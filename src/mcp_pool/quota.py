import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import ValidationError

from mcp_pool.domain.quota import (
    ProviderQuotaError,
    ProviderQuotaKeyResponse,
    ProviderQuotaServiceResponse,
    ProviderQuotaServiceStatus,
    ProviderQuotaSnapshot,
)
from mcp_pool.pool import AccountKey, KeyPoolManager, KeyPoolRegistry
from mcp_pool.providers.context7 import (
    CONTEXT7_QUOTA_TIMEOUT_SECONDS,
    Context7ProviderAdapter,
)

PROVIDER_QUOTA_STALE_AFTER = timedelta(hours=1)
PROVIDER_QUOTA_REFRESH_COOLDOWN_SECONDS = 10.0
PROVIDER_QUOTA_MAX_BATCH_SIZE = 20


class ProviderQuotaRefreshInProgressError(Exception):
    """A selected key already has an upstream quota query in flight."""


class ProviderQuotaRefreshCooldownError(Exception):
    """A selected key was queried too recently."""

    def __init__(self, retry_after: int):
        super().__init__("provider quota refresh is cooling down")
        self.retry_after = retry_after


class ProviderQuotaRefreshBatchTooLargeError(Exception):
    """A bulk refresh exceeds the bounded per-request key count."""

    def __init__(self, max_batch_size: int):
        super().__init__("provider quota refresh batch is too large")
        self.max_batch_size = max_batch_size


def get_provider_quota_status(
    manager: KeyPoolManager,
    *,
    now: datetime | None = None,
    can_refresh: bool = False,
) -> ProviderQuotaServiceResponse:
    """Build a stable response from the last persisted provider observations."""
    if manager.provider_type.lower() != "context7":
        return ProviderQuotaServiceResponse(
            service_id=manager.service_id,
            provider_type=manager.provider_type,
            supported=False,
            can_refresh=can_refresh,
            status="unsupported",
            keys=[],
        )

    observed_at = _utc(now or datetime.now(UTC))
    keys = [_key_response(key, observed_at) for key in manager.keys]
    return ProviderQuotaServiceResponse(
        service_id=manager.service_id,
        provider_type=manager.provider_type,
        supported=True,
        can_refresh=can_refresh,
        status=_service_status(keys),
        keys=keys,
    )


async def refresh_provider_quota_status(
    manager: KeyPoolManager,
    registry: KeyPoolRegistry,
    *,
    key_id: str | None = None,
) -> ProviderQuotaServiceResponse:
    """Refresh one or all Context7 keys concurrently and persist each result."""
    if manager.provider_type.lower() != "context7":
        return get_provider_quota_status(manager, can_refresh=True)

    target_keys = list(manager.keys)
    if key_id is not None:
        target = next((key for key in manager.keys if key.key_id == key_id), None)
        if target is None:
            raise KeyError(key_id)
        target_keys = [target]
    elif len(target_keys) > PROVIDER_QUOTA_MAX_BATCH_SIZE:
        raise ProviderQuotaRefreshBatchTooLargeError(PROVIDER_QUOTA_MAX_BATCH_SIZE)

    adapter = manager.provider_adapter
    if not isinstance(adapter, Context7ProviderAdapter):
        return get_provider_quota_status(manager, can_refresh=True)

    targets = [(key, key.secret_key) for key in target_keys]
    target_ids = [key.key_id for key, _ in targets]
    claim, retry_after = await registry.claim_provider_quota_refresh(
        target_ids,
        cooldown_seconds=PROVIDER_QUOTA_REFRESH_COOLDOWN_SECONDS,
    )
    if claim == "in_progress":
        raise ProviderQuotaRefreshInProgressError
    if claim == "cooldown":
        raise ProviderQuotaRefreshCooldownError(retry_after)

    async def fetch(
        key: AccountKey,
        credential: str,
        client: httpx.AsyncClient,
    ) -> tuple[AccountKey, str, ProviderQuotaSnapshot | ProviderQuotaError]:
        try:
            async with registry.provider_quota_refresh_semaphore:
                result = await adapter.fetch_quota_status(credential, client)
        except Exception:
            result = ProviderQuotaError(
                status="error",
                checked_at=datetime.now(UTC),
                error_code="internal_error",
            )
        return key, credential, result

    try:
        if targets:
            timeout = httpx.Timeout(CONTEXT7_QUOTA_TIMEOUT_SECONDS)
            async with httpx.AsyncClient(timeout=timeout) as client:
                results = await asyncio.gather(
                    *(fetch(key, credential, client) for key, credential in targets)
                )

            updated_keys: list[AccountKey] = []
            for key, credential, result in results:
                if not any(current is key for current in manager.keys):
                    continue
                if adapter.apply_quota_result(
                    key,
                    result,
                    expected_credential=credential,
                ):
                    updated_keys.append(key)
            await registry.update_provider_quota_states_in_db(updated_keys)
    finally:
        await registry.release_provider_quota_refresh(target_ids)

    return get_provider_quota_status(manager, can_refresh=True)


def _key_response(key: AccountKey, now: datetime) -> ProviderQuotaKeyResponse:
    snapshot = _load_snapshot(key.provider_quota_snapshot)
    error = _load_error(key.provider_quota_error)
    stale = (
        error is not None
        or snapshot is None
        or now - _utc(snapshot.checked_at) > PROVIDER_QUOTA_STALE_AFTER
        or now >= _utc(snapshot.reset_at)
    )

    if snapshot is None:
        return ProviderQuotaKeyResponse(
            key_id=key.key_id,
            status=error.status if error is not None else "unknown",
            last_success_at=None,
            last_attempt_at=_utc(error.checked_at) if error is not None else None,
            stale=True,
            error_code=error.error_code if error is not None else None,
        )

    return ProviderQuotaKeyResponse(
        key_id=key.key_id,
        status=error.status if error is not None else snapshot.status,
        used=snapshot.used,
        limit=snapshot.limit,
        remaining=snapshot.remaining,
        reset_at=_utc(snapshot.reset_at),
        last_success_at=_utc(snapshot.checked_at),
        last_attempt_at=(
            _utc(error.checked_at) if error is not None else _utc(snapshot.checked_at)
        ),
        stale=stale,
        error_code=error.error_code if error is not None else snapshot.error_code,
    )


def _load_snapshot(value: str | None) -> ProviderQuotaSnapshot | None:
    if value is None:
        return None
    try:
        return ProviderQuotaSnapshot.model_validate_json(value)
    except (ValidationError, ValueError):
        return None


def _load_error(value: str | None) -> ProviderQuotaError | None:
    if value is None:
        return None
    try:
        return ProviderQuotaError.model_validate_json(value)
    except (ValidationError, ValueError):
        return None


def _service_status(keys: list[ProviderQuotaKeyResponse]) -> ProviderQuotaServiceStatus:
    if not keys:
        return "unknown"
    if all(key.status == "ok" for key in keys):
        return "ok"
    if all(key.status == "exhausted" for key in keys):
        return "exhausted"
    if any(key.status in ("ok", "exhausted") for key in keys):
        return "partial"
    if any(key.status in ("auth_invalid", "error") for key in keys):
        return "error"
    return "unknown"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
