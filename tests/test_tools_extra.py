from __future__ import annotations
import pytest
from sql_mcp_server.tools import SQLMCPTools

# Reuse the existing `engine` fixture from tests/test_tools.py
# Tests cover edge cases around read-only SQL validation.

def test_execute_allows_forbidden_keywords_in_comments(engine):
    tools = SQLMCPTools(engine)
    sql = """
    -- DROP TABLE users;
    /* INSERT INTO users (id) VALUES (3); */
    SELECT id FROM users WHERE id = 1
    """
    rows = tools.execute_read_only_sql(sql)
    assert rows and rows[0]["id"] == 1

def test_execute_rejects_multi_statement_with_semicolon(engine):
    tools = SQLMCPTools(engine)
    bad = "SELECT id FROM users; SELECT name FROM users"
    with pytest.raises(ValueError):
        tools.execute_read_only_sql(bad)

def test_execute_allows_leading_parenthesis_select(engine):
    tools = SQLMCPTools(engine)
    sql = "(SELECT id FROM users WHERE id = 2)"
    rows = tools.execute_read_only_sql(sql)
    assert rows and rows[0]["id"] == 2

def test_execute_rejects_forbidden_keyword_inside_string_literal(engine):
    # Conservative validator will reject queries containing forbidden keywords
    # even inside string literals — ensure this is enforced.
    tools = SQLMCPTools(engine)
    bad = "SELECT 'DROP TABLE users' as payload"
    with pytest.raises(ValueError):
        tools.execute_read_only_sql(bad)

def test_execute_allows_sql_with_leading_comments_and_whitespace(engine):
    tools = SQLMCPTools(engine)
    sql = """
    -- leading comment
    /* block comment */
    
    SELECT name FROM users WHERE id = 1
    """
    rows = tools.execute_read_only_sql(sql)
    assert rows and rows[0]["name"] == "alice"
