from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

import httpx


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
