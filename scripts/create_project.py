#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project generator for the SQL MCP server.
Run this script from the repository root to create the complete project structure and files.

Usage:
    python scripts/create_project.py

This script writes the full project files as specified by the user request.
"""
from pathlib import Path
from textwrap import dedent

ROOT = Path(".").resolve()

files = {
    "pyproject.toml": dedent("""\
        [project]
        name = "sql-mcp-server"
        version = "0.1.0"
        description = "A configurable SQL MCP server using fastmcp, SQLAlchemy and pydantic-settings."
        readme = "README.md"
        requires-python = ">=3.10"
        authors = [{name = "sql-mcp", email = "dev@example.com"}]
        license = {text = "MIT"}

        [project.dependencies]
        fastmcp = "^0.1"
        SQLAlchemy = "^1.4"
        pydantic-settings = "^0.1"
        pydantic = "^2.6"
        psycopg2-binary = {version = "^2.9", optional = true}
        pymysql = {version = "^1.0", optional = true}
        pyodbc = {version = "^4.0", optional = true}

        [project.optional-dependencies]
        postgresql = ["psycopg2-binary"]
        mysql = ["pymysql"]
        mssql = ["pyodbc"]

        [tool.pytest.ini_options]
        minversion = "6.0"
        addopts = "-q"

        [build-system]
        requires = ["setuptools", "wheel"]
        build-backend = "setuptools.build_meta"
        """),

    ".gitignore": dedent("""\
        __pycache__/
        *.pyc
        .env
        .env.* 
        .idea/
        .vscode/
        dist/
        build/
        *.egg-info
        """),

    "README.md": dedent("""\
        # SQL MCP Server

        輕量可配置的 SQL MCP server，提供 list_tables, get_table_schema, execute_read_only_sql 等工具給 AI 使用。

        配置（環境變數）
        - DB_TYPE: postgresql | mysql | mssql | sqlite  (預設: sqlite)
        - DB_HOST
        - DB_PORT
        - DB_USER
        - DB_PASS
        - DB_NAME

        執行 (範例)
        ```bash
        export DB_TYPE=sqlite
        export DB_NAME=":memory:"
        python -m sql_mcp_server.server
        ```

        測試
        ```bash
        pip install -e .[postgresql,mysql,mssql]
        pip install pytest
        pytest
        ```
        """),

    "sql_mcp_server/__init__.py": dedent("""\
        \"\"\"sql_mcp_server package\"\"\"
        __version__ = "0.1.0"
        """),

    "sql_mcp_server/config.py": dedent("""\
        from __future__ import annotations
        from typing import Optional
        from pydantic_settings import BaseSettings

        class Settings(BaseSettings):
            \"\"\"
            Configuration loaded from environment variables.

            Environment variables:
              - DB_TYPE: postgresql | mysql | mssql | sqlite
              - DB_HOST
              - DB_PORT
              - DB_USER
              - DB_PASS
              - DB_NAME
            \"\"\"

            DB_TYPE: str = "sqlite"
            DB_HOST: Optional[str] = "localhost"
            DB_PORT: Optional[int] = None
            DB_USER: Optional[str] = None
            DB_PASS: Optional[str] = None
            DB_NAME: str = ":memory:"

            class Config:
                env_prefix = ""
                env_file = ".env"

            def database_url(self) -> str:
                \"\"\"Construct a SQLAlchemy database URL based on settings.\"\"\"
                db_type = self.DB_TYPE.lower()
                if db_type in (\"sqlite\",):
                    # in-memory default
                    if self.DB_NAME == \":memory:\":
                        return \"sqlite+pysqlite:///:memory:\"
                    # file-based sqlite
                    return f\"sqlite+pysqlite:///{self.DB_NAME}\"
                if db_type in (\"postgresql\", \"postgres\"):
                    port = f\":{self.DB_PORT}\" if self.DB_PORT else \"\"
                    user = self.DB_USER or \"\"
                    password = self.DB_PASS or \"\"
                    creds = f\"{user}:{password}@\" if user or password else \"\"
                    return f\"postgresql+psycopg2://{creds}{self.DB_HOST}{port}/{self.DB_NAME}\"
                if db_type in (\"mysql\",):
                    port = f\":{self.DB_PORT}\" if self.DB_PORT else \"\"
                    user = self.DB_USER or \"\"
                    password = self.DB_PASS or \"\"
                    creds = f\"{user}:{password}@\" if user or password else \"\"
                    return f\"mysql+pymysql://{creds}{self.DB_HOST}{port}/{self.DB_NAME}\"
                if db_type in (\"mssql\", \"sqlserver\"):
                    # Uses pyodbc DSN style, user must ensure driver installed and connection works
                    port = f\":{self.DB_PORT}\" if self.DB_PORT else \"\"
                    user = self.DB_USER or \"\"
                    password = self.DB_PASS or \"\"
                    creds = f\"{user}:{password}@\" if user or password else \"\"
                    driver = \"ODBC+Driver+17+for+SQL+Server\"
                    return f\"mssql+pyodbc://{creds}{self.DB_HOST}{port}/{self.DB_NAME}?driver={driver}\"
                raise ValueError(f\"Unsupported DB_TYPE: {self.DB_TYPE}\")
        """),

    "sql_mcp_server/db.py": dedent("""\
        from __future__ import annotations
        from typing import Optional
        from sqlalchemy import create_engine, inspect, text, MetaData
        from sqlalchemy.engine import Engine
        from .config import Settings

        def create_engine_from_settings(settings: Settings) -> Engine:
            \"\"\"
            Create a SQLAlchemy Engine from Settings.

            Uses reasonable defaults for pooling and pre-ping to keep connections healthy.
            \"\"\"
            url = settings.database_url()
            return create_engine(
                url,
                future=True,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
            )

        def create_engine_from_url(url: str) -> Engine:
            \"\"\"Helper to create engine directly from a URL (used in tests).\"\"\"
            return create_engine(url, future=True, pool_pre_ping=True)
        """),

    "sql_mcp_server/tools.py": dedent("""\
        from __future__ import annotations
        import re
        from typing import Any, Dict, List
        from sqlalchemy.engine import Engine
        from sqlalchemy import inspect, text
        from sqlalchemy.exc import SQLAlchemyError

        FORBIDDEN_KEYWORDS = {
            \"INSERT\",
            \"UPDATE\",
            \"DELETE\",
            \"DROP\",
            \"CREATE\",
            \"ALTER\",
            \"TRUNCATE\",
            \"GRANT\",
            \"REVOKE\",
            \"MERGE\",
        }

        def _strip_sql_comments(sql: str) -> str:
            \"\"\"Remove -- single-line and /* */ block comments.\"\"\"
            # remove block comments first
            sql = re.sub(r\"/\\*.*?\\*/\", \" \", sql, flags=re.S)
            # remove single-line comments
            sql = re.sub(r\"--.*?$\", \" \", sql, flags=re.M)
            return sql

        def _is_read_only_sql(sql: str) -> bool:
            \"\"\"
            Very conservative check:
            - Remove comments
            - Ensure there's exactly one statement (no multiple ';' separated statements)
            - Ensure the first token is SELECT or WITH
            - Ensure none of the forbidden keywords appear as separate words anywhere
            \"\"\"
            stripped = _strip_sql_comments(sql).strip()
            if not stripped:
                return False
            # disallow multiple statements separated by semicolon
            parts = [p for p in re.split(r\";\\s*\", stripped) if p.strip()]
            if len(parts) != 1:
                return False
            first_match = re.match(r\"^\\s*(\\(?\\s*)*(?P<first>\\w+)\", stripped, flags=re.I)
            if not first_match:
                return False
            first_token = first_match.group(\"first\").upper()
            if first_token not in {\"SELECT\", \"WITH\"}:
                return False
            # ensure forbidden keywords not present as whole words
            for kw in FORBIDDEN_KEYWORDS:
                if re.search(rf\"\\b{kw}\\b\", stripped, flags=re.I):
                    return False
            return True

        class SQLMCPTools:
            \"\"\"
            Container for database-aware tools exposed to the MCP server.

            The instance holds a SQLAlchemy Engine (connection pool) and provides:
              - list_tables()
              - get_table_schema(table_name)
              - execute_read_only_sql(sql_query)
            \"\"\"

            def __init__(self, engine: Engine) -> None:
                self.engine = engine

            def list_tables(self) -> List[str]:
                \"\"\"
                Return list of table and view names in the target database.
                \"\"\"
                inspector = inspect(self.engine)
                tables = inspector.get_table_names()
                views = inspector.get_view_names()
                # combine and return sorted unique list
                return sorted(dict.fromkeys(tables + views))

            def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
                \"\"\"
                Return list of column metadata for the given table:
                - name, type, nullable, primary_key, default
                \"\"\"
                inspector = inspect(self.engine)
                if table_name not in inspector.get_table_names() and table_name not in inspector.get_view_names():
                    raise ValueError(f\"Table or view '{table_name}' does not exist\")
                columns = inspector.get_columns(table_name)
                schema = []
                for col in columns:
                    schema.append(
                        {
                            \"name\": col.get(\"name\"),
                            \"type\": str(col.get(\"type\")),
                            \"nullable\": bool(col.get(\"nullable\", True)),
                            \"primary_key\": bool(col.get(\"primary_key\", False)),
                            \"default\": col.get(\"default\"),
                        }
                    )
                return schema

            def execute_read_only_sql(self, sql_query: str) -> List[Dict[str, Any]]:
                \"\"\"
                Execute a read-only SQL query and return rows as list of dicts.
                Strictly enforces read-only policy using _is_read_only_sql guard.
                Raises ValueError if query is not permitted.
                \"\"\"
                if not _is_read_only_sql(sql_query):
                    raise ValueError(\"Only single-statement read-only SELECT/WITH queries are allowed\")
                try:
                    with self.engine.connect() as conn:
                        stmt = text(sql_query)
                        result = conn.execute(stmt)
                        # mappings() returns rows as dict-like objects
                        rows = [dict(r) for r in result.mappings().all()]
                        return rows
                except SQLAlchemyError as exc:
                    # propagate as ValueError for the MCP to surface
                    raise ValueError(f\"Error executing query: {exc}\") from exc
        """),

    "sql_mcp_server/server.py": dedent("""\
        from __future__ import annotations
        import os
        import logging
        from .config import Settings
        from .db import create_engine_from_settings
        from .tools import SQLMCPTools

        log = logging.getLogger("sql_mcp_server")
        log.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)

        def build_server():
            \"\"\"
            Build and return a fastmcp server instance with registered tools.

            Note: fastmcp API surface may differ by version. This module expects fastmcp
            to provide a simple server or registry to register callable tools. Adjust as needed.
            \"\"\"
            try:
                import fastmcp
            except Exception as exc:  # pragma: no cover - runtime check
                raise RuntimeError("fastmcp is required to run the MCP server. Install it in your environment.") from exc

            settings = Settings()
            engine = create_engine_from_settings(settings)
            tools = SQLMCPTools(engine)

            # The following is a generic registration pattern. If fastmcp defines
            # different decorators / APIs, adapt accordingly.
            server = fastmcp.MCPServer(name="sql-mcp")

            @server.tool(name="list_tables")
            def list_tables_tool() -> list[str]:
                \"\"\"Return list of table & view names.\"\"\"
                return tools.list_tables()

            @server.tool(name="get_table_schema")
            def get_table_schema_tool(table_name: str) -> list[dict]:
                \"\"\"Return schema for named table/view.\"\"\"
                return tools.get_table_schema(table_name)

            @server.tool(name="execute_read_only_sql")
            def execute_read_only_sql_tool(sql_query: str) -> list[dict]:
                \"\"\"Execute read-only SQL query and return rows.\"\"\"
                return tools.execute_read_only_sql(sql_query)

            return server

        def main():
            \"\"\"
            Start the MCP server. The precise run API depends on fastmcp implementation.
            This function attempts to call `run()` on the returned server object.
            \"\"\"
            server = build_server()
            # Attempt to run; if API differs, user should adapt accordingly.
            if hasattr(server, "run"):
                server.run()
            else:
                # fallback: print registration summary and wait
                log.info("MCP server built but `run()` not found on server object. Tools registered.")
                for t in ("list_tables", "get_table_schema", "execute_read_only_sql"):
                    log.info("Registered tool: %s", t)
                # keep process alive if desired
                try:
                    import time
                    while True:
                        time.sleep(3600)
                except KeyboardInterrupt:
                    log.info("Server shutting down.")

        if __name__ == "__main__":
            main()
        """),

    "tests/test_tools.py": dedent("""\
        from __future__ import annotations
        import pytest
        from sqlalchemy import MetaData, Table, Column, Integer, String
        from sql_mcp_server.db import create_engine_from_url
        from sql_mcp_server.tools import SQLMCPTools

        @pytest.fixture
        def engine():
            \"\"\"Create an in-memory SQLite engine for integration tests.\"\"\"
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
                conn.execute("INSERT INTO users (id, name, age) VALUES (1, 'alice', 30)")
                conn.execute("INSERT INTO users (id, name, age) VALUES (2, 'bob', 25)")
                conn.execute("INSERT INTO items (id, owner_id, title) VALUES (1, 1, 'item-a')")
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
            sql = \"\"\"
            WITH u AS (SELECT id, name FROM users)
            SELECT name FROM u WHERE id = 2
            \"\"\"
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
        """),
}

def ensure_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

def write_file(rel_path: str, content: str) -> None:
    path = ROOT / rel_path
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
    print(f"Wrote: {rel_path}")

def main():
    for rel, content in files.items():
        write_file(rel, content)
    print("Project files created. Run pytest to execute the test suite.")

if __name__ == "__main__":
    main()
