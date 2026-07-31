from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from mcp_pool.domain.admin import KeyResponse, ServiceResponse
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.providers.base import ProviderAdapter, ProviderSignalKind
from mcp_pool.providers.context7 import Context7ProviderAdapter
from mcp_pool.providers.generic import GenericHeaderProviderAdapter


@dataclass
class AccountKey:
    key_id: str
    name: str
    secret_key: str
    is_active: bool = True
    quota_exhausted: bool = False
    paused_until: datetime | None = None
    weight: float = 1.0
    fail_count: int = 0
    requests_count: int = 0
    last_used: datetime | None = None
    monthly_quota: int = 0
    used_offset: int = 0
    provider_quota_snapshot: str | None = None
    provider_quota_error: str | None = None

    def is_available(self, now: datetime | None = None, used_this_month: int = 0) -> bool:
        current_time = now or datetime.now(UTC)
        if not self.is_active or self.quota_exhausted:
            return False
        if self.monthly_quota > 0 and used_this_month >= self.monthly_quota:
            return False
        paused_until = self.paused_until
        if paused_until and paused_until.tzinfo is None:
            paused_until = paused_until.replace(tzinfo=UTC)
        return not (paused_until and paused_until > current_time)

    def mask_key(self) -> str:
        return (
            "****"
            if len(self.secret_key) <= 8
            else f"{self.secret_key[:4]}...{self.secret_key[-4:]}"
        )

    def to_response(self, monthly_usage: Mapping[str, int] | None = None) -> KeyResponse:
        total_used = (monthly_usage or {}).get(self.key_id, 0) + self.used_offset
        return KeyResponse(
            id=self.key_id,
            name=self.name,
            key_masked=self.mask_key(),
            is_active=self.is_active,
            quota_exhausted=self.quota_exhausted,
            paused_until=self.paused_until,
            weight=self.weight,
            fail_count=self.fail_count,
            requests_count=self.requests_count,
            last_used=self.last_used,
            monthly_quota=self.monthly_quota,
            used_this_month=total_used,
        )


def get_provider_adapter(config: ServiceConfig) -> ProviderAdapter:
    if config.provider_type.lower() == "context7":
        return Context7ProviderAdapter()
    return GenericHeaderProviderAdapter(
        name=config.name, auth_header=config.auth_header, auth_prefix=config.auth_prefix
    )


class KeyPoolManager:
    """Pure in-memory key selection and failover policy for one service."""

    def __init__(self, service_id: str, config: ServiceConfig, owner_id: str | None = None):
        self.service_id = service_id
        self.service_name = config.name
        self.upstream_url = config.upstream_url.rstrip("/")
        self.provider_type = config.provider_type
        self.auth_header = config.auth_header
        self.auth_prefix = config.auth_prefix
        self.owner_id = owner_id
        self.provider_adapter = get_provider_adapter(config)
        self.keys = [
            AccountKey(
                key_id=f"{config.name}-key-{index + 1}", name=f"Key-{index + 1}", secret_key=key
            )
            for index, key in enumerate(config.api_keys)
        ]
        self._weighted_current: dict[str, float] = {}

    def add_key(
        self, secret_key: str, name: str | None = None, weight: float = 1.0, monthly_quota: int = 0
    ) -> AccountKey:
        key = AccountKey(
            key_id=f"{self.service_name}-key-{len(self.keys) + 1}-{uuid4().hex[:4]}",
            name=name or f"Key-{len(self.keys) + 1}",
            secret_key=secret_key,
            weight=weight,
            monthly_quota=monthly_quota,
        )
        self.keys.append(key)
        return key

    def get_current_key(
        self,
        monthly_usage: Mapping[str, int] | None = None,
        excluded_key_ids: set[str] | None = None,
        preferred_key_id: str | None = None,
    ) -> AccountKey | None:
        if not self.keys:
            return None
        now, usage, excluded = datetime.now(UTC), monthly_usage or {}, excluded_key_ids or set()
        if preferred_key_id is not None:
            preferred = next((key for key in self.keys if key.key_id == preferred_key_id), None)
            if preferred is None or preferred.key_id in excluded:
                return None
            return (
                preferred
                if preferred.is_available(
                    now, usage.get(preferred.key_id, 0) + preferred.used_offset
                )
                else None
            )
        eligible = [
            key
            for key in self.keys
            if key.key_id not in excluded
            and key.is_available(now, usage.get(key.key_id, 0) + key.used_offset)
        ]
        if not eligible:
            return None
        total_weight = 0.0
        for key in eligible:
            weight = max(0.01, key.weight)
            total_weight += weight
            self._weighted_current[key.key_id] = (
                self._weighted_current.get(key.key_id, 0.0) + weight
            )
        selected = max(eligible, key=lambda key: self._weighted_current[key.key_id])
        self._weighted_current[selected.key_id] -= total_weight
        return selected

    def mark_signal(
        self, key_id: str, kind: ProviderSignalKind, retry_at: datetime | None = None
    ) -> AccountKey | None:
        for key in self.keys:
            if key.key_id != key_id:
                continue
            key.requests_count += 1
            key.last_used = datetime.now(UTC)
            if kind in (ProviderSignalKind.QUOTA_EXHAUSTED, ProviderSignalKind.AUTH_INVALID):
                key.quota_exhausted, key.is_active = True, False
            elif kind == ProviderSignalKind.RATE_LIMITED:
                key.paused_until = retry_at
            elif kind == ProviderSignalKind.SUCCESS:
                key.fail_count = 0
            else:
                key.fail_count += 1
            return key
        return None

    def get_service_status(self, monthly_usage: Mapping[str, int] | None = None) -> str:
        if not self.keys:
            return "unavailable"
        usage = monthly_usage or {}
        active = sum(
            key.is_available(used_this_month=usage.get(key.key_id, 0) + key.used_offset)
            for key in self.keys
        )
        return "active" if active == len(self.keys) else "degraded" if active else "unavailable"

    def to_response(self, monthly_usage: Mapping[str, int] | None = None) -> ServiceResponse:
        usage = monthly_usage or {}
        active = sum(
            key.is_available(used_this_month=usage.get(key.key_id, 0) + key.used_offset)
            for key in self.keys
        )
        return ServiceResponse(
            id=self.service_id,
            name=self.service_name,
            upstream_url=self.upstream_url,
            provider_type=self.provider_type,
            auth_header=self.auth_header,
            auth_prefix=self.auth_prefix,
            total_keys=len(self.keys),
            active_keys=active,
            status=self.get_service_status(usage),
            keys=[key.to_response(monthly_usage) for key in self.keys],
        )
