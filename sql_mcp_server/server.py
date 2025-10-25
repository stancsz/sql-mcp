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
    """
    Build and return a fastmcp server instance with registered tools.

    Note: fastmcp API surface may differ by version. This module expects fastmcp
    to provide a simple server or registry to register callable tools. Adjust as needed.
    """
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
        """Return list of table & view names."""
        return tools.list_tables()

    @server.tool(name="get_table_schema")
    def get_table_schema_tool(table_name: str) -> list[dict]:
        """Return schema for named table/view."""
        return tools.get_table_schema(table_name)

    @server.tool(name="execute_read_only_sql")
    def execute_read_only_sql_tool(sql_query: str) -> list[dict]:
        """Execute read-only SQL query and return rows."""
        return tools.execute_read_only_sql(sql_query)

    return server

def main():
    """
    Start the MCP server. The precise run API depends on fastmcp implementation.
    This function attempts to call `run()` on the returned server object.
    """
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
