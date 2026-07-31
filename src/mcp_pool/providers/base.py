from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Protocol

import httpx

HOP_BY_HOP_REQUEST_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class ProviderSignalKind(StrEnum):
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH_EXPIRED = "auth_expired"
    AUTH_INVALID = "auth_invalid"
    UPSTREAM_UNHEALTHY = "upstream_unhealthy"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True, slots=True)
class ProviderSignal:
    kind: ProviderSignalKind
    retry_at: datetime | None = None
    reason: str | None = None
    authoritative: bool = False


class ProviderAdapter(Protocol):
    """Boundary for provider-specific authentication and quota behavior."""

    name: str

    def prepare_headers(self, credential: str, headers: httpx.Headers) -> httpx.Headers:
        """Return upstream headers with provider credentials injected."""
        ...

    async def classify_response(self, response: httpx.Response) -> ProviderSignal:
        """Translate provider-specific responses into gateway state signals."""
        ...


def sanitize_request_headers(headers: httpx.Headers) -> httpx.Headers:
    """Remove hop-by-hop fields, including names nominated by Connection."""
    sanitized = httpx.Headers(headers)
    connection_tokens = {
        token.strip().lower()
        for token in sanitized.get("connection", "").split(",")
        if token.strip()
    }
    for name in HOP_BY_HOP_REQUEST_HEADERS | connection_tokens:
        sanitized.pop(name, None)
    return sanitized


def parse_retry_after(response: httpx.Response, default_seconds: float = 60.0) -> datetime:
    """Parse Retry-After seconds or HTTP-date, with a bounded fallback cooldown."""
    value = response.headers.get("retry-after")
    now = datetime.now(UTC)
    if value:
        try:
            seconds = max(0.0, min(float(value), 3600.0))
            return now + timedelta(seconds=seconds)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return max(now, parsed.astimezone(UTC))
            except (TypeError, ValueError, OverflowError):
                pass
    return now + timedelta(seconds=default_seconds)
