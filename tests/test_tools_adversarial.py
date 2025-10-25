from __future__ import annotations
import pytest
from sql_mcp_server.tools import SQLMCPTools, _HAS_SQLPARSE
from typing import List

# Reuse the existing `engine` fixture from tests/test_tools.py

ACCEPT_QUERIES: List[str] = [
    # Simple select
    "SELECT id FROM users WHERE id = 1",
    # Leading parentheses (nested)
    "((SELECT id FROM users WHERE id = 2))",
    # CTE with nested select
    """
    WITH u AS (SELECT id, name FROM users WHERE id IN (1,2))
    SELECT name FROM u WHERE id = 2
    """,
    # EXPLAIN allowed
    "EXPLAIN SELECT id FROM users",
    # VALUES clause
    "VALUES (1),(2)",
    # Trailing semicolon only
    "SELECT id FROM users WHERE id = 1;",
    # Forbidden keyword inside a string literal (should be allowed)
    "SELECT 'DROP TABLE users' as payload",
]

REJECT_QUERIES: List[str] = [
    # Multiple statements
    "SELECT id FROM users; DROP TABLE users;",
    # Multiple statements with semicolon in middle
    "SELECT 1; SELECT 2",
    # Transaction control
    "BEGIN; SELECT 1; COMMIT;",
    # COPY command
    "COPY users FROM STDIN",
    # SET config
    "SET search_path = public",
    # VACUUM
    "VACUUM",
    # ATTACH
    "ATTACH DATABASE 'file.db' AS other",
    # DDL create/drop
    "CREATE TABLE t(x int)",
    "DROP TABLE users",
    # DML insert/update/delete
    "INSERT INTO users (id) VALUES (3)",
    "UPDATE users SET name = 'x' WHERE id = 1",
    "DELETE FROM users WHERE id = 1",
]

@pytest.mark.parametrize("sql", ACCEPT_QUERIES)
def test_accept_queries(engine, sql: str):
    tools = SQLMCPTools(engine)
    # Special-case: string-literal containing forbidden keyword
    if sql.strip().upper().startswith("SELECT") and "DROP TABLE USERS" in sql.upper():
        # If sqlparse available, allow; otherwise conservative fallback may reject.
        if _HAS_SQLPARSE:
            rows = tools.execute_read_only_sql(sql)
            assert isinstance(rows, list)
            return
        else:
            with pytest.raises(ValueError):
                tools.execute_read_only_sql(sql)
            return

    rows = tools.execute_read_only_sql(sql)
    assert isinstance(rows, list)

@pytest.mark.parametrize("sql", REJECT_QUERIES)
def test_reject_queries(engine, sql: str):
    tools = SQLMCPTools(engine)
    with pytest.raises(ValueError):
        tools.execute_read_only_sql(sql)

def test_reject_keyword_embedded_outside_strings(engine):
    tools = SQLMCPTools(engine)
    # keyword appearing as part of identifier should not by itself allow dangerous ops,
    # but validator should not be tricked by words embedded in longer identifiers.
    sql = "SELECT id FROM users WHERE name LIKE '%drop table users%';"
    # If sqlparse is present, string literal protection should allow this (it's inside a string),
    # otherwise conservative fallback will likely reject.
    if _HAS_SQLPARSE:
        rows = tools.execute_read_only_sql(sql)
        assert isinstance(rows, list)
    else:
        with pytest.raises(ValueError):
            tools.execute_read_only_sql(sql)

def test_reject_copy_with_comment_trick(engine):
    tools = SQLMCPTools(engine)
    # Attempt to hide a forbidden keyword using comments: should still be rejected
    sql = "/* comment */ COPY users FROM STDIN -- more"
    with pytest.raises(ValueError):
        tools.execute_read_only_sql(sql)

def test_reject_set_in_whitespace_variations(engine):
    tools = SQLMCPTools(engine)
    sql = "  SeT   search_path = public"
    with pytest.raises(ValueError):
        tools.execute_read_only_sql(sql)

def test_accept_explain_with_leading_comments(engine):
    tools = SQLMCPTools(engine)
    sql = "-- comment\nEXPLAIN\nSELECT id FROM users WHERE id = 1"
    rows = tools.execute_read_only_sql(sql)
    assert isinstance(rows, list)
