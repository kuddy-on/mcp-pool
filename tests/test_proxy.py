from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from mcp_pool.app import create_app, lifespan
from mcp_pool.db import AccountKeyModel, async_session
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.pool import KeyPoolManager
from mcp_pool.providers.base import ProviderSignalKind
from mcp_pool.providers.context7 import Context7ProviderAdapter
from mcp_pool.providers.generic import GenericHeaderProviderAdapter


def test_generic_provider_headers() -> None:
    adapter = GenericHeaderProviderAdapter(auth_header="X-API-Key", auth_prefix="")
    headers = httpx.Headers({"content-type": "application/json", "host": "localhost"})
    out = adapter.prepare_headers("my_secret_key_123", headers)

    assert out["x-api-key"] == "my_secret_key_123"
    assert "host" not in out


def test_key_pool_manager_round_robin() -> None:
    service_cfg = ServiceConfig(
        name="test_service_rr",
        upstream_url="https://api.example.com/mcp",
        provider_type="generic",
        api_keys=["key_1", "key_2", "key_3"],
    )
    manager = KeyPoolManager("srv-uuid-rr", service_cfg)

    k1 = manager.get_current_key()
    assert k1 is not None and k1.secret_key == "key_1"

    k2 = manager.get_current_key()
    assert k2 is not None and k2.secret_key == "key_2"

    k3 = manager.get_current_key()
    assert k3 is not None and k3.secret_key == "key_3"

    k1_again = manager.get_current_key()
    assert k1_again is not None and k1_again.secret_key == "key_1"


def test_key_pool_manager_rotation() -> None:
    service_cfg = ServiceConfig(
        name="test_service",
        upstream_url="https://api.example.com/mcp",
        provider_type="generic",
        api_keys=["key_1", "key_2"],
    )
    manager = KeyPoolManager("srv-uuid-1", service_cfg)

    k1 = manager.get_current_key()
    assert k1 is not None
    assert k1.secret_key == "key_1"

    manager.mark_signal(k1.key_id, ProviderSignalKind.QUOTA_EXHAUSTED)

    k2 = manager.get_current_key()
    assert k2 is not None
    assert k2.secret_key == "key_2"

    manager.mark_signal(k2.key_id, ProviderSignalKind.QUOTA_EXHAUSTED)

    assert manager.get_current_key() is None


def test_key_pool_manager_enforces_monthly_quota() -> None:
    manager = KeyPoolManager(
        "srv-quota",
        ServiceConfig(
            name="quota-service",
            upstream_url="https://api.example.com/mcp",
            api_keys=["key_1", "key_2"],
        ),
    )
    manager.keys[0].monthly_quota = 10

    selected = manager.get_current_key({manager.keys[0].key_id: 10})

    assert selected is not None
    assert selected.secret_key == "key_2"


@pytest.mark.asyncio
async def test_context7_auth_and_rate_limit_classification() -> None:
    adapter = Context7ProviderAdapter()

    auth_signal = await adapter.classify_response(httpx.Response(401))
    rate_signal = await adapter.classify_response(httpx.Response(429, headers={"Retry-After": "5"}))

    assert auth_signal.kind == ProviderSignalKind.AUTH_INVALID
    assert rate_signal.kind == ProviderSignalKind.RATE_LIMITED
    assert rate_signal.retry_at is not None
    assert rate_signal.retry_at > datetime.now(UTC)


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

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=transport)
        assert app_module.pool_registry is not None
        service_name = f"test_service_{uuid4().hex[:6]}"
        await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://api.example.com/mcp",
                provider_type="generic",
                api_keys=["key_1", "key_2"],
            )
        )
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"proxy-test-{uuid4().hex[:6]}"
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.post(
                f"/s/{service_name}/v1/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
                json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            )
            assert res.status_code == 200
            assert res.json() == {"jsonrpc": "2.0", "result": "ok", "id": 1}

            assert app_module.pool_registry is not None
            mgr = app_module.pool_registry.get_manager(service_name)
            assert mgr is not None
            current_key = mgr.get_current_key()
            assert current_key is not None
            assert current_key.secret_key == "key_2"

            async with async_session() as session:
                result = await session.execute(
                    select(AccountKeyModel).where(AccountKeyModel.id == mgr.keys[0].key_id)
                )
                stored_key = result.scalar_one()
                assert stored_key.is_active is False
                assert stored_key.quota_exhausted is True
                assert stored_key.secret_key.startswith("enc:v1:")
                assert stored_key.secret_key != "key_1"


@pytest.mark.asyncio
async def test_context7_success_log_includes_attempt_in_failover_chain() -> None:
    app = create_app()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": {}, "id": 1})

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        service_name = f"context7_log_{uuid4().hex[:6]}"
        await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://api.context7.com/mcp",
                provider_type="context7",
                api_keys=["context7-key"],
            )
        )
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"context7-log-test-{uuid4().hex[:6]}"
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/s/{service_name}/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "query-docs", "arguments": {}},
                    "id": 1,
                },
            )

        assert response.status_code == 200
        logs = app_module.pool_registry.get_logs(
            limit=10,
            service_names={service_name},
        )
        assert len(logs) == 1
        assert logs[0].failover_chain == ["Key-1:success"]


@pytest.mark.asyncio
async def test_proxy_requires_gateway_key_on_both_routes() -> None:
    app = create_app()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": "ok", "id": 1})

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        service_name = f"auth_service_{uuid4().hex[:6]}"
        await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://api.example.com/mcp",
                api_keys=["upstream-key"],
            )
        )
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"auth-test-{uuid4().hex[:6]}"
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            payload = {"jsonrpc": "2.0", "method": "ping", "id": 1}
            named_unauthorized = await client.post(
                f"/s/{service_name}/mcp",
                json=payload,
            )
            root_unauthorized = await client.post(
                "/mcp",
                headers={"X-MCP-Service": service_name},
                json=payload,
            )
            root_authorized = await client.post(
                "/mcp",
                headers={
                    "Authorization": f"Bearer {gateway_key}",
                    "X-MCP-Service": service_name,
                },
                json=payload,
            )

        assert named_unauthorized.status_code == 401
        assert root_unauthorized.status_code == 401
        assert root_authorized.status_code == 200


@pytest.mark.asyncio
async def test_tools_call_transport_error_is_not_retried() -> None:
    app = create_app()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection lost", request=request)

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        service_name = f"unsafe_service_{uuid4().hex[:6]}"
        await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://api.example.com/mcp",
                api_keys=["key_1", "key_2"],
            )
        )
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"unsafe-test-{uuid4().hex[:6]}"
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/s/{service_name}/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "write-operation", "arguments": {}},
                    "id": 1,
                },
            )

    assert response.status_code == 502
    assert attempts == 1


@pytest.mark.asyncio
async def test_read_only_request_fails_over_on_5xx() -> None:
    app = create_app()
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": {}, "id": 1})

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        service_name = f"safe_service_{uuid4().hex[:6]}"
        await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://api.example.com/mcp",
                api_keys=["key_1", "key_2"],
            )
        )
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"safe-test-{uuid4().hex[:6]}"
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/s/{service_name}/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
                json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            )

    assert response.status_code == 200
    assert attempts == 2
