from __future__ import annotations
import pytest
from sqlalchemy import MetaData, Table, Column, Integer, String
from sql_mcp_server.db import create_engine_from_url
from sql_mcp_server.tools import SQLMCPTools

@pytest.fixture
def engine():
    """Create an in-memory SQLite engine for integration tests."""
    url = "sqlite+pysqlite:///:memory:"
    eng = create_engine_from_url(url)
    # create a sample table
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(50), nullable=False),
        Column("age", Integer, nullable=True),
    )
    Table(
        "items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("owner_id", Integer),
        Column("title", String(100)),
    )
    metadata.create_all(eng)
    # seed some data
    with eng.begin() as conn:
        conn.exec_driver_sql("INSERT INTO users (id, name, age) VALUES (1, 'alice', 30)")
        conn.exec_driver_sql("INSERT INTO users (id, name, age) VALUES (2, 'bob', 25)")
        conn.exec_driver_sql("INSERT INTO items (id, owner_id, title) VALUES (1, 1, 'item-a')")
    return eng

def test_list_tables(engine):
    tools = SQLMCPTools(engine)
    tables = tools.list_tables()
    assert "users" in tables
    assert "items" in tables

def test_get_table_schema(engine):
    tools = SQLMCPTools(engine)
    schema = tools.get_table_schema("users")
    names = [c["name"] for c in schema]
    assert "id" in names
    assert "name" in names
    assert any(c["primary_key"] for c in schema if c["name"] == "id")

def test_execute_read_only_sql_ok(engine):
    tools = SQLMCPTools(engine)
    rows = tools.execute_read_only_sql("SELECT id, name FROM users ORDER BY id")
    assert isinstance(rows, list)
    assert rows[0]["id"] == 1
    assert rows[0]["name"] == "alice"

def test_execute_read_only_sql_with_cte(engine):
    tools = SQLMCPTools(engine)
    sql = """
    WITH u AS (SELECT id, name FROM users)
    SELECT name FROM u WHERE id = 2
    """
    rows = tools.execute_read_only_sql(sql)
    assert rows[0]["name"] == "bob"

@pytest.mark.parametrize("bad_sql", [
    "DROP TABLE users",
    "INSERT INTO users (id) VALUES (3)",
    "UPDATE users SET name='x' WHERE id=1",
    "SELECT * FROM users; DROP TABLE items",
    "CREATE TABLE t(x int)",
])
def test_execute_read_only_sql_rejects_bad(engine, bad_sql):
    tools = SQLMCPTools(engine)
    with pytest.raises(ValueError):
        tools.execute_read_only_sql(bad_sql)
