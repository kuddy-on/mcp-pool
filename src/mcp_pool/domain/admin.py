from datetime import datetime

from pydantic import BaseModel, Field


class KeyCreateRequest(BaseModel):
    name: str
    secret_key: str
    weight: float = 1.0
    monthly_quota: int = 0  # 0 = unlimited


class KeyUpdateRequest(BaseModel):
    name: str | None = None
    secret_key: str | None = None
    weight: float | None = None
    is_active: bool | None = None
    monthly_quota: int | None = None
    used_this_month: int | None = None


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
    monthly_quota: int = 0  # 0 = unlimited
    used_this_month: int = 0


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
    mcp_method: str | None = None
    key_id: str | None = None
    key_name: str | None = None
    client_key_name: str | None = None
    client_ip: str | None = None
    status_code: int
    signal_kind: str
    duration_ms: float
    failover_chain: list[str] = Field(default_factory=list)


class TestResultItem(BaseModel):
    step: str
    success: bool
    message: str
    duration_ms: float


class ClientApiKeyResponse(BaseModel):
    id: str
    name: str
    api_key_masked: str
    is_active: bool
    created_at: datetime


class ClientApiKeyCreateRequest(BaseModel):
    name: str


class SystemSettingsResponse(BaseModel):
    gateway_external_url: str


class SystemSettingsUpdateRequest(BaseModel):
    gateway_external_url: str
