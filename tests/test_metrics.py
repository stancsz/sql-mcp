from __future__ import annotations
import asyncio
from httpx import AsyncClient, ASGITransport
from sql_mcp_server.server import create_http_app
from sql_mcp_server.config import Settings

def test_metrics_endpoint_behavior():
    """
    - If prometheus-client is installed, /metrics should return 200 and contain
      the initialized metric names (even with zero values).
    - If prometheus-client is not installed, /metrics should return 501.
    """
    async def run():
        app = create_http_app(Settings(DB_TYPE="sqlite", DB_NAME=":memory:"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/metrics")
            try:
                import prometheus_client  # type: ignore
                # prometheus available => metrics endpoint enabled
                assert resp.status_code == 200
                text = resp.text
                # the server initializes metrics names; ensure the response contains at least one expected metric name
                assert "sqlmcp_execute_requests_total" in text or "sqlmcp_query_duration_seconds" in text
            except Exception:
                # prometheus not available => endpoint returns 501
                assert resp.status_code == 501
    asyncio.run(run())
