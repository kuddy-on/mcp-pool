import asyncio
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from mcp_pool.config import get_settings
from mcp_pool.crypto import (
    HASHED_KEY_PREFIX,
    SecretCipher,
    client_api_key_hint,
    hash_client_api_key,
)
from mcp_pool.db import (
    AccountKeyModel,
    ClientApiKeyModel,
    RequestLogModel,
    ServiceModel,
    SystemSettingModel,
    UserModel,
    async_session,
)
from mcp_pool.domain.admin import KeyResponse, RequestLogItem, ServiceResponse
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.providers.base import ProviderAdapter, ProviderSignalKind
from mcp_pool.providers.context7 import Context7ProviderAdapter
from mcp_pool.providers.generic import GenericHeaderProviderAdapter

PROVIDER_QUOTA_MAX_CONCURRENCY = 5


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
    monthly_quota: int = 0  # 0 = unlimited
    used_offset: int = 0  # manual offset for external usage
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
        if len(self.secret_key) <= 8:
            return "****"
        return f"{self.secret_key[:4]}...{self.secret_key[-4:]}"

    def to_response(self, monthly_usage: Mapping[str, int] | None = None) -> KeyResponse:
        log_count = (monthly_usage or {}).get(self.key_id, 0)
        total_used = log_count + self.used_offset
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

    def __init__(self, service_id: str, service_config: ServiceConfig, owner_id: str | None = None):
        self.service_id = service_id
        self.service_name = service_config.name
        self.upstream_url = service_config.upstream_url.rstrip("/")
        self.provider_type = service_config.provider_type
        self.auth_header = service_config.auth_header
        self.auth_prefix = service_config.auth_prefix
        self.owner_id = owner_id
        self.provider_adapter = get_provider_adapter(service_config)

        self.keys: list[AccountKey] = [
            AccountKey(
                key_id=f"{service_config.name}-key-{i + 1}",
                name=f"Key-{i + 1}",
                secret_key=k,
            )
            for i, k in enumerate(service_config.api_keys)
        ]
        self._current_index: int = 0

    def add_key(
        self, secret_key: str, name: str | None = None, weight: float = 1.0, monthly_quota: int = 0
    ) -> AccountKey:
        kid = f"{self.service_name}-key-{len(self.keys) + 1}-{uuid4().hex[:4]}"
        kname = name or f"Key-{len(self.keys) + 1}"
        acc_key = AccountKey(
            key_id=kid,
            name=kname,
            secret_key=secret_key,
            weight=weight,
            monthly_quota=monthly_quota,
        )
        self.keys.append(acc_key)
        return acc_key

    def get_current_key(
        self,
        monthly_usage: Mapping[str, int] | None = None,
        excluded_key_ids: set[str] | None = None,
    ) -> AccountKey | None:
        if not self.keys:
            return None
        now = datetime.now(UTC)
        usage = monthly_usage or {}
        excluded = excluded_key_ids or set()
        for i in range(len(self.keys)):
            idx = (self._current_index + i) % len(self.keys)
            key = self.keys[idx]
            used_this_month = usage.get(key.key_id, 0) + key.used_offset
            if key.key_id not in excluded and key.is_available(now, used_this_month):
                self._current_index = (idx + 1) % len(self.keys)
                return key
        return None

    def mark_signal(
        self, key_id: str, kind: ProviderSignalKind, retry_at: datetime | None = None
    ) -> AccountKey | None:
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
                return key
        return None

    def get_service_status(self, monthly_usage: Mapping[str, int] | None = None) -> str:
        if not self.keys:
            return "unavailable"
        usage = monthly_usage or {}
        active_count = sum(
            1
            for key in self.keys
            if key.is_available(used_this_month=usage.get(key.key_id, 0) + key.used_offset)
        )
        if active_count == len(self.keys):
            return "active"
        if active_count > 0:
            return "degraded"
        return "unavailable"

    def to_response(self, monthly_usage: Mapping[str, int] | None = None) -> ServiceResponse:
        usage = monthly_usage or {}
        active_keys = sum(
            1
            for k in self.keys
            if k.is_available(used_this_month=usage.get(k.key_id, 0) + k.used_offset)
        )
        return ServiceResponse(
            id=self.service_id,
            name=self.service_name,
            upstream_url=self.upstream_url,
            provider_type=self.provider_type,
            auth_header=self.auth_header,
            auth_prefix=self.auth_prefix,
            total_keys=len(self.keys),
            active_keys=active_keys,
            status=self.get_service_status(usage),
            keys=[k.to_response(monthly_usage) for k in self.keys],
        )


class KeyPoolRegistry:
    """Registry holding KeyPoolManagers, Client API Keys, System Settings and SQLite DB Syncing."""

    def __init__(self, default_services: Sequence[ServiceConfig]):
        self._application_secret = get_settings().secret_key.get_secret_value()
        self._secret_cipher = SecretCipher(self._application_secret)
        self._managers: dict[str, KeyPoolManager] = {}
        self._default_services = default_services
        self._default_service_name: str | None = None
        self._logs: list[RequestLogItem] = []
        self.gateway_external_url: str = "http://localhost:8100"
        self._client_keys: dict[str, str] = {}  # HMAC digest -> display name
        self.provider_quota_refresh_semaphore = asyncio.Semaphore(PROVIDER_QUOTA_MAX_CONCURRENCY)
        self._provider_quota_refresh_claim_lock = asyncio.Lock()
        self._provider_quota_refresh_inflight: set[str] = set()
        self._provider_quota_refresh_last_started: dict[str, float] = {}
        self._provider_quota_state_locks: dict[str, asyncio.Lock] = {}

    def provider_quota_state_lock(self, key_id: str) -> asyncio.Lock:
        """Return the single-process lock protecting one key's quota state and persistence."""
        lock = self._provider_quota_state_locks.get(key_id)
        if lock is None:
            lock = asyncio.Lock()
            self._provider_quota_state_locks[key_id] = lock
        return lock

    async def claim_provider_quota_refresh(
        self,
        key_ids: Sequence[str],
        *,
        cooldown_seconds: float,
    ) -> tuple[str, int]:
        """Atomically reserve keys for one quota refresh request.

        Returns ``("acquired", 0)``, ``("in_progress", 0)``, or
        ``("cooldown", retry_after_seconds)``.
        """
        async with self._provider_quota_refresh_claim_lock:
            if any(key_id in self._provider_quota_refresh_inflight for key_id in key_ids):
                return "in_progress", 0

            now = time.monotonic()
            retry_after = max(
                (
                    cooldown_seconds
                    - (now - self._provider_quota_refresh_last_started.get(key_id, -math.inf))
                    for key_id in key_ids
                ),
                default=0.0,
            )
            if retry_after > 0:
                return "cooldown", max(1, math.ceil(retry_after))

            self._provider_quota_refresh_inflight.update(key_ids)
            for key_id in key_ids:
                self._provider_quota_refresh_last_started[key_id] = now
            return "acquired", 0

    async def release_provider_quota_refresh(self, key_ids: Sequence[str]) -> None:
        async with self._provider_quota_refresh_claim_lock:
            self._provider_quota_refresh_inflight.difference_update(key_ids)

    async def reset_provider_quota_refresh_cooldown(self, key_id: str) -> None:
        """Allow a newly replaced credential to be queried after old work finishes."""
        async with self._provider_quota_refresh_claim_lock:
            self._provider_quota_refresh_last_started.pop(key_id, None)

    async def initialize(self) -> None:
        """Load persistent records from SQLite DB or seed default admin user."""
        from mcp_pool.auth import hash_password

        async with async_session() as session:
            # Seed default admin user if no user exists
            stmt_usr = select(UserModel)
            res_usr = await session.execute(stmt_usr)
            users = res_usr.scalars().all()
            if not users:
                admin_usr = UserModel(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    role="admin",
                )
                session.add(admin_usr)
                await session.commit()
            # Load system settings
            stmt_set = select(SystemSettingModel)
            res_set = await session.execute(stmt_set)
            for setting in res_set.scalars().all():
                if setting.key == "gateway_external_url":
                    self.gateway_external_url = setting.value

            # Migrate legacy plaintext Gateway keys to HMAC digests and load active keys.
            stmt_ck = select(ClientApiKeyModel)
            res_ck = await session.execute(stmt_ck)
            client_keys_changed = False
            for ck in res_ck.scalars().all():
                if not ck.api_key.startswith(HASHED_KEY_PREFIX):
                    raw_key = ck.api_key
                    ck.api_key = hash_client_api_key(raw_key, self._application_secret)
                    ck.key_hint = client_api_key_hint(raw_key)
                    client_keys_changed = True
                if ck.is_active:
                    self._client_keys[ck.api_key] = ck.name
            if client_keys_changed:
                await session.commit()

            # Load historical request logs
            stmt_log = select(RequestLogModel).order_by(RequestLogModel.timestamp.desc()).limit(100)
            res_log = await session.execute(stmt_log)
            for lm in res_log.scalars().all():
                try:
                    f_chain = json.loads(lm.failover_chain) if lm.failover_chain else []
                except Exception:
                    f_chain = []
                self._logs.append(
                    RequestLogItem(
                        id=lm.id,
                        service_name=lm.service_name,
                        timestamp=lm.timestamp,
                        method=lm.method,
                        path=lm.path,
                        mcp_method=getattr(lm, "mcp_method", None),
                        key_id=getattr(lm, "key_id", None),
                        key_name=getattr(lm, "key_name", None),
                        client_key_name=getattr(lm, "client_key_name", None),
                        client_ip=getattr(lm, "client_ip", None),
                        status_code=lm.status_code,
                        signal_kind=lm.signal_kind,
                        duration_ms=lm.duration_ms,
                        failover_chain=f_chain,
                    )
                )
            self._logs.reverse()

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
                            secret_key=self._secret_cipher.encrypt(k.secret_key),
                            is_active=k.is_active,
                            weight=k.weight,
                        )
                        session.add(k_model)
                    self._managers[s.name] = mgr

                await session.commit()
                if self._default_services:
                    self._default_service_name = self._default_services[0].name
            else:
                credentials_changed = False
                for db_s in db_services:
                    cfg = ServiceConfig(
                        name=db_s.name,
                        upstream_url=db_s.upstream_url,
                        provider_type=db_s.provider_type,
                        auth_header=db_s.auth_header,
                        auth_prefix=db_s.auth_prefix,
                        api_keys=[],
                    )
                    mgr = KeyPoolManager(db_s.id, cfg, owner_id=db_s.owner_id)
                    mgr.keys = []
                    for key_model in db_s.keys:
                        plaintext, needs_encryption = self._secret_cipher.decrypt(
                            key_model.secret_key
                        )
                        if needs_encryption:
                            key_model.secret_key = self._secret_cipher.encrypt(plaintext)
                            credentials_changed = True
                        mgr.keys.append(
                            AccountKey(
                                key_id=key_model.id,
                                name=key_model.name,
                                secret_key=plaintext,
                                is_active=key_model.is_active,
                                quota_exhausted=key_model.quota_exhausted,
                                paused_until=key_model.paused_until,
                                weight=key_model.weight,
                                fail_count=key_model.fail_count,
                                requests_count=key_model.requests_count,
                                last_used=key_model.last_used,
                                monthly_quota=getattr(key_model, "monthly_quota", 0) or 0,
                                used_offset=getattr(key_model, "used_offset", 0) or 0,
                                provider_quota_snapshot=getattr(
                                    key_model, "provider_quota_snapshot", None
                                ),
                                provider_quota_error=getattr(
                                    key_model, "provider_quota_error", None
                                ),
                            )
                        )
                    self._managers[db_s.name] = mgr

                if credentials_changed:
                    await session.commit()
                if db_services:
                    self._default_service_name = db_services[0].name

    def get_manager(self, service_name: str | None = None) -> KeyPoolManager | None:
        if service_name is not None:
            if service_name in self._managers:
                return self._managers[service_name]
            for mgr in self._managers.values():
                if mgr.service_id == service_name:
                    return mgr
            return None
        if self._default_service_name and self._default_service_name in self._managers:
            return self._managers[self._default_service_name]
        return None

    def get_manager_by_name(self, name: str) -> KeyPoolManager | None:
        return self._managers.get(name)

    async def add_service(
        self, service_config: ServiceConfig, owner_id: str | None = None
    ) -> KeyPoolManager:
        async with async_session() as session:
            srv_model = ServiceModel(
                name=service_config.name,
                upstream_url=service_config.upstream_url,
                provider_type=service_config.provider_type,
                auth_header=service_config.auth_header,
                auth_prefix=service_config.auth_prefix,
                owner_id=owner_id,
            )
            session.add(srv_model)
            await session.flush()

            mgr = KeyPoolManager(srv_model.id, service_config, owner_id=owner_id)
            for k in mgr.keys:
                k_model = AccountKeyModel(
                    id=k.key_id,
                    service_id=srv_model.id,
                    name=k.name,
                    secret_key=self._secret_cipher.encrypt(k.secret_key),
                    is_active=k.is_active,
                    weight=k.weight,
                )
                session.add(k_model)

            await session.commit()

        self._managers[service_config.name] = mgr
        if not self._default_service_name:
            self._default_service_name = service_config.name
        return mgr

    async def update_service_in_db(self, manager: KeyPoolManager) -> None:
        async with async_session() as session:
            stmt = select(ServiceModel).where(ServiceModel.id == manager.service_id)
            result = await session.execute(stmt)
            service = result.scalar_one_or_none()
            if service:
                service.upstream_url = manager.upstream_url
                service.provider_type = manager.provider_type
                service.auth_header = manager.auth_header
                service.auth_prefix = manager.auth_prefix
                await session.commit()

        manager.provider_adapter = get_provider_adapter(
            ServiceConfig(
                name=manager.service_name,
                upstream_url=manager.upstream_url,
                provider_type=manager.provider_type,
                auth_header=manager.auth_header,
                auth_prefix=manager.auth_prefix,
            )
        )

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
        self,
        service_id: str,
        secret_key: str,
        name: str | None = None,
        weight: float = 1.0,
        monthly_quota: int = 0,
    ) -> AccountKey | None:
        mgr = self.get_manager(service_id)
        if not mgr:
            return None

        key = mgr.add_key(
            secret_key=secret_key, name=name, weight=weight, monthly_quota=monthly_quota
        )
        async with async_session() as session:
            k_model = AccountKeyModel(
                id=key.key_id,
                service_id=mgr.service_id,
                name=key.name,
                secret_key=self._secret_cipher.encrypt(key.secret_key),
                is_active=key.is_active,
                weight=key.weight,
                monthly_quota=key.monthly_quota,
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
                km.secret_key = self._secret_cipher.encrypt(account_key.secret_key)
                km.is_active = account_key.is_active
                km.quota_exhausted = account_key.quota_exhausted
                km.paused_until = account_key.paused_until
                km.weight = account_key.weight
                km.fail_count = account_key.fail_count
                km.requests_count = account_key.requests_count
                km.last_used = account_key.last_used
                km.monthly_quota = account_key.monthly_quota
                km.used_offset = account_key.used_offset
                km.provider_quota_snapshot = account_key.provider_quota_snapshot
                km.provider_quota_error = account_key.provider_quota_error
                await session.commit()

    async def update_provider_quota_states_in_db(
        self,
        account_keys: Sequence[AccountKey],
    ) -> None:
        """Persist provider quota metadata and its synchronized local usage offset."""
        if not account_keys:
            return
        states = {
            key.key_id: (
                key.provider_quota_snapshot,
                key.provider_quota_error,
                key.used_offset,
            )
            for key in account_keys
        }
        async with async_session() as session:
            stmt = select(AccountKeyModel).where(AccountKeyModel.id.in_(states))
            res = await session.execute(stmt)
            for key_model in res.scalars().all():
                snapshot, error, used_offset = states[key_model.id]
                key_model.provider_quota_snapshot = snapshot
                key_model.provider_quota_error = error
                key_model.used_offset = used_offset
            await session.commit()

    async def record_signal(
        self,
        manager: KeyPoolManager,
        key_id: str,
        kind: ProviderSignalKind,
        retry_at: datetime | None = None,
    ) -> AccountKey | None:
        key = manager.mark_signal(key_id, kind, retry_at)
        if key is not None:
            await self.update_key_in_db(key_id, key)
        return key

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

    async def get_monthly_usage(self) -> dict[str, int]:
        """Compute monthly request usage by stable account key ID."""
        now = datetime.now(UTC)
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)

        async with async_session() as session:
            stmt = (
                select(
                    RequestLogModel.key_id,
                    RequestLogModel.service_name,
                    RequestLogModel.key_name,
                    func.count(RequestLogModel.id),
                )
                .where(RequestLogModel.timestamp >= month_start)
                .group_by(
                    RequestLogModel.key_id,
                    RequestLogModel.service_name,
                    RequestLogModel.key_name,
                )
            )
            res = await session.execute(stmt)
            usage: dict[str, int] = {}
            for key_id, service_name, key_name, count in res.all():
                resolved_key_id = key_id
                if resolved_key_id is None and key_name:
                    manager = self._managers.get(service_name)
                    if manager:
                        legacy_key = next(
                            (key for key in manager.keys if key.name == key_name),
                            None,
                        )
                        resolved_key_id = legacy_key.key_id if legacy_key else None
                if resolved_key_id:
                    usage[resolved_key_id] = usage.get(resolved_key_id, 0) + count
            return usage

    async def list_services_async(
        self, user_id: str | None = None, is_admin: bool = False
    ) -> list[ServiceResponse]:
        monthly_usage = await self.get_monthly_usage()
        out: list[ServiceResponse] = []
        for mgr in self._managers.values():
            if is_admin or not mgr.owner_id or mgr.owner_id == user_id:
                out.append(mgr.to_response(monthly_usage))
        return out

    def list_services(
        self, user_id: str | None = None, is_admin: bool = False
    ) -> list[ServiceResponse]:
        out: list[ServiceResponse] = []
        for mgr in self._managers.values():
            if is_admin or not mgr.owner_id or mgr.owner_id == user_id:
                out.append(mgr.to_response())
        return out

    def visible_service_names(self, user_id: str, is_admin: bool) -> set[str] | None:
        if is_admin:
            return None
        return {
            manager.service_name
            for manager in self._managers.values()
            if manager.owner_id is None or manager.owner_id == user_id
        }

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
                mcp_method=log_item.mcp_method,
                key_id=log_item.key_id,
                key_name=log_item.key_name,
                client_key_name=log_item.client_key_name,
                client_ip=log_item.client_ip,
                status_code=log_item.status_code,
                signal_kind=log_item.signal_kind,
                duration_ms=log_item.duration_ms,
                failover_chain=json.dumps(log_item.failover_chain),
            )
            session.add(log_model)
            await session.commit()

    def get_logs(
        self,
        limit: int = 50,
        service_names: set[str] | None = None,
    ) -> list[RequestLogItem]:
        logs = self._logs
        if service_names is not None:
            logs = [log for log in logs if log.service_name in service_names]
        return list(reversed(logs[-limit:]))

    def validate_client_key(self, raw_token: str | None) -> str | None:
        """Validate client key and return the key name, or None if invalid.

        Returns empty string when no client keys are configured (open access).
        Returns the key name if valid. Returns None if invalid.
        """
        if not self._client_keys:
            return ""  # open access
        if not raw_token:
            return None
        clean_token = raw_token.replace("Bearer ", "").strip()
        key_hash = hash_client_api_key(clean_token, self._application_secret)
        return self._client_keys.get(key_hash)

    async def update_external_url(self, new_url: str) -> None:
        self.gateway_external_url = new_url.rstrip("/")
        async with async_session() as session:
            stmt = select(SystemSettingModel).where(
                SystemSettingModel.key == "gateway_external_url"
            )
            res = await session.execute(stmt)
            setting = res.scalar_one_or_none()
            if not setting:
                setting = SystemSettingModel(
                    key="gateway_external_url", value=self.gateway_external_url
                )
                session.add(setting)
            else:
                setting.value = self.gateway_external_url
            await session.commit()

    async def create_client_api_key(self, name: str) -> tuple[ClientApiKeyModel, str]:
        raw_key = f"mcp_live_{uuid4().hex}"
        key_hash = hash_client_api_key(raw_key, self._application_secret)
        async with async_session() as session:
            ck = ClientApiKeyModel(
                name=name,
                api_key=key_hash,
                key_hint=client_api_key_hint(raw_key),
            )
            session.add(ck)
            await session.commit()
            await session.refresh(ck)
            self._client_keys[key_hash] = name
            return ck, raw_key

    async def list_client_api_keys(self) -> Sequence[ClientApiKeyModel]:
        async with async_session() as session:
            stmt = select(ClientApiKeyModel)
            res = await session.execute(stmt)
            return res.scalars().all()

    async def delete_client_api_key(self, key_id: str) -> bool:
        async with async_session() as session:
            stmt = select(ClientApiKeyModel).where(ClientApiKeyModel.id == key_id)
            res = await session.execute(stmt)
            ck = res.scalar_one_or_none()
            if ck:
                self._client_keys.pop(ck.api_key, None)
                await session.delete(ck)
                await session.commit()
                return True
        return False
