import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from mcp_pool.db import AccountKeyModel, RequestLogModel, ServiceModel, async_session
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

    def __init__(self, service_id: str, service_config: ServiceConfig):
        self.service_id = service_id
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
    """Registry holding KeyPoolManagers and SQLite DB Syncing."""

    def __init__(self, default_services: Sequence[ServiceConfig]):
        self._managers: dict[str, KeyPoolManager] = {}
        self._default_services = default_services
        self._default_service_name: str | None = None
        self._logs: list[RequestLogItem] = []

    async def initialize(self) -> None:
        """Load persistent records from SQLite DB or seed with default services."""
        async with async_session() as session:
            stmt = select(ServiceModel).options(selectinload(ServiceModel.keys))
            result = await session.execute(stmt)
            db_services = result.scalars().all()

            if not db_services and self._default_services:
                # Seed default services into DB
                for s in self._default_services:
                    srv_model = ServiceModel(
                        name=s.name,
                        upstream_url=s.upstream_url,
                        provider_type=s.provider_type,
                        auth_header=s.auth_header,
                        auth_prefix=s.auth_prefix,
                    )
                    session.add(srv_model)
                    await session.flush()

                    mgr = KeyPoolManager(srv_model.id, s)
                    for k in mgr.keys:
                        k_model = AccountKeyModel(
                            id=k.key_id,
                            service_id=srv_model.id,
                            name=k.name,
                            secret_key=k.secret_key,
                            is_active=k.is_active,
                            weight=k.weight,
                        )
                        session.add(k_model)
                    self._managers[s.name] = mgr

                await session.commit()
                if self._default_services:
                    self._default_service_name = self._default_services[0].name
            else:
                for db_s in db_services:
                    cfg = ServiceConfig(
                        name=db_s.name,
                        upstream_url=db_s.upstream_url,
                        provider_type=db_s.provider_type,
                        auth_header=db_s.auth_header,
                        auth_prefix=db_s.auth_prefix,
                        api_keys=[],
                    )
                    mgr = KeyPoolManager(db_s.id, cfg)
                    mgr.keys = [
                        AccountKey(
                            key_id=k.id,
                            name=k.name,
                            secret_key=k.secret_key,
                            is_active=k.is_active,
                            quota_exhausted=k.quota_exhausted,
                            paused_until=k.paused_until,
                            weight=k.weight,
                            fail_count=k.fail_count,
                            requests_count=k.requests_count,
                            last_used=k.last_used,
                        )
                        for k in db_s.keys
                    ]
                    self._managers[db_s.name] = mgr

                if db_services:
                    self._default_service_name = db_services[0].name

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

    async def add_service(self, service_config: ServiceConfig) -> KeyPoolManager:
        async with async_session() as session:
            srv_model = ServiceModel(
                name=service_config.name,
                upstream_url=service_config.upstream_url,
                provider_type=service_config.provider_type,
                auth_header=service_config.auth_header,
                auth_prefix=service_config.auth_prefix,
            )
            session.add(srv_model)
            await session.flush()

            mgr = KeyPoolManager(srv_model.id, service_config)
            for k in mgr.keys:
                k_model = AccountKeyModel(
                    id=k.key_id,
                    service_id=srv_model.id,
                    name=k.name,
                    secret_key=k.secret_key,
                    is_active=k.is_active,
                    weight=k.weight,
                )
                session.add(k_model)

            await session.commit()

        self._managers[service_config.name] = mgr
        if not self._default_service_name:
            self._default_service_name = service_config.name
        return mgr

    async def remove_service(self, service_name_or_id: str) -> bool:
        target_name = None
        target_id = None
        for name, mgr in self._managers.items():
            if name == service_name_or_id or mgr.service_id == service_name_or_id:
                target_name = name
                target_id = mgr.service_id
                break

        if target_name and target_id:
            async with async_session() as session:
                stmt = select(ServiceModel).where(ServiceModel.id == target_id)
                res = await session.execute(stmt)
                srv = res.scalar_one_or_none()
                if srv:
                    await session.delete(srv)
                    await session.commit()

            del self._managers[target_name]
            if self._default_service_name == target_name:
                self._default_service_name = next(iter(self._managers.keys()), None)
            return True
        return False

    async def add_key_to_service(
        self, service_id: str, secret_key: str, name: str | None = None, weight: float = 1.0
    ) -> AccountKey | None:
        mgr = self.get_manager(service_id)
        if not mgr:
            return None

        key = mgr.add_key(secret_key=secret_key, name=name, weight=weight)
        async with async_session() as session:
            k_model = AccountKeyModel(
                id=key.key_id,
                service_id=mgr.service_id,
                name=key.name,
                secret_key=key.secret_key,
                is_active=key.is_active,
                weight=key.weight,
            )
            session.add(k_model)
            await session.commit()

        return key

    async def update_key_in_db(self, key_id: str, account_key: AccountKey) -> None:
        async with async_session() as session:
            stmt = select(AccountKeyModel).where(AccountKeyModel.id == key_id)
            res = await session.execute(stmt)
            km = res.scalar_one_or_none()
            if km:
                km.name = account_key.name
                km.secret_key = account_key.secret_key
                km.is_active = account_key.is_active
                km.quota_exhausted = account_key.quota_exhausted
                km.paused_until = account_key.paused_until
                km.weight = account_key.weight
                km.fail_count = account_key.fail_count
                km.requests_count = account_key.requests_count
                km.last_used = account_key.last_used
                await session.commit()

    async def delete_key_from_db(self, service_id: str, key_id: str) -> bool:
        mgr = self.get_manager(service_id)
        if not mgr:
            return False

        mgr.keys = [k for k in mgr.keys if k.key_id != key_id]
        async with async_session() as session:
            stmt = select(AccountKeyModel).where(AccountKeyModel.id == key_id)
            res = await session.execute(stmt)
            km = res.scalar_one_or_none()
            if km:
                await session.delete(km)
                await session.commit()
        return True

    def list_services(self) -> list[ServiceResponse]:
        return [mgr.to_response() for mgr in self._managers.values()]

    async def add_log(self, log_item: RequestLogItem) -> None:
        self._logs.append(log_item)
        if len(self._logs) > 200:
            self._logs.pop(0)

        async with async_session() as session:
            log_model = RequestLogModel(
                id=log_item.id,
                service_name=log_item.service_name,
                timestamp=log_item.timestamp,
                method=log_item.method,
                path=log_item.path,
                key_id=log_item.key_id,
                status_code=log_item.status_code,
                signal_kind=log_item.signal_kind,
                duration_ms=log_item.duration_ms,
                failover_chain=json.dumps(log_item.failover_chain),
            )
            session.add(log_model)
            await session.commit()

    def get_logs(self, limit: int = 50) -> list[RequestLogItem]:
        return list(reversed(self._logs[-limit:]))
