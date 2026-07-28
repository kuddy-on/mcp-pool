from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

from mcp_pool.domain.quota import ProviderQuotaError, ProviderQuotaSnapshot
from mcp_pool.providers.base import (
    ProviderAdapter,
    ProviderSignal,
    ProviderSignalKind,
    parse_retry_after,
)

if TYPE_CHECKING:
    from mcp_pool.pool import AccountKey

CONTEXT7_QUOTA_URL = (
    "https://context7.com/api/v2/libs/search?libraryName=context7&query=quota-status"
)
CONTEXT7_QUOTA_TIMEOUT_SECONDS = 5.0


class Context7ProviderAdapter(ProviderAdapter):
    """Provider adapter for Context7 service."""

    name: str = "context7"

    def prepare_headers(self, credential: str, headers: httpx.Headers) -> httpx.Headers:
        """Inject Authorization header with Bearer API Key into upstream request."""
        new_headers = httpx.Headers(headers)
        new_headers.pop("host", None)
        new_headers.pop("content-length", None)

        token = credential if credential.startswith("Bearer ") else f"Bearer {credential}"
        new_headers["authorization"] = token
        return new_headers

    async def classify_response(self, response: httpx.Response) -> ProviderSignal:
        """Classify Context7 responses into pool signals."""
        status = response.status_code

        if 200 <= status < 300:
            return ProviderSignal(kind=ProviderSignalKind.SUCCESS)

        if status in (401, 403):
            return ProviderSignal(
                kind=ProviderSignalKind.AUTH_INVALID,
                reason=f"Context7 rejected the API key ({status})",
                authoritative=True,
            )

        if status == 429:
            return ProviderSignal(
                kind=ProviderSignalKind.RATE_LIMITED,
                retry_at=parse_retry_after(response),
                reason="Rate limited (429)",
                authoritative=True,
            )

        if status >= 500:
            return ProviderSignal(
                kind=ProviderSignalKind.UPSTREAM_UNHEALTHY,
                reason=f"Server error ({status})",
            )

        return ProviderSignal(
            kind=ProviderSignalKind.UNKNOWN_ERROR,
            reason=f"Unexpected status code {status}",
        )

    async def fetch_quota_status(
        self,
        credential: str,
        client: httpx.AsyncClient,
    ) -> ProviderQuotaSnapshot | ProviderQuotaError:
        """Consume one Context7 request and return the post-request quota values.

        Context7 reports quota through RateLimit-* headers. The HEAD request itself
        consumes one request, so ``remaining`` and the derived ``used`` value describe
        the account immediately after this check.
        """
        token = credential if credential.startswith("Bearer ") else f"Bearer {credential}"
        try:
            response = await client.head(
                CONTEXT7_QUOTA_URL,
                headers={
                    "authorization": token,
                    "accept": "application/json",
                },
            )
        except httpx.TimeoutException:
            return ProviderQuotaError(
                status="error",
                checked_at=datetime.now(UTC),
                error_code="timeout",
            )
        except httpx.RequestError:
            return ProviderQuotaError(
                status="error",
                checked_at=datetime.now(UTC),
                error_code="network_error",
            )

        return parse_context7_quota_response(response)

    def capture_quota_response(
        self,
        key: AccountKey,
        response: httpx.Response,
        *,
        expected_credential: str,
    ) -> None:
        """Apply quota metadata from a request that was already sent.

        The credential comparison prevents a response from an in-flight request from
        overwriting quota state after an administrator has replaced the key.
        """
        if response.status_code in (401, 403):
            result: ProviderQuotaSnapshot | ProviderQuotaError = parse_context7_quota_response(
                response
            )
        elif response.status_code == 429 or 200 <= response.status_code < 300:
            required_headers = (
                "ratelimit-limit",
                "ratelimit-remaining",
                "ratelimit-reset",
            )
            if any(response.headers.get(name) is None for name in required_headers):
                return
            result = parse_context7_quota_response(response)
        else:
            return

        self.apply_quota_result(
            key,
            result,
            expected_credential=expected_credential,
        )

    def apply_quota_result(
        self,
        key: AccountKey,
        result: ProviderQuotaSnapshot | ProviderQuotaError,
        *,
        expected_credential: str,
    ) -> bool:
        """Apply a current-credential result without allowing stale quota rollback."""
        if key.secret_key != expected_credential:
            return False

        if isinstance(result, ProviderQuotaSnapshot):
            previous = _load_snapshot(key.provider_quota_snapshot)
            previous_error = _load_error(key.provider_quota_error)
            if previous_error is not None and _utc(result.checked_at) < _utc(
                previous_error.checked_at
            ):
                return False
            if previous is not None:
                previous_reset = _utc(previous.reset_at)
                result_reset = _utc(result.reset_at)
                if result_reset < previous_reset:
                    return False
                if (
                    result_reset == previous_reset
                    and result.limit == previous.limit
                    and result.remaining > previous.remaining
                ):
                    return False
            key.provider_quota_snapshot = result.model_dump_json()
            key.provider_quota_error = None
        else:
            previous_error = _load_error(key.provider_quota_error)
            previous_snapshot = _load_snapshot(key.provider_quota_snapshot)
            if previous_error is not None and _utc(result.checked_at) < _utc(
                previous_error.checked_at
            ):
                return False
            if previous_snapshot is not None and _utc(result.checked_at) < _utc(
                previous_snapshot.checked_at
            ):
                return False
            # Preserve the last valid snapshot while recording the latest failure.
            key.provider_quota_error = result.model_dump_json()
        return True


def parse_context7_quota_response(
    response: httpx.Response,
    *,
    checked_at: datetime | None = None,
) -> ProviderQuotaSnapshot | ProviderQuotaError:
    """Normalize a Context7 quota response without exposing response contents."""
    observed_at = checked_at or datetime.now(UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    else:
        observed_at = observed_at.astimezone(UTC)

    if response.status_code in (401, 403):
        return ProviderQuotaError(
            status="auth_invalid",
            checked_at=observed_at,
            error_code="auth_invalid",
        )

    if response.status_code != 429 and not 200 <= response.status_code < 300:
        error_code = "upstream_error" if response.status_code >= 500 else "unexpected_http_status"
        return ProviderQuotaError(
            status="error",
            checked_at=observed_at,
            error_code=error_code,
        )

    header_names = ("ratelimit-limit", "ratelimit-remaining", "ratelimit-reset")
    if any(response.headers.get(name) is None for name in header_names):
        return ProviderQuotaError(
            status="error",
            checked_at=observed_at,
            error_code="missing_rate_limit_headers",
        )

    try:
        limit = _parse_non_negative_header(response.headers["ratelimit-limit"])
        remaining = _parse_non_negative_header(response.headers["ratelimit-remaining"])
        reset_epoch = _parse_non_negative_header(response.headers["ratelimit-reset"])
        if remaining > limit:
            raise ValueError("remaining exceeds limit")
        reset_at = datetime.fromtimestamp(reset_epoch, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return ProviderQuotaError(
            status="error",
            checked_at=observed_at,
            error_code="invalid_rate_limit_headers",
        )

    exhausted = response.status_code == 429 or remaining == 0
    return ProviderQuotaSnapshot(
        status="exhausted" if exhausted else "ok",
        used=limit - remaining,
        limit=limit,
        remaining=remaining,
        reset_at=reset_at,
        checked_at=observed_at,
        error_code="rate_limited" if response.status_code == 429 else None,
    )


def _parse_non_negative_header(value: str) -> int:
    if not value or not value.isdecimal():
        raise ValueError("rate limit header must be a non-negative decimal integer")
    return int(value)


def _load_snapshot(value: str | None) -> ProviderQuotaSnapshot | None:
    if value is None:
        return None
    try:
        return ProviderQuotaSnapshot.model_validate_json(value)
    except ValueError:
        return None


def _load_error(value: str | None) -> ProviderQuotaError | None:
    if value is None:
        return None
    try:
        return ProviderQuotaError.model_validate_json(value)
    except ValueError:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
