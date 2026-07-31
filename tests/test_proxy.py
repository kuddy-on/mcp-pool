import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from mcp_pool.app import AttemptResources, create_app, lifespan
from mcp_pool.db import AccountKeyModel, RequestLogModel, async_session
from mcp_pool.domain.admin import RequestLogItem
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.pool import KeyPoolManager, KeyPoolRegistry
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


def test_weighted_round_robin_honors_configured_weights() -> None:
    manager = KeyPoolManager(
        "weighted-service-id",
        ServiceConfig(
            name="weighted-service",
            upstream_url="https://api.example.com/mcp",
            api_keys=["key_1", "key_2"],
        ),
    )
    manager.keys[0].weight = 1
    manager.keys[1].weight = 3

    selections = [manager.get_current_key() for _ in range(400)]
    counts = {
        key.secret_key: sum(selected is key for selected in selections) for key in manager.keys
    }

    assert counts == {"key_1": 100, "key_2": 300}


@pytest.mark.asyncio
async def test_quota_reservation_prevents_concurrent_oversubscription() -> None:
    registry = KeyPoolRegistry([])
    manager = KeyPoolManager(
        "quota-reservation-id",
        ServiceConfig(
            name="quota-reservation",
            upstream_url="https://api.example.com/mcp",
            api_keys=["key_1"],
        ),
    )
    manager.keys[0].monthly_quota = 1

    first, second = await asyncio.gather(
        registry.reserve_key(manager, set()),
        registry.reserve_key(manager, set()),
    )

    assert (first is None) != (second is None)
    selected = first or second
    assert selected is not None
    await registry.release_key_reservation(selected.key_id)


@pytest.mark.asyncio
async def test_committed_usage_prevents_stale_quota_reservation() -> None:
    registry = KeyPoolRegistry([])
    manager = KeyPoolManager(
        "quota-commit-id",
        ServiceConfig(
            name=f"quota-commit-{uuid4().hex}",
            upstream_url="https://api.example.com/mcp",
            api_keys=["key_1"],
        ),
    )
    key = manager.keys[0]
    key.monthly_quota = 1

    reserved = await registry.reserve_key(manager, set())
    assert reserved is key
    await registry.add_log(
        RequestLogItem(
            id=str(uuid4()),
            service_name=manager.service_name,
            timestamp=datetime.now(UTC),
            method="POST",
            path="mcp",
            mcp_method="tools/call",
            key_id=key.key_id,
            key_name=key.name,
            status_code=200,
            signal_kind="success",
            duration_ms=1,
        )
    )
    await registry.release_key_reservation(key.key_id)

    assert await registry.reserve_key(manager, set()) is None


@pytest.mark.asyncio
async def test_attempt_cancellation_closes_response_and_releases_reservation() -> None:
    registry = KeyPoolRegistry([])
    manager = KeyPoolManager(
        "cancel-id",
        ServiceConfig(
            name=f"cancel-{uuid4().hex}",
            upstream_url="https://api.example.com/mcp",
            api_keys=["key_1"],
        ),
    )
    key = await registry.reserve_key(manager, set())
    assert key is not None
    response = httpx.Response(200, content=b"pending")
    started = asyncio.Event()

    async def cancelled_attempt() -> None:
        async with AttemptResources(registry, key.key_id) as resources:
            resources.own_response(response)
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(cancelled_attempt())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert response.is_closed
    assert registry._quota_reservations == {}


@pytest.mark.asyncio
async def test_attempt_releases_reservation_when_response_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = KeyPoolRegistry([])
    manager = KeyPoolManager(
        "close-failure-id",
        ServiceConfig(
            name=f"close-failure-{uuid4().hex}",
            upstream_url="https://api.example.com/mcp",
            api_keys=["key_1"],
        ),
    )
    key = await registry.reserve_key(manager, set())
    assert key is not None
    response = httpx.Response(200, content=b"pending")

    async def failing_close() -> None:
        raise RuntimeError("transport close failed")

    monkeypatch.setattr(response, "aclose", failing_close)
    with pytest.raises(RuntimeError, match="transport close failed"):
        async with AttemptResources(registry, key.key_id) as resources:
            resources.own_response(response)

    assert registry._quota_reservations == {}


@pytest.mark.asyncio
async def test_retention_preserves_current_month_quota_across_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = KeyPoolRegistry([])
    monkeypatch.setattr(registry._settings, "request_log_retention_days", 1)
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    key_id = f"retained-{uuid4().hex}"
    current_id = str(uuid4())
    expired_id = str(uuid4())
    async with async_session() as session:
        session.add_all(
            [
                RequestLogModel(
                    id=current_id,
                    service_name="retention-test",
                    timestamp=month_start,
                    method="POST",
                    path="mcp",
                    key_id=key_id,
                    key_name="retained-key",
                    status_code=200,
                    signal_kind="success",
                    duration_ms=1,
                ),
                RequestLogModel(
                    id=expired_id,
                    service_name="retention-test",
                    timestamp=month_start - timedelta(days=2),
                    method="POST",
                    path="mcp",
                    key_id=key_id,
                    key_name="expired-key",
                    status_code=200,
                    signal_kind="success",
                    duration_ms=1,
                ),
            ]
        )
        await session.commit()

    assert await registry.prune_request_logs() >= 1

    async with async_session() as session:
        remaining = await session.execute(
            select(RequestLogModel.id).where(RequestLogModel.id.in_([current_id, expired_id]))
        )
    assert set(remaining.scalars()) == {current_id}

    reloaded = KeyPoolRegistry([])
    usage = await reloaded.get_monthly_usage()
    assert usage[key_id] == 1
    manager = KeyPoolManager(
        "retention-quota-id",
        ServiceConfig(
            name=f"retention-quota-{uuid4().hex}",
            upstream_url="https://api.example.com/mcp",
            api_keys=["key_1"],
        ),
    )
    manager.keys[0].key_id = key_id
    manager.keys[0].monthly_quota = 1
    assert await reloaded.reserve_key(manager, set()) is None


@pytest.mark.asyncio
async def test_session_affinity_uses_lru_eviction(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = KeyPoolRegistry([])
    monkeypatch.setattr(registry._settings, "session_affinity_max_entries", 2)

    await registry.bind_session("session-1", "service", "key-1")
    await registry.bind_session("session-2", "service", "key-2")
    assert await registry.get_session_key_id("session-1", "service") == "key-1"
    await registry.bind_session("session-3", "service", "key-3")

    assert await registry.get_session_key_id("session-2", "service") is None
    assert await registry.get_session_key_id("session-1", "service") == "key-1"
    assert await registry.get_session_key_id("session-3", "service") == "key-3"


@pytest.mark.asyncio
async def test_session_affinity_keeps_followup_on_original_key() -> None:
    app = create_app()
    seen_credentials: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_credentials.append(request.headers["authorization"])
        headers = {"Mcp-Session-Id": "session-123"} if len(seen_credentials) == 1 else {}
        return httpx.Response(
            200,
            headers=headers,
            json={"jsonrpc": "2.0", "result": {}, "id": 1},
        )

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        service_name = f"affinity-{uuid4().hex[:8]}"
        await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://api.example.com/mcp",
                api_keys=["key_1", "key_2"],
            )
        )
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"affinity-client-{uuid4().hex[:8]}"
        )
        auth = {"Authorization": f"Bearer {gateway_key}"}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            initialized = await client.post(
                f"/s/{service_name}/mcp",
                headers=auth,
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            )
            followed_up = await client.post(
                f"/s/{service_name}/mcp",
                headers={**auth, "Mcp-Session-Id": "session-123"},
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            )

    assert initialized.status_code == 200
    assert followed_up.status_code == 200
    assert seen_credentials == ["Bearer key_1", "Bearer key_1"]


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
