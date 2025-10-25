"""
sql_mcp_server.tools

Read-only SQL validation and execution helpers.

Purpose
- Enforce a strict read-only policy for user-provided SQL executed by the server.
- Provide utilities used by SQLMCPTools.execute_read_only_sql() to normalize,
  validate, and safely execute SELECT-style queries.

Policy summary
- Allowed leading statements: SELECT, WITH, EXPLAIN, VALUES.
- Disallowed keywords (examples): INSERT, UPDATE, DELETE, DROP, CREATE,
  ALTER, TRUNCATE, GRANT, REVOKE, MERGE, COPY, BEGIN, COMMIT, ROLLBACK,
  SET, ATTACH, VACUUM.
- Only single-statement queries are permitted. Multi-statement payloads are rejected.
- Validation errs on the side of safety: when in doubt the validator rejects.

Validation strategy
1. Prefer sqlparse token-level validation when the `sqlparse` package is
   available:
   - Use sqlparse.split()/parse() to ensure a single statement.
   - Confirm the first meaningful token is in the allowed set.
   - Walk the flattened token stream and reject any Keyword tokens that
     match forbidden keywords, while skipping comments and string literals.
   - sqlparse reduces false positives by distinguishing keywords from literal text.

2. Conservative regex fallback (when sqlparse is not present):
   - Strip comments, remove string/dollar-quoted literals for statement-splitting,
     ensure a single statement and that the first token is allowed.
   - For keyword scanning the fallback checks the comment-stripped SQL without
     removing string literals (conservative) and will reject queries that
     include forbidden words even if they appear inside string literals.
   - This means environments lacking sqlparse will be more conservative.

Notes for operators & CI
- Recommended: install the parsing extras in CI to run sqlparse-based checks:
  python -m pip install -e ".[parsing]"
- CI should explicitly test both paths if desired (with and without sqlparse),
  or include sqlparse to mirror production parsing behavior.
- The implementation prioritizes safety; additional runtime limits (query
  length, execution timeout) are recommended as follow-up tasks.
"""
from __future__ import annotations
import logging
import re
from typing import Any, Dict, List

from sqlalchemy.engine import Engine
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("sql_mcp_server.tools")

# Expanded forbidden keywords that must not appear in read-only queries.
FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "MERGE",
    "COPY",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SET",
    "ATTACH",
    "VACUUM",
}

# Allowed leading statements for read-only queries.
ALLOWED_LEADING_KEYWORDS = {"SELECT", "WITH", "EXPLAIN", "VALUES"}

# Try to import sqlparse for stronger validation if available.
try:
    import sqlparse  # type: ignore
    from sqlparse.sql import Token  # type: ignore

    _HAS_SQLPARSE = True
    logger.debug("sqlparse is available, stronger SQL validation enabled.")
except Exception:
    sqlparse = None  # type: ignore
    _HAS_SQLPARSE = False
    logger.debug("sqlparse not available, falling back to conservative regex checks.")

def _strip_sql_comments(sql: str) -> str:
    """Remove --, # single-line and /* */ block comments."""
    # remove block comments first (/* ... */)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    # remove -- single-line comments
    sql = re.sub(r"--.*?$", " ", sql, flags=re.M)
    # remove hash-style (#) single-line comments (common in some clients)
    sql = re.sub(r"#.*?$", " ", sql, flags=re.M)
    return sql

def _strip_string_literals(sql: str) -> str:
    """
    Replace string and quoted literal contents with spaces so that keyword
    scanning does not match words inside string literals.

    Handles:
      - single-quoted strings '...'
      - double-quoted strings "..." (often used for identifiers)
      - dollar-quoted strings $tag$...$tag$
      - simple escaped quotes via backslash are handled conservatively
    """
    s = sql

    # Remove dollar-quoted strings: $tag$ ... $tag$
    s = re.sub(r"\$[^$]*\$.*?\$[^$]*\$", " ", s, flags=re.S)

    # Remove single- and double-quoted strings (naive but practical)
    # Handles escaped quotes by allowing backslashes inside.
    s = re.sub(r"'(?:\\.|''|[^'])*'", " ", s, flags=re.S)
    s = re.sub(r'"(?:\\.|""|[^"])*"', " ", s, flags=re.S)

    return s

def _strip_outer_parentheses(sql: str) -> str:
    """
    Remove a single pair (or repeated nested pairs) of balanced outer
    parentheses that enclose the entire statement.

    This helps databases like SQLite which do not accept a top-level
    parenthesized SELECT (e.g. "(SELECT ... )"). The function only
    removes outer pairs that balance across the whole string and will
    not touch parentheses that are not enclosing the full statement.
    """
    s = sql.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        match_index = None
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    match_index = i
                    break
        # If the first matching closing parenthesis is at the very end,
        # the outer parentheses enclose the whole string -> strip them.
        if match_index is not None and match_index == len(s) - 1:
            s = s[1:-1].strip()
            # continue to remove additional nested outer pairs, if any
            continue
        break
    return s

def _is_read_only_sql_regex(sql: str) -> bool:
    """
    Conservative regex-based check (fallback).

    Strategy:
    - Strip comments first.
    - For statement-count and first-token detection, remove string/dollar-quoted literals
      so semicolons and tokens inside strings do not mislead the splitter.
    - For forbidden-keyword scanning, use the comment-stripped SQL (do NOT remove
      string literals) to be conservative when sqlparse is not available — this
      rejects queries that include forbidden words even inside string literals.
    """
    # Strip comments first
    stripped_comments = _strip_sql_comments(sql).strip()
    if not stripped_comments:
        return False

    # Remove string literals only for splitting/token-detection so semicolons inside
    # strings don't create false multi-statement detections.
    stripped_for_split = _strip_string_literals(stripped_comments)

    # Naively split on semicolons in the string-literal-stripped SQL.
    parts = [p for p in re.split(r";\s*", stripped_for_split) if p.strip()]
    if len(parts) != 1:
        return False

    # Determine first word/token from the string-literal-stripped SQL
    first_match = re.match(r"^\s*(\(?\s*)*(?P<first>\w+)", stripped_for_split, flags=re.I)
    if not first_match:
        return False
    first_token = first_match.group("first").upper()
    if first_token not in ALLOWED_LEADING_KEYWORDS:
        return False

    # Conservative keyword scanning: check the comment-stripped SQL (not removing strings)
    # to ensure we err on the side of safety when sqlparse is absent.
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", stripped_comments, flags=re.I):
            return False

    return True

def _is_read_only_sql_sqlparse(sql: str) -> bool:
    """
    Stronger SQL validation using sqlparse token inspection.

    Rules:
    - Use sqlparse.split() to ensure a single statement (ignoring empty segments).
    - Parse the statement and ensure the first meaningful token is in ALLOWED_LEADING_KEYWORDS.
    - Walk the flattened token stream and reject if a real SQL Keyword token
      matches any FORBIDDEN_KEYWORDS.
    - Ignore occurrences of forbidden words inside string literals or comments.
    - On unexpected parse errors we conservatively reject (safe-fail).
    """
    try:
        # Ensure only a single statement
        statements = sqlparse.split(sql)
        if len([s for s in statements if s.strip()]) != 1:
            return False

        parsed = sqlparse.parse(sql)
        if not parsed:
            return False
        stmt = parsed[0]

        # First meaningful token must be in allowed set
        first_token = stmt.token_first(skip_cm=True)
        if first_token is None:
            return False
        ft_val = getattr(first_token, "value", str(first_token)).strip()
        first_word = ft_val.split(maxsplit=1)[0].upper() if ft_val else ""
        if first_word not in ALLOWED_LEADING_KEYWORDS:
            return False

        # Walk tokens and detect forbidden keywords that are real SQL keywords.
        # Ignore comments and string literals.
        try:
            from sqlparse import tokens as T  # local import for readability
        except Exception:
            # if tokens module missing, fallback to conservative regex approach
            stripped = _strip_sql_comments(sql)
            for kw in FORBIDDEN_KEYWORDS:
                if re.search(rf"\b{kw}\b", stripped, flags=re.I):
                    return False
            return True

        for token in stmt.flatten():
            # Skip comments
            if token.ttype and str(token.ttype).startswith("Token.Comment"):
                continue
            # Skip string literals
            if token.ttype and str(token.ttype).startswith("Token.Literal.String"):
                continue
            # If token looks like a Keyword token, inspect its value
            if token.ttype and str(token.ttype).startswith("Token.Keyword"):
                val = (token.value or "").strip().upper()
                if val in FORBIDDEN_KEYWORDS:
                    logger.debug("Rejected query due to forbidden keyword token: %s", val)
                    return False

        # Additional safety net: regex scan on comment-stripped, string-stripped SQL
        stripped_no_strings = _strip_string_literals(_strip_sql_comments(sql))
        for kw in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{kw}\b", stripped_no_strings, flags=re.I):
                logger.debug(
                    "Rejected query due to forbidden keyword detected by regex after stripping strings: %s", kw
                )
                return False

        return True
    except Exception as exc:
        # On unexpected parse errors, be conservative and reject the query.
        logger.exception("sqlparse-based validation encountered an error; rejecting query")
        return False

def _is_read_only_sql(sql: str) -> bool:
    """
    Decide which validator to use: prefer sqlparse if available,
    otherwise fall back to conservative regex checks.

    Notes:
      - This validator errs on the side of safety: when in doubt it rejects.
      - Allowed starting statements: SELECT, WITH, EXPLAIN, VALUES.
    """
    if _HAS_SQLPARSE:
        return _is_read_only_sql_sqlparse(sql)
    return _is_read_only_sql_regex(sql)

class SQLMCPTools:
    """
    Container for database-aware tools exposed to the MCP server.

    Holds a SQLAlchemy Engine (connection pool) and provides:
      - list_tables()
      - get_table_schema(table_name)
      - execute_read_only_sql(sql_query)
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_tables(self) -> List[str]:
        """
        Return list of table and view names in the target database.
        """
        inspector = inspect(self.engine)
        tables = inspector.get_table_names()
        views = inspector.get_view_names()
        # combine and return sorted unique list
        return sorted(dict.fromkeys(tables + views))

    def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        """
        Return list of column metadata for the given table:
        - name, type, nullable, primary_key, default
        """
        inspector = inspect(self.engine)
        if table_name not in inspector.get_table_names() and table_name not in inspector.get_view_names():
            raise ValueError(f"Table or view '{table_name}' does not exist")
        columns = inspector.get_columns(table_name)
        schema: List[Dict[str, Any]] = []
        for col in columns:
            schema.append(
                {
                    "name": col.get("name"),
                    "type": str(col.get("type")),
                    "nullable": bool(col.get("nullable", True)),
                    "primary_key": bool(col.get("primary_key", False)),
                    "default": col.get("default"),
                }
            )
        return schema

    def execute_read_only_sql(self, sql_query: str) -> List[Dict[str, Any]]:
        """
        Execute a read-only SQL query and return rows as list of dicts.

        Strictly enforces read-only policy using _is_read_only_sql guard.
        Instrumentation: if prometheus-client is available, record request counts
        and query duration. This function lazy-loads prometheus to avoid hard
        dependency when not needed.
        Raises ValueError if query is not permitted or execution fails.
        """
        # Normalize the SQL by stripping balanced outer parentheses which some
        # databases (notably SQLite) don't accept for a top-level statement.
        normalized_sql = _strip_outer_parentheses(sql_query)

        if not _is_read_only_sql(normalized_sql):
            raise ValueError("Only single-statement read-only SELECT/WITH/EXPLAIN/VALUES queries are allowed")

        # Lazy import prometheus metrics (optional)
        _metrics_enabled = False
        try:
            from prometheus_client import Counter as _Counter, Histogram as _Histogram  # type: ignore
            _metrics_enabled = True
        except Exception:
            _metrics_enabled = False

        # Initialize module-level metrics once if prometheus is available
        if _metrics_enabled:
            if "_requests_counter" not in globals():
                try:
                    globals()["_requests_counter"] = _Counter(
                        "sqlmcp_execute_requests_total",
                        "Total number of execute_read_only_sql calls",
                    )
                    globals()["_query_histogram"] = _Histogram(
                        "sqlmcp_query_duration_seconds",
                        "Duration of read-only queries in seconds",
                    )
                except Exception:
                    # Avoid failing queries if metrics cannot be registered
                    logger.exception("Failed to initialize prometheus metrics")
                    _metrics_enabled = False

        rows: List[Dict[str, Any]] = []
        from time import perf_counter

        start = perf_counter()
        try:
            with self.engine.connect() as conn:
                # Use a safe SQL text construct; SQLAlchemy will handle parameters and execution.
                # Execute the normalized SQL (outer parentheses stripped) to accommodate DBs
                # like SQLite which reject a top-level parenthesized SELECT.
                stmt = text(normalized_sql)
                result = conn.execute(stmt)
                # mappings() returns rows as dict-like objects
                rows = [dict(r) for r in result.mappings().all()]
        except SQLAlchemyError as exc:
            logger.exception("Error executing read-only SQL")
            raise ValueError(f"Error executing query: {exc}") from exc
        finally:
            elapsed = perf_counter() - start
            if _metrics_enabled:
                try:
                    globals()["_requests_counter"].inc()
                    globals()["_query_histogram"].observe(elapsed)
                except Exception:
                    logger.debug("Failed to record prometheus metrics for query")
        return rows
