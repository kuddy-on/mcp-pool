from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from mcp_pool.domain.service import normalize_upstream_url


class KeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    secret_key: str = Field(min_length=1, max_length=8192)
    weight: float = Field(default=1.0, gt=0, le=100)
    monthly_quota: int = Field(default=0, ge=0)  # 0 = unlimited


class KeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    secret_key: str | None = Field(default=None, min_length=1, max_length=8192)
    weight: float | None = Field(default=None, gt=0, le=100)
    is_active: bool | None = None
    monthly_quota: int | None = Field(default=None, ge=0)
    used_this_month: int | None = Field(default=None, ge=0)


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
    name: str = Field(min_length=1, max_length=64)
    upstream_url: str = Field(min_length=8, max_length=2048)
    provider_type: str = "generic"
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    api_keys: list[str] = Field(default_factory=list)

    _normalize_url = field_validator("upstream_url")(normalize_upstream_url)


class ServiceUpdateRequest(BaseModel):
    upstream_url: str | None = Field(default=None, min_length=8, max_length=2048)
    provider_type: str | None = None
    auth_header: str | None = None
    auth_prefix: str | None = None

    _normalize_url = field_validator("upstream_url")(normalize_upstream_url)


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
    name: str = Field(min_length=1, max_length=64)


class SystemSettingsResponse(BaseModel):
    gateway_external_url: str


class SystemSettingsUpdateRequest(BaseModel):
    gateway_external_url: str = Field(min_length=8, max_length=2048)

    _normalize_url = field_validator("gateway_external_url")(normalize_upstream_url)
