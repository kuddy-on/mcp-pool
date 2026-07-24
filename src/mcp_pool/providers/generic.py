from datetime import UTC, datetime, timedelta

import httpx

from mcp_pool.providers.base import ProviderAdapter, ProviderSignal, ProviderSignalKind


class GenericHeaderProviderAdapter(ProviderAdapter):
    """Generic provider adapter configurable via header names and status mapping rules."""

    def __init__(
        self,
        name: str = "generic",
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer ",
    ):
        self.name = name
        self.auth_header = auth_header.lower()
        self.auth_prefix = auth_prefix

    def prepare_headers(self, credential: str, headers: httpx.Headers) -> httpx.Headers:
        """Inject API key into configured header."""
        new_headers = httpx.Headers(headers)
        new_headers.pop("host", None)
        new_headers.pop("content-length", None)

        if self.auth_prefix and not credential.startswith(self.auth_prefix):
            value = f"{self.auth_prefix}{credential}"
        else:
            value = credential

        new_headers[self.auth_header] = value
        return new_headers

    async def classify_response(self, response: httpx.Response) -> ProviderSignal:
        """Classify HTTP responses into pool signals using standard conventions."""
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
