"""
Pytest conftest to ensure the project package is importable during tests.

This adds the repository root to sys.path so test modules can import the
local `sql_mcp_server` package without needing an editable install.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Shared fixtures for tests
import pytest  # noqa: E402
from sqlalchemy import MetaData, Table, Column, Integer, String, text  # noqa: E402
from sql_mcp_server.db import create_engine_from_url  # noqa: E402

@pytest.fixture
def engine():
    """
    Provide an in-memory SQLite Engine with a small sample schema and seed data.

    This fixture is used by multiple tests across the suite so it lives in
    conftest.py to ensure pytest discovery finds it for all test modules.
    """
    url = "sqlite+pysqlite:///:memory:"
    eng = create_engine_from_url(url)

    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(50)),
        Column("age", Integer),
    )
    Table(
        "items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("owner_id", Integer),
        Column("title", String(100)),
    )

    metadata.create_all(eng)

    with eng.begin() as conn:
        conn.execute(text("INSERT INTO users (id, name, age) VALUES (1, 'alice', 30)"))
        conn.execute(text("INSERT INTO users (id, name, age) VALUES (2, 'bob', 25)"))
        conn.execute(text("INSERT INTO items (id, owner_id, title) VALUES (1, 1, 'item-a')"))

    return eng
