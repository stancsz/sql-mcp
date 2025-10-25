from __future__ import annotations
import os
import time
import pytest
from sqlalchemy import MetaData, Table, Column, Integer, String
from sql_mcp_server.db import create_engine_from_url
from sql_mcp_server.tools import SQLMCPTools
from sql_mcp_server.config import Settings

@pytest.mark.integration
def test_postgres_integration_list_tables():
    """
    Integration test that runs against a Postgres service defined in docker-compose.
    Requires environment variables (see .env.example) or docker-compose up.
    """
    settings = Settings()
    engine = create_engine_from_url(settings.database_url())
    metadata = MetaData()
    Table(
        "integration_users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(50), nullable=False),
    )
    metadata.create_all(engine)
    # Insert a row
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO integration_users (id, name) VALUES (1, 'alice')")
    tools = SQLMCPTools(engine)
    tables = tools.list_tables()
    assert "integration_users" in tables
