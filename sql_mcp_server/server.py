from __future__ import annotations
import os
import json
import logging
from typing import Optional

from .config import Settings
from .db import create_engine_from_settings
from .tools import SQLMCPTools

# Optional HTTP server dependencies are declared in pyproject (FastAPI/uvicorn).
# This module exposes two entrypaths:
#  - build_mcp_server(): builds the fastmcp server (if fastmcp is installed)
#  - create_http_app(settings): returns a FastAPI app exposing /health and /ready
# The main() will run the HTTP server by default; set RUN_HTTP=0 to attempt MCP server.
logger = logging.getLogger("sql_mcp_server")
logger.setLevel(logging.INFO)


class JSONFormatter(logging.Formatter):
    """Simple JSON formatter for structured logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging() -> None:
    """Configure a simple structured logger for the package."""
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)


def _register_tool(server, name: str, func) -> None:
    """
    Register a tool function on a fastmcp server instance in a backward/forward
    compatible way. Tries common registration APIs and falls back to injecting
    into a tools dict when available. Raises RuntimeError if unable to register.
    """
    try:
        decorator = getattr(server, "tool", None)
        if callable(decorator):
            try:
                # decorator style: server.tool(name="...")(func)
                decorator(name=name)(func)
                return
            except TypeError:
                # some implementations may allow calling the decorator directly
                try:
                    decorator(func, name=name)
                    return
                except Exception:
                    pass
    except Exception:
        pass

    for attr in ("register_tool", "register", "add_tool", "add"):
        if hasattr(server, attr):
            method = getattr(server, attr)
            try:
                # try (name, func)
                method(name, func)
                return
            except TypeError:
                # try (func, name)
                try:
                    method(func, name)
                    return
                except Exception:
                    pass

    # Last-resort: inject into `tools` dict if present
    if hasattr(server, "tools") and isinstance(getattr(server, "tools"), dict):
        server.tools[name] = func
        return

    raise RuntimeError(f"Unable to register tool {name} on server instance of type {type(server)}")
def build_mcp_server() -> object:
    """
    Build and return a fastmcp server instance with registered tools.

    Raises RuntimeError when fastmcp is not installed.
    """
    try:
        import fastmcp  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime check
        raise RuntimeError("fastmcp is required to run the MCP server. Install it in your environment.") from exc

    settings = Settings()
    engine = create_engine_from_settings(settings)
    tools = SQLMCPTools(engine)

    server = fastmcp.MCPServer(name="sql-mcp")

    def list_tables_tool() -> list[str]:
        """Return list of table & view names."""
        return tools.list_tables()

    def get_table_schema_tool(table_name: str) -> list[dict]:
        """Return schema for named table/view."""
        return tools.get_table_schema(table_name)

    def execute_read_only_sql_tool(sql_query: str) -> list[dict]:
        """Execute read-only SQL query and return rows."""
        return tools.execute_read_only_sql(sql_query)

    # Register tools using compatibility helper
    for _name, _func in (
        ("list_tables", list_tables_tool),
        ("get_table_schema", get_table_schema_tool),
        ("execute_read_only_sql", execute_read_only_sql_tool),
    ):
        _register_tool(server, _name, _func)

    return server


def create_http_app(settings: Optional[Settings] = None):
    """
    Create and return a FastAPI app exposing basic health, readiness and metrics endpoints.

    - GET /health  -> {"status": "ok"}
    - GET /ready   -> {"db": "ok"} or HTTP 503 with {"db": "error", "reason": "..."}
    - GET /metrics -> Prometheus metrics (if prometheus-client installed) or 501
    """
    try:
        from fastapi import FastAPI, Response, status
        from fastapi.responses import JSONResponse, PlainTextResponse
        from sqlalchemy import text
    except Exception as exc:  # pragma: no cover - runtime check
        raise RuntimeError("fastapi and sqlalchemy are required for the HTTP app. Install extras.") from exc

    # optional prometheus support
    try:
        from prometheus_client import CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST, Counter, Histogram
        _HAS_PROM = True
    except Exception:
        CollectorRegistry = None  # type: ignore
        generate_latest = None  # type: ignore
        CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
        Counter = None  # type: ignore
        Histogram = None  # type: ignore
        _HAS_PROM = False

    _configure_logging()
    app = FastAPI(title="sql-mcp-server")

    # application-scoped placeholders; set in startup
    settings = settings or Settings()
    app.state.engine = None
    app.state.metrics_registry = None
    app.state.requests_counter = None
    app.state.query_histogram = None

    def _create_engine():
        return create_engine_from_settings(settings)

    @app.on_event("startup")
    def _startup():
        logger.info("app startup: creating engine and initializing metrics")
        # create engine once on startup
        try:
            app.state.engine = _create_engine()
        except Exception:
            logger.exception("failed to create engine on startup")
            raise

        # setup prometheus metrics if available
        if _HAS_PROM:
            try:
                reg = CollectorRegistry(auto_describe=True)
                # basic metrics
                app.state.requests_counter = Counter(
                    "sqlmcp_execute_requests_total", "Total number of execute_read_only_sql calls", registry=reg
                )
                app.state.query_histogram = Histogram(
                    "sqlmcp_query_duration_seconds", "Duration of read-only queries in seconds", registry=reg
                )
                app.state.metrics_registry = reg
                logger.info("Prometheus metrics initialized")
            except Exception:
                logger.exception("Failed to initialize Prometheus metrics")
                app.state.metrics_registry = None
        else:
            logger.info("prometheus-client not available; /metrics will return 501")

    @app.on_event("shutdown")
    def _shutdown():
        logger.info("app shutdown: disposing engine and cleaning up")
        try:
            engine = getattr(app.state, "engine", None)
            if engine is not None:
                engine.dispose()
                logger.info("engine disposed")
        except Exception:
            logger.exception("Error disposing engine on shutdown")

    @app.get("/health")
    def health() -> dict:
        """
        Liveness probe. Returns 200 if the application process is running.
        """
        logger.info("health check")
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        """
        Readiness probe. Verifies the database connection by running a trivial query.
        Returns 200 if the DB is reachable, otherwise 503.
        """
        logger.info("readiness check: verifying database connectivity")
        try:
            engine = getattr(app.state, "engine", None)
            if engine is None:
                engine = create_engine_from_settings(settings)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return JSONResponse({"db": "ok"}, status_code=status.HTTP_200_OK)
        except Exception as exc:  # broad catch to convert to a controlled response
            logger.exception("readiness check failed")
            return JSONResponse({"db": "error", "reason": str(exc)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.get("/metrics")
    def metrics() -> Response:
        """
        Expose Prometheus metrics if prometheus-client is available.
        Returns 501 Not Implemented when not installed.
        """
        if not _HAS_PROM or app.state.metrics_registry is None or generate_latest is None:
            logger.debug("Metrics endpoint requested but prometheus-client not available")
            return JSONResponse({"error": "prometheus metrics not enabled"}, status_code=status.HTTP_501_NOT_IMPLEMENTED)
        try:
            data = generate_latest(app.state.metrics_registry)
            return PlainTextResponse(data, media_type=CONTENT_TYPE_LATEST)
        except Exception:
            logger.exception("Failed to generate metrics")
            return JSONResponse({"error": "failed to generate metrics"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return app


def main() -> None:
    """
    Entrypoint. By default runs the HTTP server (uvicorn). To run the MCP server
    instead, set RUN_HTTP=0 in the environment.
    """
    _configure_logging()
    run_http = os.environ.get("RUN_HTTP", "1") not in ("0", "false", "False")

    if run_http:
        try:
            import uvicorn  # type: ignore
        except Exception:
            raise RuntimeError("uvicorn is required to run the HTTP server. Install with extras.")

        settings = Settings()
        app = create_http_app(settings)
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "8080"))
        logger.info(f"starting http server on {host}:{port}")
        uvicorn.run(app, host=host, port=port)
        return

    # Fallback: build and run MCP server
    server = build_mcp_server()
    if hasattr(server, "run"):
        server.run()
    else:
        logger.info("MCP server built but `run()` not found on server object. Tools registered.")
        for t in ("list_tables", "get_table_schema", "execute_read_only_sql"):
            logger.info("Registered tool: %s", t)
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            logger.info("Server shutting down.")


if __name__ == "__main__":
    main()
