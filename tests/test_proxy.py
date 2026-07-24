import httpx
import pytest

from mcp_pool.app import create_app, lifespan
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.pool import KeyPoolManager
from mcp_pool.providers.base import ProviderSignalKind
from mcp_pool.providers.generic import GenericHeaderProviderAdapter


def test_generic_provider_headers() -> None:
    adapter = GenericHeaderProviderAdapter(auth_header="X-API-Key", auth_prefix="")
    headers = httpx.Headers({"content-type": "application/json", "host": "localhost"})
    out = adapter.prepare_headers("my_secret_key_123", headers)

    assert out["x-api-key"] == "my_secret_key_123"
    assert "host" not in out


def test_key_pool_manager_rotation() -> None:
    service_cfg = ServiceConfig(
        name="test_service",
        upstream_url="https://api.example.com/mcp",
        provider_type="generic",
        api_keys=["key_1", "key_2"],
    )
    manager = KeyPoolManager(service_cfg)

    k1 = manager.get_current_key()
    assert k1 is not None
    assert k1.secret_key == "key_1"

    manager.mark_signal(k1.key_id, ProviderSignalKind.QUOTA_EXHAUSTED)

    k2 = manager.get_current_key()
    assert k2 is not None
    assert k2.secret_key == "key_2"

    manager.mark_signal(k2.key_id, ProviderSignalKind.QUOTA_EXHAUSTED)

    assert manager.get_current_key() is None


@pytest.mark.asyncio
async def test_proxy_end_to_end_generic_failover() -> None:
    app = create_app()

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if "key_1" in auth:
            return httpx.Response(401, json={"error": "Quota exceeded"})
        elif "key_2" in auth:
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "ok", "id": 1})
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)

    async with lifespan(app):
        import mcp_pool.app as app_module

        app_module.http_client = httpx.AsyncClient(transport=transport)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.post("/v1/mcp", json={"jsonrpc": "2.0", "method": "ping", "id": 1})
            assert res.status_code == 200
            assert res.json() == {"jsonrpc": "2.0", "result": "ok", "id": 1}

            assert app_module.pool_registry is not None
            mgr = app_module.pool_registry.get_manager()
            assert mgr is not None
            current_key = mgr.get_current_key()
            assert current_key is not None
            assert current_key.secret_key == "key_2"
