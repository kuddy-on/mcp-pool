import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from mcp_pool import db
from mcp_pool.app import create_app, lifespan
from mcp_pool.db import AccountKeyModel, async_session
from mcp_pool.domain.admin import RequestLogItem
from mcp_pool.domain.quota import ProviderQuotaError, ProviderQuotaSnapshot
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.pool import AccountKey, KeyPoolManager, KeyPoolRegistry
from mcp_pool.providers.context7 import (
    CONTEXT7_QUOTA_URL,
    Context7ProviderAdapter,
    parse_context7_quota_response,
)
from mcp_pool.providers.generic import GenericHeaderProviderAdapter
from mcp_pool.quota import get_provider_quota_status, refresh_provider_quota_status


def test_parse_context7_quota_success() -> None:
    checked_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    result = parse_context7_quota_response(
        httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "1000",
                "RateLimit-Remaining": "749",
                "RateLimit-Reset": "1785542400",
            },
        ),
        checked_at=checked_at,
    )

    assert isinstance(result, ProviderQuotaSnapshot)
    assert result.status == "ok"
    assert result.used == 251
    assert result.limit == 1000
    assert result.remaining == 749
    assert result.reset_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert result.checked_at == checked_at


def test_quota_snapshot_is_stale_after_reset_even_when_recent() -> None:
    now = datetime(2026, 8, 1, 0, 1, tzinfo=UTC)
    key = AccountKey(
        key_id="recent-but-reset",
        name="Recent",
        secret_key="not-used",
        provider_quota_snapshot=ProviderQuotaSnapshot(
            status="exhausted",
            used=1000,
            limit=1000,
            remaining=0,
            reset_at=datetime(2026, 8, 1, tzinfo=UTC),
            checked_at=datetime(2026, 7, 31, 23, 59, tzinfo=UTC),
        ).model_dump_json(),
    )
    manager = KeyPoolManager(
        "context7-service",
        ServiceConfig(
            name="context7",
            upstream_url="https://mcp.context7.com/mcp",
            provider_type="context7",
        ),
    )
    manager.keys = [key]

    response = get_provider_quota_status(manager, now=now)

    assert response.keys[0].stale is True


def test_all_exhausted_keys_have_exhausted_service_status() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    manager = KeyPoolManager(
        "context7-exhausted",
        ServiceConfig(
            name="context7-exhausted",
            upstream_url="https://mcp.context7.com/mcp",
            provider_type="context7",
        ),
    )
    manager.keys = [
        AccountKey(
            key_id=f"exhausted-{index}",
            name=f"Exhausted {index}",
            secret_key=f"ctx7-{index}",
            provider_quota_snapshot=ProviderQuotaSnapshot(
                status="exhausted",
                used=100,
                limit=100,
                remaining=0,
                reset_at=now + timedelta(days=1),
                checked_at=now,
            ).model_dump_json(),
        )
        for index in range(2)
    ]

    response = get_provider_quota_status(manager, now=now)

    assert response.status == "exhausted"


@pytest.mark.parametrize(
    ("response", "status", "error_code"),
    [
        (httpx.Response(200), "error", "missing_rate_limit_headers"),
        (httpx.Response(401), "auth_invalid", "auth_invalid"),
        (
            httpx.Response(
                200,
                headers={
                    "RateLimit-Limit": "not-a-number",
                    "RateLimit-Remaining": "5",
                    "RateLimit-Reset": "1785542400",
                },
            ),
            "error",
            "invalid_rate_limit_headers",
        ),
        (
            httpx.Response(
                200,
                headers={
                    "RateLimit-Limit": "4",
                    "RateLimit-Remaining": "5",
                    "RateLimit-Reset": "1785542400",
                },
            ),
            "error",
            "invalid_rate_limit_headers",
        ),
    ],
)
def test_parse_context7_quota_errors(
    response: httpx.Response,
    status: str,
    error_code: str,
) -> None:
    result = parse_context7_quota_response(response)

    assert isinstance(result, ProviderQuotaError)
    assert result.status == status
    assert result.error_code == error_code


def test_parse_context7_quota_429() -> None:
    result = parse_context7_quota_response(
        httpx.Response(
            429,
            headers={
                "RateLimit-Limit": "200",
                "RateLimit-Remaining": "0",
                "RateLimit-Reset": "1785542400",
                "Retry-After": "300",
            },
        )
    )

    assert isinstance(result, ProviderQuotaSnapshot)
    assert result.status == "exhausted"
    assert result.used == 200
    assert result.remaining == 0
    assert result.error_code == "rate_limited"


def test_passive_capture_updates_only_actionable_context7_responses() -> None:
    now = datetime.now(UTC)
    reset_epoch = int((now + timedelta(days=1)).timestamp())
    reset_at = datetime.fromtimestamp(reset_epoch, tz=UTC)
    manager = KeyPoolManager(
        "context7-passive",
        ServiceConfig(
            name="context7-passive",
            upstream_url="https://mcp.context7.com/mcp",
            provider_type="context7",
        ),
    )
    key = AccountKey(
        key_id="passive-key",
        name="Passive",
        secret_key="ctx7-test",
        provider_quota_snapshot=ProviderQuotaSnapshot(
            status="ok",
            used=10,
            limit=100,
            remaining=90,
            reset_at=reset_at,
            checked_at=now - timedelta(minutes=2),
        ).model_dump_json(),
        provider_quota_error=ProviderQuotaError(
            status="error",
            checked_at=now - timedelta(minutes=1),
            error_code="network_error",
        ).model_dump_json(),
    )

    adapter = manager.provider_adapter
    assert isinstance(adapter, Context7ProviderAdapter)
    adapter.capture_quota_response(
        key,
        httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "100",
                "RateLimit-Remaining": "87",
                "RateLimit-Reset": str(reset_epoch),
            },
        ),
        expected_credential="ctx7-test",
    )

    assert key.provider_quota_snapshot is not None
    snapshot = ProviderQuotaSnapshot.model_validate_json(key.provider_quota_snapshot)
    assert snapshot.used == 13
    assert snapshot.remaining == 87
    assert key.provider_quota_error is None

    saved_snapshot = key.provider_quota_snapshot
    adapter.capture_quota_response(
        key,
        httpx.Response(200),
        expected_credential="ctx7-test",
    )
    assert key.provider_quota_snapshot == saved_snapshot
    assert key.provider_quota_error is None

    adapter.capture_quota_response(
        key,
        httpx.Response(401),
        expected_credential="ctx7-test",
    )
    assert key.provider_quota_snapshot == saved_snapshot
    assert key.provider_quota_error is not None
    error = ProviderQuotaError.model_validate_json(key.provider_quota_error)
    assert error.status == "auth_invalid"

    adapter.capture_quota_response(
        key,
        httpx.Response(
            429,
            headers={
                "RateLimit-Limit": "100",
                "RateLimit-Remaining": "0",
                "RateLimit-Reset": str(reset_epoch),
            },
        ),
        expected_credential="ctx7-test",
    )
    assert key.provider_quota_snapshot is not None
    exhausted = ProviderQuotaSnapshot.model_validate_json(key.provider_quota_snapshot)
    assert exhausted.status == "exhausted"
    assert exhausted.remaining == 0
    assert key.provider_quota_error is None

    # An older overlapping response must not roll a same-period counter backwards.
    adapter.capture_quota_response(
        key,
        httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "100",
                "RateLimit-Remaining": "50",
                "RateLimit-Reset": str(reset_epoch),
            },
        ),
        expected_credential="ctx7-test",
    )
    assert key.provider_quota_snapshot is not None
    not_rolled_back = ProviderQuotaSnapshot.model_validate_json(key.provider_quota_snapshot)
    assert not_rolled_back.remaining == 0

    key.secret_key = "ctx7-replacement"
    saved_snapshot = key.provider_quota_snapshot
    saved_error = key.provider_quota_error
    adapter.capture_quota_response(
        key,
        httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "100",
                "RateLimit-Remaining": "50",
                "RateLimit-Reset": str(reset_epoch),
            },
        ),
        expected_credential="ctx7-test",
    )
    assert key.provider_quota_snapshot == saved_snapshot
    assert key.provider_quota_error == saved_error


def test_success_without_headers_adds_one_to_an_existing_official_snapshot() -> None:
    checked_at = datetime.now(UTC)
    key = AccountKey(
        key_id="estimated-key",
        name="Estimated",
        secret_key="ctx7-test",
        provider_quota_snapshot=ProviderQuotaSnapshot(
            status="ok",
            used=10,
            limit=100,
            remaining=90,
            reset_at=checked_at + timedelta(days=1),
            checked_at=checked_at,
        ).model_dump_json(),
    )
    adapter = Context7ProviderAdapter()

    updated = adapter.capture_quota_response(
        key,
        httpx.Response(200),
        expected_credential="ctx7-test",
        estimate_success_without_headers=True,
    )

    assert updated is True
    assert key.provider_quota_snapshot is not None
    snapshot = ProviderQuotaSnapshot.model_validate_json(key.provider_quota_snapshot)
    assert snapshot.used == 10
    assert snapshot.remaining == 90
    assert len(snapshot.local_usage_events) == 1
    assert snapshot.local_usage_events[0] >= checked_at
    assert snapshot.checked_at == checked_at

    manager = KeyPoolManager(
        "estimated-service",
        ServiceConfig(
            name="estimated-service",
            upstream_url="https://mcp.context7.com/mcp",
            provider_type="context7",
        ),
    )
    manager.keys = [key]
    response = get_provider_quota_status(manager, now=checked_at + timedelta(minutes=1))
    assert response.keys[0].used == 11
    assert response.keys[0].remaining == 89
    assert response.keys[0].estimated is True
    assert response.keys[0].last_success_at == checked_at


def test_local_quota_increment_requires_a_current_snapshot_and_current_credential() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    adapter = Context7ProviderAdapter()
    missing = AccountKey(
        key_id="missing-snapshot",
        name="Missing",
        secret_key="ctx7-test",
    )
    expired = AccountKey(
        key_id="expired-snapshot",
        name="Expired",
        secret_key="ctx7-test",
        provider_quota_snapshot=ProviderQuotaSnapshot(
            status="ok",
            used=20,
            limit=100,
            remaining=80,
            reset_at=now,
            checked_at=now - timedelta(hours=1),
        ).model_dump_json(),
    )

    assert (
        adapter.increment_quota_usage(
            missing,
            expected_credential="ctx7-test",
            observed_at=now,
        )
        is False
    )
    assert (
        adapter.increment_quota_usage(
            expired,
            expected_credential="ctx7-test",
            observed_at=now,
        )
        is False
    )
    assert (
        adapter.increment_quota_usage(
            expired,
            expected_credential="old-credential",
            observed_at=now - timedelta(seconds=1),
        )
        is False
    )
    assert expired.provider_quota_snapshot is not None
    snapshot = ProviderQuotaSnapshot.model_validate_json(expired.provider_quota_snapshot)
    assert snapshot.local_usage_events == []


def test_official_quota_result_absorbs_local_usage_without_double_counting() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    key = AccountKey(
        key_id="calibrated-key",
        name="Calibrated",
        secret_key="ctx7-test",
        provider_quota_snapshot=ProviderQuotaSnapshot(
            status="ok",
            used=10,
            limit=100,
            remaining=90,
            reset_at=now + timedelta(days=1),
            checked_at=now,
            local_usage_events=[now + timedelta(seconds=30)],
        ).model_dump_json(),
    )
    official = ProviderQuotaSnapshot(
        status="ok",
        used=12,
        limit=100,
        remaining=88,
        reset_at=now + timedelta(days=1),
        checked_at=now + timedelta(minutes=1),
    )

    applied = Context7ProviderAdapter().apply_quota_result(
        key,
        official,
        expected_credential="ctx7-test",
    )

    assert applied is True
    assert key.provider_quota_snapshot is not None
    calibrated = ProviderQuotaSnapshot.model_validate_json(key.provider_quota_snapshot)
    assert calibrated.used == 12
    assert calibrated.remaining == 88
    assert calibrated.local_usage_events == []


def test_older_header_response_preserves_usage_observed_after_it() -> None:
    baseline_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    official_response_at = baseline_at + timedelta(minutes=1)
    later_business_at = baseline_at + timedelta(minutes=2)
    latest_business_at = baseline_at + timedelta(minutes=3)
    reset_at = baseline_at + timedelta(days=1)
    key = AccountKey(
        key_id="out-of-order-key",
        name="Out of order",
        secret_key="ctx7-test",
        provider_quota_snapshot=ProviderQuotaSnapshot(
            status="ok",
            used=10,
            limit=100,
            remaining=90,
            reset_at=reset_at,
            checked_at=baseline_at,
            local_usage_events=[later_business_at, latest_business_at],
        ).model_dump_json(),
    )

    applied = Context7ProviderAdapter().capture_quota_response(
        key,
        httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "100",
                "RateLimit-Remaining": "89",
                "RateLimit-Reset": str(int(reset_at.timestamp())),
            },
        ),
        expected_credential="ctx7-test",
        observed_at=official_response_at,
    )

    assert applied is True
    assert key.provider_quota_snapshot is not None
    snapshot = ProviderQuotaSnapshot.model_validate_json(key.provider_quota_snapshot)
    assert snapshot.used == 11
    assert snapshot.remaining == 89
    assert snapshot.local_usage_events == [later_business_at, latest_business_at]

    manager = KeyPoolManager(
        "out-of-order-service",
        ServiceConfig(
            name="out-of-order-service",
            upstream_url="https://mcp.context7.com/mcp",
            provider_type="context7",
        ),
    )
    manager.keys = [key]
    response = get_provider_quota_status(manager, now=latest_business_at)
    assert response.keys[0].used == 13
    assert response.keys[0].remaining == 87


def test_explicit_official_calibration_can_correct_a_local_overestimate() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    key = AccountKey(
        key_id="corrected-key",
        name="Corrected",
        secret_key="ctx7-test",
        provider_quota_snapshot=ProviderQuotaSnapshot(
            status="ok",
            used=10,
            limit=100,
            remaining=90,
            reset_at=now + timedelta(days=1),
            checked_at=now,
            local_usage_events=[
                now + timedelta(seconds=10),
                now + timedelta(seconds=20),
            ],
        ).model_dump_json(),
    )
    official = ProviderQuotaSnapshot(
        status="ok",
        used=11,
        limit=100,
        remaining=89,
        reset_at=now + timedelta(days=1),
        checked_at=now + timedelta(minutes=1),
    )
    adapter = Context7ProviderAdapter()

    assert (
        adapter.apply_quota_result(
            key,
            official,
            expected_credential="ctx7-test",
        )
        is False
    )
    assert (
        adapter.apply_quota_result(
            key,
            official,
            expected_credential="ctx7-test",
            reconcile_local_usage=True,
        )
        is True
    )
    assert key.provider_quota_snapshot is not None
    corrected = ProviderQuotaSnapshot.model_validate_json(key.provider_quota_snapshot)
    assert corrected.used == 11
    assert corrected.remaining == 89
    assert corrected.local_usage_events == []


def test_local_quota_increment_stops_at_zero_remaining() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    key = AccountKey(
        key_id="last-request-key",
        name="Last request",
        secret_key="ctx7-test",
        provider_quota_snapshot=ProviderQuotaSnapshot(
            status="ok",
            used=99,
            limit=100,
            remaining=1,
            reset_at=now + timedelta(days=1),
            checked_at=now,
        ).model_dump_json(),
    )
    adapter = Context7ProviderAdapter()

    assert (
        adapter.increment_quota_usage(
            key,
            expected_credential="ctx7-test",
            observed_at=now + timedelta(minutes=1),
        )
        is True
    )
    assert (
        adapter.increment_quota_usage(
            key,
            expected_credential="ctx7-test",
            observed_at=now + timedelta(minutes=2),
        )
        is False
    )

    manager = KeyPoolManager(
        "last-request-service",
        ServiceConfig(
            name="last-request-service",
            upstream_url="https://mcp.context7.com/mcp",
            provider_type="context7",
        ),
    )
    manager.keys = [key]
    response = get_provider_quota_status(manager, now=now + timedelta(minutes=2))
    assert response.keys[0].status == "exhausted"
    assert response.keys[0].used == 100
    assert response.keys[0].remaining == 0


@pytest.mark.asyncio
async def test_context7_quota_fetch_uses_fixed_head_endpoint_and_bearer_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        assert str(request.url) == CONTEXT7_QUOTA_URL
        assert request.headers["authorization"] == "Bearer ctx7-test-key"
        return httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "500",
                "RateLimit-Remaining": "498",
                "RateLimit-Reset": "1785542400",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Context7ProviderAdapter().fetch_quota_status("ctx7-test-key", client)

    assert isinstance(result, ProviderQuotaSnapshot)
    # This HEAD request consumed the second request, so used is 500 - 498.
    assert result.used == 2


@pytest.mark.asyncio
async def test_proxy_passively_persists_context7_quota_from_the_same_request() -> None:
    app = create_app()
    service_name = f"passive-proxy-{uuid4().hex[:8]}"
    upstream_calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        return httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "1000",
                "RateLimit-Remaining": "876",
                "RateLimit-Reset": "1785542400",
            },
            json={"jsonrpc": "2.0", "result": "ok", "id": 1},
        )

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        manager = await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://mcp.context7.com/mcp",
                provider_type="context7",
                api_keys=["ctx7-passive-key"],
            )
        )
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"passive-proxy-{uuid4().hex[:8]}"
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
        assert upstream_calls == 1
        account_key = manager.keys[0]
        assert account_key.provider_quota_snapshot is not None
        snapshot = ProviderQuotaSnapshot.model_validate_json(account_key.provider_quota_snapshot)
        assert snapshot.used == 124

        async with async_session() as session:
            stored = await session.execute(
                select(AccountKeyModel).where(AccountKeyModel.id == account_key.key_id)
            )
            stored_key = stored.scalar_one()
            assert stored_key.provider_quota_snapshot == account_key.provider_quota_snapshot
            assert stored_key.provider_quota_error is None


@pytest.mark.asyncio
async def test_proxy_estimates_success_without_headers_and_ignores_probe_requests() -> None:
    app = create_app()
    service_name = f"estimated-proxy-{uuid4().hex[:8]}"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "result": "ok", "id": 1},
        )

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        manager = await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://mcp.context7.com/mcp",
                provider_type="context7",
                api_keys=["ctx7-estimated-key"],
            )
        )
        account_key = manager.keys[0]
        checked_at = datetime.now(UTC)
        account_key.provider_quota_snapshot = ProviderQuotaSnapshot(
            status="ok",
            used=20,
            limit=100,
            remaining=80,
            reset_at=checked_at + timedelta(days=1),
            checked_at=checked_at,
        ).model_dump_json()
        await app_module.pool_registry.update_provider_quota_states_in_db([account_key])
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"estimated-proxy-{uuid4().hex[:8]}"
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            probe = await client.post(
                f"/s/{service_name}/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
                json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            )
            notification = await client.post(
                f"/s/{service_name}/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            session_close = await client.request(
                "DELETE",
                f"/s/{service_name}/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
            )
            business = await client.post(
                f"/s/{service_name}/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "query-docs", "arguments": {}},
                    "id": 2,
                },
            )

        assert probe.status_code == 200
        assert notification.status_code == 200
        assert session_close.status_code == 200
        assert business.status_code == 200
        assert account_key.provider_quota_snapshot is not None
        snapshot = ProviderQuotaSnapshot.model_validate_json(account_key.provider_quota_snapshot)
        assert len(snapshot.local_usage_events) == 1
        monthly_usage = await app_module.pool_registry.get_monthly_usage()
        assert monthly_usage[account_key.key_id] == 1
        quota = get_provider_quota_status(manager)
        assert quota.keys[0].used == 21
        assert quota.keys[0].remaining == 79
        assert quota.keys[0].estimated is True

        async with async_session() as session:
            stored = await session.execute(
                select(AccountKeyModel).where(AccountKeyModel.id == account_key.key_id)
            )
            stored_key = stored.scalar_one()
            assert stored_key.provider_quota_snapshot is not None
            stored_snapshot = ProviderQuotaSnapshot.model_validate_json(
                stored_key.provider_quota_snapshot
            )
            assert len(stored_snapshot.local_usage_events) == 1


@pytest.mark.asyncio
async def test_concurrent_proxy_successes_persist_every_local_quota_increment() -> None:
    app = create_app()
    service_name = f"concurrent-estimate-{uuid4().hex[:8]}"
    request_count = 8

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "result": "ok", "id": 1},
        )

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        manager = await app_module.pool_registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://mcp.context7.com/mcp",
                provider_type="context7",
                api_keys=["ctx7-concurrent-key"],
            )
        )
        account_key = manager.keys[0]
        checked_at = datetime.now(UTC)
        account_key.provider_quota_snapshot = ProviderQuotaSnapshot(
            status="ok",
            used=100,
            limit=1000,
            remaining=900,
            reset_at=checked_at + timedelta(days=1),
            checked_at=checked_at,
        ).model_dump_json()
        await app_module.pool_registry.update_provider_quota_states_in_db([account_key])
        _, gateway_key = await app_module.pool_registry.create_client_api_key(
            f"concurrent-estimate-{uuid4().hex[:8]}"
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            responses = await asyncio.gather(
                *(
                    client.post(
                        f"/s/{service_name}/mcp",
                        headers={"Authorization": f"Bearer {gateway_key}"},
                        json={
                            "jsonrpc": "2.0",
                            "method": "tools/call",
                            "params": {"name": "query-docs", "arguments": {"i": index}},
                            "id": index,
                        },
                    )
                    for index in range(request_count)
                )
            )

        assert all(response.status_code == 200 for response in responses)
        assert account_key.provider_quota_snapshot is not None
        snapshot = ProviderQuotaSnapshot.model_validate_json(account_key.provider_quota_snapshot)
        assert len(snapshot.local_usage_events) == request_count
        quota = get_provider_quota_status(manager)
        assert quota.keys[0].used == 100 + request_count
        assert quota.keys[0].remaining == 900 - request_count

        async with async_session() as session:
            stored = await session.execute(
                select(AccountKeyModel).where(AccountKeyModel.id == account_key.key_id)
            )
            stored_key = stored.scalar_one()
            assert stored_key.provider_quota_snapshot is not None
            stored_snapshot = ProviderQuotaSnapshot.model_validate_json(
                stored_key.provider_quota_snapshot
            )
            assert len(stored_snapshot.local_usage_events) == request_count


@pytest.mark.asyncio
async def test_business_success_after_official_observation_survives_refresh_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    service_name = f"refresh-race-{uuid4().hex[:8]}"
    official_response_ready = asyncio.Event()
    allow_refresh_to_apply = asyncio.Event()
    official_checked_at: datetime | None = None
    reset_at = datetime.now(UTC) + timedelta(days=1)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "result": "ok", "id": 1},
        )

    async def delayed_official_fetch(
        _adapter: Context7ProviderAdapter,
        _credential: str,
        _client: httpx.AsyncClient,
    ) -> ProviderQuotaSnapshot:
        nonlocal official_checked_at
        official_checked_at = datetime.now(UTC)
        official_response_ready.set()
        await allow_refresh_to_apply.wait()
        return ProviderQuotaSnapshot(
            status="ok",
            used=11,
            limit=100,
            remaining=89,
            reset_at=reset_at,
            checked_at=official_checked_at,
        )

    monkeypatch.setattr(
        Context7ProviderAdapter,
        "fetch_quota_status",
        delayed_official_fetch,
    )

    async with lifespan(app):
        import mcp_pool.app as app_module

        assert app_module.http_client is not None
        await app_module.http_client.aclose()
        app_module.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert app_module.pool_registry is not None
        registry = app_module.pool_registry
        manager = await registry.add_service(
            ServiceConfig(
                name=service_name,
                upstream_url="https://mcp.context7.com/mcp",
                provider_type="context7",
                api_keys=["ctx7-refresh-race-key"],
            )
        )
        account_key = manager.keys[0]
        baseline_checked_at = datetime.now(UTC) - timedelta(minutes=1)
        account_key.provider_quota_snapshot = ProviderQuotaSnapshot(
            status="ok",
            used=10,
            limit=100,
            remaining=90,
            reset_at=reset_at,
            checked_at=baseline_checked_at,
        ).model_dump_json()
        await registry.update_provider_quota_states_in_db([account_key])
        _, gateway_key = await registry.create_client_api_key(f"refresh-race-{uuid4().hex[:8]}")

        refresh_task = asyncio.create_task(
            refresh_provider_quota_status(
                manager,
                registry,
                key_id=account_key.key_id,
            )
        )
        await asyncio.wait_for(official_response_ready.wait(), timeout=1)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            business = await client.post(
                f"/s/{service_name}/mcp",
                headers={"Authorization": f"Bearer {gateway_key}"},
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": "query-docs", "arguments": {}},
                    "id": 1,
                },
            )
        assert business.status_code == 200

        allow_refresh_to_apply.set()
        refreshed = await asyncio.wait_for(refresh_task, timeout=1)
        refreshed_key = refreshed.keys[0]
        assert refreshed_key.used == 12
        assert refreshed_key.remaining == 88
        assert refreshed_key.estimated is True
        monthly_usage = await registry.get_monthly_usage()
        assert monthly_usage[account_key.key_id] == 1
        assert account_key.used_offset == 11
        assert account_key.to_response(monthly_usage).used_this_month == 12

        assert account_key.provider_quota_snapshot is not None
        snapshot = ProviderQuotaSnapshot.model_validate_json(account_key.provider_quota_snapshot)
        assert len(snapshot.local_usage_events) == 1
        assert official_checked_at is not None
        assert snapshot.local_usage_events[0] > official_checked_at

        async with async_session() as session:
            stored = await session.execute(
                select(AccountKeyModel).where(AccountKeyModel.id == account_key.key_id)
            )
            stored_key = stored.scalar_one()
            assert stored_key.provider_quota_snapshot is not None
            stored_snapshot = ProviderQuotaSnapshot.model_validate_json(
                stored_key.provider_quota_snapshot
            )
            assert len(stored_snapshot.local_usage_events) == 1


async def _login_admin(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.mark.asyncio
async def test_admin_key_test_passively_persists_context7_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    service_name = f"passive-key-test-{uuid4().hex[:8]}"
    upstream_calls = 0

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            return httpx.Response(
                200,
                headers={
                    "RateLimit-Limit": "500",
                    "RateLimit-Remaining": "444",
                    "RateLimit-Reset": "1785542400",
                },
                json={"jsonrpc": "2.0", "result": {}, "id": 1},
            )

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        headers = await _login_admin(client)
        created = await client.post(
            "/api/admin/services",
            headers=headers,
            json={
                "name": service_name,
                "upstream_url": "https://mcp.context7.com/mcp",
                "provider_type": "context7",
                "api_keys": ["ctx7-passive-test-key"],
            },
        )
        assert created.status_code == 200
        service_id = str(created.json()["id"])
        key_id = str(created.json()["keys"][0]["id"])

        monkeypatch.setattr("mcp_pool.admin_routes.httpx.AsyncClient", FakeAsyncClient)
        tested = await client.post(
            f"/api/admin/services/{service_id}/keys/{key_id}/test",
            headers=headers,
        )

        assert tested.status_code == 200
        assert tested.json()["success"] is True
        assert upstream_calls == 1

        manager = db_value_registry().get_manager(service_id)
        assert manager is not None
        account_key = manager.keys[0]
        assert account_key.provider_quota_snapshot is not None
        snapshot = ProviderQuotaSnapshot.model_validate_json(account_key.provider_quota_snapshot)
        assert snapshot.used == 56

        async with async_session() as session:
            stored = await session.execute(
                select(AccountKeyModel).where(AccountKeyModel.id == key_id)
            )
            stored_key = stored.scalar_one()
            assert stored_key.provider_quota_snapshot == account_key.provider_quota_snapshot


@pytest.mark.asyncio
async def test_quota_endpoint_permissions_unsupported_and_adapter_rebuild() -> None:
    app = create_app()
    service_name = f"quota-generic-{uuid4().hex[:8]}"

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        admin_headers = await _login_admin(client)
        created = await client.post(
            "/api/admin/services",
            headers=admin_headers,
            json={
                "name": service_name,
                "upstream_url": "https://untrusted.example/mcp",
                "provider_type": "generic",
                "api_keys": ["not-used"],
            },
        )
        service_id = str(created.json()["id"])

        unauthenticated = await client.get(f"/api/admin/services/{service_id}/quota-status")
        assert unauthenticated.status_code == 401

        unsupported = await client.get(
            f"/api/admin/services/{service_id}/quota-status",
            headers=admin_headers,
        )
        assert unsupported.status_code == 200
        assert unsupported.json() == {
            "service_id": service_id,
            "provider_type": "generic",
            "supported": False,
            "can_refresh": True,
            "status": "unsupported",
            "keys": [],
        }

        username = f"quota-user-{uuid4().hex[:8]}"
        create_user = await client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={"username": username, "password": "test-password", "role": "user"},
        )
        assert create_user.status_code == 200
        login = await client.post(
            "/api/auth/login",
            json={"username": username, "password": "test-password"},
        )
        user_headers = {"Authorization": f"Bearer {login.json()['token']}"}
        forbidden = await client.get(
            f"/api/admin/services/{service_id}/quota-status",
            headers=user_headers,
        )
        assert forbidden.status_code == 403

        manager = db_value_registry().get_manager(service_id)
        assert manager is not None
        assert isinstance(manager.provider_adapter, GenericHeaderProviderAdapter)

        updated = await client.patch(
            f"/api/admin/services/{service_id}",
            headers=admin_headers,
            json={"provider_type": "context7"},
        )
        assert updated.status_code == 200
        assert isinstance(manager.provider_adapter, Context7ProviderAdapter)

        private_refresh = await client.post(
            f"/api/admin/services/{service_id}/quota-status/refresh",
            headers=user_headers,
        )
        assert private_refresh.status_code == 403

        manager.owner_id = None
        shared_read = await client.get(
            f"/api/admin/services/{service_id}/quota-status",
            headers=user_headers,
        )
        shared_refresh = await client.post(
            f"/api/admin/services/{service_id}/quota-status/refresh",
            headers=user_headers,
        )
        assert shared_read.status_code == 200
        assert shared_read.json()["can_refresh"] is False
        assert shared_refresh.status_code == 403


def db_value_registry() -> KeyPoolRegistry:
    # Import lazily so tests always observe the registry set by the active lifespan.
    from mcp_pool import admin_routes

    assert admin_routes.registry is not None
    return admin_routes.registry


@pytest.mark.asyncio
async def test_quota_refresh_singleflight_and_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    service_name = f"quota-guard-{uuid4().hex[:8]}"
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow_fetch(
        _adapter: Context7ProviderAdapter,
        _credential: str,
        _client: httpx.AsyncClient,
    ) -> ProviderQuotaSnapshot:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        checked_at = datetime.now(UTC)
        return ProviderQuotaSnapshot(
            status="ok",
            used=1,
            limit=100,
            remaining=99,
            reset_at=checked_at + timedelta(days=1),
            checked_at=checked_at,
        )

    monkeypatch.setattr(Context7ProviderAdapter, "fetch_quota_status", slow_fetch)

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        headers = await _login_admin(client)
        created = await client.post(
            "/api/admin/services",
            headers=headers,
            json={
                "name": service_name,
                "upstream_url": "https://mcp.context7.com/mcp",
                "provider_type": "context7",
                "api_keys": ["ctx7-guard-key"],
            },
        )
        service_id = str(created.json()["id"])
        key_id = str(created.json()["keys"][0]["id"])
        endpoint = f"/api/admin/services/{service_id}/quota-status/refresh"

        first = asyncio.create_task(
            client.post(endpoint, params={"key_id": key_id}, headers=headers)
        )
        await asyncio.wait_for(started.wait(), timeout=1)

        duplicate = await client.post(endpoint, params={"key_id": key_id}, headers=headers)
        assert duplicate.status_code == 409
        assert calls == 1

        release.set()
        completed = await first
        assert completed.status_code == 200

        cooling_down = await client.post(endpoint, params={"key_id": key_id}, headers=headers)
        assert cooling_down.status_code == 429
        assert int(cooling_down.headers["retry-after"]) >= 1
        assert calls == 1


@pytest.mark.asyncio
async def test_bulk_quota_refresh_has_a_bounded_batch_size() -> None:
    app = create_app()
    service_name = f"quota-batch-{uuid4().hex[:8]}"

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        headers = await _login_admin(client)
        created = await client.post(
            "/api/admin/services",
            headers=headers,
            json={
                "name": service_name,
                "upstream_url": "https://mcp.context7.com/mcp",
                "provider_type": "context7",
                "api_keys": [f"ctx7-batch-{index}" for index in range(21)],
            },
        )
        service_id = str(created.json()["id"])

        response = await client.post(
            f"/api/admin/services/{service_id}/quota-status/refresh",
            headers=headers,
        )

        assert response.status_code == 422
        assert "20 keys" in response.json()["detail"]


@pytest.mark.asyncio
async def test_replacing_secret_drops_inflight_old_credential_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    service_name = f"quota-secret-race-{uuid4().hex[:8]}"
    started = asyncio.Event()
    release = asyncio.Event()
    credentials: list[str] = []

    async def delayed_fetch(
        _adapter: Context7ProviderAdapter,
        credential: str,
        _client: httpx.AsyncClient,
    ) -> ProviderQuotaSnapshot:
        credentials.append(credential)
        if credential == "old-secret":
            started.set()
            await release.wait()
        checked_at = datetime.now(UTC)
        return ProviderQuotaSnapshot(
            status="ok",
            used=20,
            limit=100,
            remaining=80,
            reset_at=checked_at + timedelta(days=1),
            checked_at=checked_at,
        )

    monkeypatch.setattr(Context7ProviderAdapter, "fetch_quota_status", delayed_fetch)

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        headers = await _login_admin(client)
        created = await client.post(
            "/api/admin/services",
            headers=headers,
            json={
                "name": service_name,
                "upstream_url": "https://mcp.context7.com/mcp",
                "provider_type": "context7",
                "api_keys": ["old-secret"],
            },
        )
        service_id = str(created.json()["id"])
        key_id = str(created.json()["keys"][0]["id"])
        refresh_endpoint = f"/api/admin/services/{service_id}/quota-status/refresh"
        key_endpoint = f"/api/admin/services/{service_id}/keys/{key_id}"

        old_refresh = asyncio.create_task(
            client.post(refresh_endpoint, params={"key_id": key_id}, headers=headers)
        )
        await asyncio.wait_for(started.wait(), timeout=1)

        replaced = await client.patch(
            key_endpoint,
            headers=headers,
            json={"secret_key": "new-secret"},
        )
        assert replaced.status_code == 200
        release.set()
        old_result = await old_refresh
        assert old_result.status_code == 200
        old_key_state = old_result.json()["keys"][0]
        assert old_key_state["status"] == "unknown"
        assert old_key_state["last_success_at"] is None

        new_result = await client.post(
            refresh_endpoint,
            params={"key_id": key_id},
            headers=headers,
        )
        assert new_result.status_code == 200
        assert credentials == ["old-secret", "new-secret"]
        assert new_result.json()["keys"][0]["used"] == 20


@pytest.mark.asyncio
async def test_quota_refresh_selected_key_partial_failure_and_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mcp_pool.quota.PROVIDER_QUOTA_REFRESH_COOLDOWN_SECONDS",
        0.0,
    )
    app = create_app()
    service_name = f"quota-context7-{uuid4().hex[:8]}"
    calls: list[str] = []
    fail_good = False

    async def fake_fetch(
        _adapter: Context7ProviderAdapter,
        credential: str,
        _client: httpx.AsyncClient,
    ) -> ProviderQuotaSnapshot | ProviderQuotaError:
        calls.append(credential)
        checked_at = datetime.now(UTC)
        if credential == "good-key" and not fail_good:
            return ProviderQuotaSnapshot(
                status="ok",
                used=11,
                limit=100,
                remaining=89,
                reset_at=checked_at + timedelta(days=1),
                checked_at=checked_at,
            )
        if credential == "bad-key":
            return ProviderQuotaError(
                status="auth_invalid",
                checked_at=checked_at,
                error_code="auth_invalid",
            )
        return ProviderQuotaError(
            status="error",
            checked_at=checked_at,
            error_code="network_error",
        )

    monkeypatch.setattr(
        Context7ProviderAdapter,
        "fetch_quota_status",
        fake_fetch,
    )

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        headers = await _login_admin(client)
        created = await client.post(
            "/api/admin/services",
            headers=headers,
            json={
                "name": service_name,
                "upstream_url": "https://attacker.invalid/not-used-for-quota",
                "provider_type": "context7",
                "api_keys": ["good-key", "bad-key"],
            },
        )
        service_id = str(created.json()["id"])
        keys = created.json()["keys"]
        good_key_id = str(keys[0]["id"])
        bad_key_id = str(keys[1]["id"])
        registry = db_value_registry()
        await registry.add_log(
            RequestLogItem(
                id=str(uuid4()),
                service_name=service_name,
                timestamp=datetime.now(UTC),
                method="POST",
                path="mcp",
                mcp_method="tools/call (query-docs)",
                key_id=good_key_id,
                key_name=str(keys[0]["name"]),
                status_code=200,
                signal_kind="success",
                duration_ms=1.0,
            )
        )

        selected = await client.post(
            f"/api/admin/services/{service_id}/quota-status/refresh",
            params={"key_id": good_key_id},
            headers=headers,
        )
        assert selected.status_code == 200
        assert calls == ["good-key"]
        selected_keys = {item["key_id"]: item for item in selected.json()["keys"]}
        assert selected.json()["status"] == "partial"
        assert selected_keys[good_key_id]["status"] == "ok"
        assert selected_keys[good_key_id]["used"] == 11
        assert selected_keys[good_key_id]["stale"] is False
        assert selected_keys[good_key_id]["last_success_at"] is not None
        assert (
            selected_keys[good_key_id]["last_attempt_at"]
            == selected_keys[good_key_id]["last_success_at"]
        )
        assert selected_keys[bad_key_id]["status"] == "unknown"
        manager = registry.get_manager(service_id)
        assert manager is not None
        good_key = next(key for key in manager.keys if key.key_id == good_key_id)
        monthly_usage = await registry.get_monthly_usage()
        assert monthly_usage[good_key_id] == 1
        assert good_key.used_offset == 10
        assert good_key.to_response(monthly_usage).used_this_month == 11

        missing_key = await client.post(
            f"/api/admin/services/{service_id}/quota-status/refresh",
            params={"key_id": "missing-key"},
            headers=headers,
        )
        assert missing_key.status_code == 404

        calls.clear()
        all_keys = await client.post(
            f"/api/admin/services/{service_id}/quota-status/refresh",
            headers=headers,
        )
        assert all_keys.status_code == 200
        assert set(calls) == {"good-key", "bad-key"}
        all_key_data = {item["key_id"]: item for item in all_keys.json()["keys"]}
        assert all_keys.json()["status"] == "partial"
        assert all_key_data[good_key_id]["status"] == "ok"
        assert all_key_data[bad_key_id]["status"] == "auth_invalid"
        assert all_key_data[bad_key_id]["error_code"] == "auth_invalid"

        bad_key = next(key for key in manager.keys if key.key_id == bad_key_id)
        assert bad_key.is_active is True
        assert bad_key.quota_exhausted is False
        assert bad_key.requests_count == 0

        fail_good = True
        failed_refresh = await client.post(
            f"/api/admin/services/{service_id}/quota-status/refresh",
            params={"key_id": good_key_id},
            headers=headers,
        )
        failed_good = {item["key_id"]: item for item in failed_refresh.json()["keys"]}[good_key_id]
        assert failed_good["status"] == "error"
        assert failed_good["error_code"] == "network_error"
        assert failed_good["used"] == 11
        assert failed_good["stale"] is True
        assert failed_good["last_success_at"] is not None
        assert failed_good["last_attempt_at"] is not None
        assert failed_good["last_attempt_at"] != failed_good["last_success_at"]

        async with async_session() as session:
            stored = await session.execute(
                select(AccountKeyModel).where(AccountKeyModel.id == good_key_id)
            )
            stored_key = stored.scalar_one()
            assert stored_key.provider_quota_snapshot is not None
            assert stored_key.provider_quota_error is not None
            assert stored_key.used_offset == 10

        reloaded_registry = KeyPoolRegistry([])
        await reloaded_registry.initialize()
        reloaded_manager = reloaded_registry.get_manager(service_id)
        assert reloaded_manager is not None
        reloaded = get_provider_quota_status(reloaded_manager)
        reloaded_good = {item.key_id: item for item in reloaded.keys}[good_key_id]
        assert reloaded_good.status == "error"
        assert reloaded_good.used == 11
        assert reloaded_good.error_code == "network_error"
        reloaded_key = next(key for key in reloaded_manager.keys if key.key_id == good_key_id)
        assert reloaded_key.used_offset == 10


@pytest.mark.asyncio
async def test_sqlite_dynamic_migration_adds_provider_quota_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_db = tmp_path / "quota-migration.sqlite3"
    migration_engine = create_async_engine(f"sqlite+aiosqlite:///{migration_db}")
    async with migration_engine.begin() as connection:
        await connection.execute(text("CREATE TABLE account_keys (id VARCHAR(64) PRIMARY KEY)"))

    monkeypatch.setattr(db, "engine", migration_engine)
    await db.init_db()

    async with migration_engine.connect() as connection:
        result = await connection.execute(text("PRAGMA table_info(account_keys)"))
        columns = {str(row[1]) for row in result.all()}
    await migration_engine.dispose()

    assert "provider_quota_snapshot" in columns
    assert "provider_quota_error" in columns
