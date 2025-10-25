from __future__ import annotations
import asyncio
from httpx import AsyncClient, ASGITransport
from sql_mcp_server.server import create_http_app
from sql_mcp_server.config import Settings

def test_health_endpoint():
    """/health should return 200 with basic status payload using AsyncClient run via asyncio."""
    async def run():
        app = create_http_app(Settings(DB_TYPE="sqlite", DB_NAME=":memory:"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
    asyncio.run(run())

def test_ready_endpoint_sqlite_in_memory():
    """/ready should return 200 when DB (in-memory sqlite) is reachable using AsyncClient run via asyncio."""
    async def run():
        app = create_http_app(Settings(DB_TYPE="sqlite", DB_NAME=":memory:"))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/ready")
            assert resp.status_code == 200
            assert resp.json() == {"db": "ok"}
    asyncio.run(run())
