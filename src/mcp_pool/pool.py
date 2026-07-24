import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from mcp_pool.domain.service import ServiceConfig
from mcp_pool.providers.base import ProviderAdapter, ProviderSignalKind
from mcp_pool.providers.context7 import Context7ProviderAdapter
from mcp_pool.providers.generic import GenericHeaderProviderAdapter


@dataclass
class AccountKey:
    key_id: str
    secret_key: str
    is_active: bool = True
    quota_exhausted: bool = False
    paused_until: datetime | None = None
    fail_count: int = 0

    def is_available(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        if not self.is_active or self.quota_exhausted:
            return False
        return not (self.paused_until and self.paused_until > current_time)


def get_provider_adapter(service_config: ServiceConfig) -> ProviderAdapter:
    """Factory function to build a provider adapter based on ServiceConfig."""
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
        self.service_name = service_config.name
        self.upstream_url = service_config.upstream_url.rstrip("/")
        self.provider_adapter = get_provider_adapter(service_config)
        self.keys: list[AccountKey] = [
            AccountKey(key_id=f"{service_config.name}-key-{i+1}", secret_key=k)
            for i, k in enumerate(service_config.api_keys)
        ]
        self._current_index: int = 0
        self._lock = asyncio.Lock()

    def add_key(self, secret_key: str, key_id: str | None = None) -> AccountKey:
        kid = key_id or f"{self.service_name}-key-{len(self.keys) + 1}"
        acc_key = AccountKey(key_id=kid, secret_key=secret_key)
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
        for key in self.keys:
            if key.key_id == key_id:
                if kind in (ProviderSignalKind.QUOTA_EXHAUSTED, ProviderSignalKind.AUTH_INVALID):
                    key.quota_exhausted = True
                    key.is_active = False
                elif kind == ProviderSignalKind.RATE_LIMITED:
                    key.paused_until = retry_at
                elif kind == ProviderSignalKind.SUCCESS:
                    key.fail_count = 0
                break


class KeyPoolRegistry:
    """Registry holding KeyPoolManagers for configured upstream services."""

    def __init__(self, services: Sequence[ServiceConfig]):
        self._managers: dict[str, KeyPoolManager] = {}
        for s in services:
            self._managers[s.name] = KeyPoolManager(s)
        self._default_service_name = services[0].name if services else None

    def get_manager(self, service_name: str | None = None) -> KeyPoolManager | None:
        if service_name and service_name in self._managers:
            return self._managers[service_name]
        if self._default_service_name and self._default_service_name in self._managers:
            return self._managers[self._default_service_name]
        return None
