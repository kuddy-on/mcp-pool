from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProviderQuotaKeyStatus = Literal["ok", "exhausted", "unknown", "auth_invalid", "error"]
ProviderQuotaServiceStatus = Literal[
    "unsupported",
    "unknown",
    "ok",
    "partial",
    "exhausted",
    "error",
]


class ProviderQuotaSnapshot(BaseModel):
    """Last authoritative provider values plus successful local usage since then."""

    status: Literal["ok", "exhausted"]
    used: int = Field(ge=0)
    limit: int = Field(ge=0)
    remaining: int = Field(ge=0)
    reset_at: datetime
    checked_at: datetime
    local_usage_events: list[datetime] = Field(default_factory=list)
    error_code: str | None = None


class ProviderQuotaError(BaseModel):
    """Most recent quota-check failure, stored separately from the last snapshot."""

    status: Literal["auth_invalid", "error"]
    checked_at: datetime
    error_code: str


class ProviderQuotaKeyResponse(BaseModel):
    key_id: str
    status: ProviderQuotaKeyStatus
    used: int | None = None
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    stale: bool
    estimated: bool = False
    error_code: str | None = None


class ProviderQuotaServiceResponse(BaseModel):
    service_id: str
    provider_type: str
    supported: bool
    can_refresh: bool = False
    status: ProviderQuotaServiceStatus
    keys: list[ProviderQuotaKeyResponse] = Field(default_factory=list)
