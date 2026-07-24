from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from mcp_pool.domain.admin import KeyResponse, RequestLogItem, ServiceResponse
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

    def is_available(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        if not self.is_active or self.quota_exhausted:
            return False
        return not (self.paused_until and self.paused_until > current_time)

    def mask_key(self) -> str:
        if len(self.secret_key) <= 8:
            return "****"
        return f"{self.secret_key[:4]}...{self.secret_key[-4:]}"

    def to_response(self) -> KeyResponse:
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
        )


def get_provider_adapter(service_config: ServiceConfig) -> ProviderAdapter:
    ptype = service_config.provider_type.lower()
    if ptype == "context7":
        return Context7ProviderAdapter()
    return GenericHeaderProviderAdapter(
        name=service_config.name,
        auth_header=service_config.auth_header,
        auth_prefix=service_config.auth_prefix,
    )


class KeyPoolManager:
    """Manages key rotation and failover for a single upstream service."""

    def __init__(self, service_config: ServiceConfig):
        self.service_id = str(uuid4())
        self.service_name = service_config.name
        self.upstream_url = service_config.upstream_url.rstrip("/")
        self.provider_type = service_config.provider_type
        self.auth_header = service_config.auth_header
        self.auth_prefix = service_config.auth_prefix
        self.provider_adapter = get_provider_adapter(service_config)

        self.keys: list[AccountKey] = [
            AccountKey(
                key_id=f"{service_config.name}-key-{i+1}",
                name=f"Key-{i+1}",
                secret_key=k,
            )
            for i, k in enumerate(service_config.api_keys)
        ]
        self._current_index: int = 0

    def add_key(self, secret_key: str, name: str | None = None, weight: float = 1.0) -> AccountKey:
        kid = f"{self.service_name}-key-{len(self.keys) + 1}-{uuid4().hex[:4]}"
        kname = name or f"Key-{len(self.keys) + 1}"
        acc_key = AccountKey(key_id=kid, name=kname, secret_key=secret_key, weight=weight)
        self.keys.append(acc_key)
        return acc_key

    def get_current_key(self) -> AccountKey | None:
        if not self.keys:
            return None
        now = datetime.now(UTC)
        for i in range(len(self.keys)):
            idx = (self._current_index + i) % len(self.keys)
            key = self.keys[idx]
            if key.is_available(now):
                self._current_index = idx
                return key
        return None

    def mark_signal(
        self, key_id: str, kind: ProviderSignalKind, retry_at: datetime | None = None
    ) -> None:
        now = datetime.now(UTC)
        for key in self.keys:
            if key.key_id == key_id:
                key.requests_count += 1
                key.last_used = now
                if kind in (ProviderSignalKind.QUOTA_EXHAUSTED, ProviderSignalKind.AUTH_INVALID):
                    key.quota_exhausted = True
                    key.is_active = False
                elif kind == ProviderSignalKind.RATE_LIMITED:
                    key.paused_until = retry_at
                elif kind == ProviderSignalKind.SUCCESS:
                    key.fail_count = 0
                else:
                    key.fail_count += 1
                break

    def get_service_status(self) -> str:
        if not self.keys:
            return "unavailable"
        active_count = sum(1 for k in self.keys if k.is_available())
        if active_count == len(self.keys):
            return "active"
        if active_count > 0:
            return "degraded"
        return "unavailable"

    def to_response(self) -> ServiceResponse:
        active_keys = sum(1 for k in self.keys if k.is_available())
        return ServiceResponse(
            id=self.service_id,
            name=self.service_name,
            upstream_url=self.upstream_url,
            provider_type=self.provider_type,
            auth_header=self.auth_header,
            auth_prefix=self.auth_prefix,
            total_keys=len(self.keys),
            active_keys=active_keys,
            status=self.get_service_status(),
            keys=[k.to_response() for k in self.keys],
        )


class KeyPoolRegistry:
    """Registry holding KeyPoolManagers and Request logs."""

    def __init__(self, services: Sequence[ServiceConfig]):
        self._managers: dict[str, KeyPoolManager] = {}
        for s in services:
            self._managers[s.name] = KeyPoolManager(s)
        self._default_service_name = services[0].name if services else None
        self._logs: list[RequestLogItem] = []

    def get_manager(self, service_name: str | None = None) -> KeyPoolManager | None:
        if service_name and service_name in self._managers:
            return self._managers[service_name]
        if service_name:
            for mgr in self._managers.values():
                if mgr.service_id == service_name:
                    return mgr
        if self._default_service_name and self._default_service_name in self._managers:
            return self._managers[self._default_service_name]
        return None

    def get_manager_by_name(self, name: str) -> KeyPoolManager | None:
        return self._managers.get(name)

    def add_service(self, service_config: ServiceConfig) -> KeyPoolManager:
        mgr = KeyPoolManager(service_config)
        self._managers[service_config.name] = mgr
        if not self._default_service_name:
            self._default_service_name = service_config.name
        return mgr

    def remove_service(self, service_name_or_id: str) -> bool:
        target_name = None
        for name, mgr in self._managers.items():
            if name == service_name_or_id or mgr.service_id == service_name_or_id:
                target_name = name
                break
        if target_name:
            del self._managers[target_name]
            if self._default_service_name == target_name:
                self._default_service_name = next(iter(self._managers.keys()), None)
            return True
        return False

    def list_services(self) -> list[ServiceResponse]:
        return [mgr.to_response() for mgr in self._managers.values()]

    def add_log(self, log_item: RequestLogItem) -> None:
        self._logs.append(log_item)
        if len(self._logs) > 200:
            self._logs.pop(0)

    def get_logs(self, limit: int = 50) -> list[RequestLogItem]:
        return list(reversed(self._logs[-limit:]))
