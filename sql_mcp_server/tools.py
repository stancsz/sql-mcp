from __future__ import annotations
import logging
import re
from typing import Any, Dict, List

from sqlalchemy.engine import Engine
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("sql_mcp_server.tools")

# Forbidden keywords that must not appear in read-only queries.
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
}

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
    """Remove -- single-line and /* */ block comments."""
    # remove block comments first
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    # remove single-line comments
    sql = re.sub(r"--.*?$", " ", sql, flags=re.M)
    return sql


def _is_read_only_sql_regex(sql: str) -> bool:
    """
    Conservative regex-based check (fallback).
    - Remove comments
    - Ensure exactly one statement (no multi-statement separated by ;)
    - Ensure first token is SELECT or WITH
    - Ensure none of the forbidden keywords appear as whole words
    """
    stripped = _strip_sql_comments(sql).strip()
    if not stripped:
        return False
    # disallow multiple statements separated by semicolon
    parts = [p for p in re.split(r";\s*", stripped) if p.strip()]
    if len(parts) != 1:
        return False
    first_match = re.match(r"^\s*(\(?\s*)*(?P<first>\w+)", stripped, flags=re.I)
    if not first_match:
        return False
    first_token = first_match.group("first").upper()
    if first_token not in {"SELECT", "WITH"}:
        return False
    # ensure forbidden keywords not present as whole words
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", stripped, flags=re.I):
            return False
    return True


def _is_read_only_sql_sqlparse(sql: str) -> bool:
    """
    Stronger SQL validation using sqlparse token inspection.

    Rules:
    - Use sqlparse.split() to ensure a single statement (ignoring empty segments).
    - Parse the statement and ensure the first meaningful token is SELECT or WITH.
    - Walk the flattened token stream and reject if a real SQL Keyword token
      (DDL/DML) matches any FORBIDDEN_KEYWORDS.
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

        # First meaningful token must be SELECT or WITH
        first_token = stmt.token_first(skip_cm=True)
        if first_token is None:
            return False
        ft_val = getattr(first_token, "value", str(first_token)).strip()
        first_word = ft_val.split(maxsplit=1)[0].upper() if ft_val else ""
        if first_word not in {"SELECT", "WITH"}:
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
            # Additionally, defense-in-depth: if a standalone forbidden word appears
            # in the stripped SQL outside of string/comments, reject.
        stripped = _strip_sql_comments(sql)
        for kw in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{kw}\b", stripped, flags=re.I):
                # If the regex finds the word, ensure it's not only present inside a string literal.
                # We already skipped string literals above, so this is an extra safety net.
                logger.debug("Rejected query due to forbidden keyword detected by regex: %s", kw)
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
        Raises ValueError if query is not permitted or execution fails.
        """
        if not _is_read_only_sql(sql_query):
            raise ValueError("Only single-statement read-only SELECT/WITH queries are allowed")
        try:
            with self.engine.connect() as conn:
                # Use a safe SQL text construct; SQLAlchemy will handle parameters and execution.
                stmt = text(sql_query)
                result = conn.execute(stmt)
                # mappings() returns rows as dict-like objects
                rows = [dict(r) for r in result.mappings().all()]
                return rows
        except SQLAlchemyError as exc:
            logger.exception("Error executing read-only SQL")
            # propagate as ValueError for the MCP layer to surface
            raise ValueError(f"Error executing query: {exc}") from exc
