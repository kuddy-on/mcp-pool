from datetime import datetime

from pydantic import BaseModel, Field


class KeyCreateRequest(BaseModel):
    name: str
    secret_key: str
    weight: float = 1.0


class KeyUpdateRequest(BaseModel):
    name: str | None = None
    secret_key: str | None = None
    weight: float | None = None
    is_active: bool | None = None


class KeyResponse(BaseModel):
    id: str
    name: str
    key_masked: str
    is_active: bool
    quota_exhausted: bool
    paused_until: datetime | None = None
    weight: float = 1.0
    fail_count: int = 0
    requests_count: int = 0
    last_used: datetime | None = None


class ServiceCreateRequest(BaseModel):
    name: str
    upstream_url: str
    provider_type: str = "generic"
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    api_keys: list[str] = Field(default_factory=list)


class ServiceUpdateRequest(BaseModel):
    upstream_url: str | None = None
    provider_type: str | None = None
    auth_header: str | None = None
    auth_prefix: str | None = None


class ServiceResponse(BaseModel):
    id: str
    name: str
    upstream_url: str
    provider_type: str
    auth_header: str
    auth_prefix: str
    total_keys: int
    active_keys: int
    status: str = "active"  # active, degraded, unavailable
    keys: list[KeyResponse] = Field(default_factory=list)


class RequestLogItem(BaseModel):
    id: str
    service_name: str
    timestamp: datetime
    method: str
    path: str
    key_id: str | None
    status_code: int
    signal_kind: str
    duration_ms: float
    failover_chain: list[str] = Field(default_factory=list)


class TestResultItem(BaseModel):
    step: str
    success: bool
    message: str
    duration_ms: float
