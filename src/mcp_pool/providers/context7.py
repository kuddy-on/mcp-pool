from datetime import UTC, datetime, timedelta

import httpx

from mcp_pool.providers.base import ProviderAdapter, ProviderSignal, ProviderSignalKind


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
                kind=ProviderSignalKind.QUOTA_EXHAUSTED,
                reason=f"Auth error or quota limit reached ({status})",
                authoritative=True,
            )

        if status == 429:
            retry_after_str = response.headers.get("retry-after")
            retry_at = None
            if retry_after_str:
                try:
                    seconds = float(retry_after_str)
                    retry_at = datetime.now(UTC) + timedelta(seconds=seconds)
                except ValueError:
                    pass
            return ProviderSignal(
                kind=ProviderSignalKind.RATE_LIMITED,
                retry_at=retry_at,
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
