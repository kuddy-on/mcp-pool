import asyncio
import json
import logging
import math
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select
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
from mcp_pool.domain.admin import RequestLogItem, ServiceResponse
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.key_pool import AccountKey as AccountKey
from mcp_pool.key_pool import KeyPoolManager as KeyPoolManager
from mcp_pool.key_pool import get_provider_adapter
from mcp_pool.providers.base import ProviderSignalKind

PROVIDER_QUOTA_MAX_CONCURRENCY = 5
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionBinding:
    service_id: str
    key_id: str
    last_seen: float


class KeyPoolRegistry:
    """Registry holding KeyPoolManagers, Client API Keys, System Settings and SQLite DB Syncing."""

    def __init__(self, default_services: Sequence[ServiceConfig]):
        self._settings = get_settings()
        self._application_secret = self._settings.secret_key.get_secret_value()
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
        self._session_bindings: OrderedDict[tuple[str, str], SessionBinding] = OrderedDict()
        self._session_bindings_lock = asyncio.Lock()
        self._quota_reservations: dict[str, int] = {}
        self._quota_reservations_lock = asyncio.Lock()
        self._monthly_usage_cache: dict[str, int] = {}
        self._monthly_usage_month: tuple[int, int] | None = None
        self._monthly_usage_lock = asyncio.Lock()
        self._last_log_prune_at = 0.0

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

        await self.prune_request_logs()
        self._last_log_prune_at = time.monotonic()
        async with async_session() as session:
            # Seed default admin user if no user exists
            stmt_usr = select(UserModel)
            res_usr = await session.execute(stmt_usr)
            users = res_usr.scalars().all()
            if not users:
                configured_password = self._settings.initial_admin_password
                if configured_password is None and self._settings.environment != "test":
                    raise RuntimeError(
                        "MCP_POOL_INITIAL_ADMIN_PASSWORD is required for first startup"
                    )
                initial_password = (
                    configured_password.get_secret_value()
                    if configured_password is not None
                    else "admin123"
                )
                admin_usr = UserModel(
                    username=self._settings.initial_admin_username,
                    password_hash=hash_password(initial_password),
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
        await self.get_monthly_usage()

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

    async def update_service(
        self,
        manager: KeyPoolManager,
        *,
        upstream_url: str | None = None,
        provider_type: str | None = None,
        auth_header: str | None = None,
        auth_prefix: str | None = None,
    ) -> KeyPoolManager:
        """Commit service changes before publishing them to the live registry."""
        next_upstream_url = (upstream_url or manager.upstream_url).rstrip("/")
        next_provider_type = provider_type or manager.provider_type
        next_auth_header = auth_header or manager.auth_header
        next_auth_prefix = auth_prefix if auth_prefix is not None else manager.auth_prefix
        next_config = ServiceConfig(
            name=manager.service_name,
            upstream_url=next_upstream_url,
            provider_type=next_provider_type,
            auth_header=next_auth_header,
            auth_prefix=next_auth_prefix,
        )
        async with async_session() as session:
            stmt = select(ServiceModel).where(ServiceModel.id == manager.service_id)
            result = await session.execute(stmt)
            service = result.scalar_one_or_none()
            if service:
                service.upstream_url = next_upstream_url
                service.provider_type = next_provider_type
                service.auth_header = next_auth_header
                service.auth_prefix = next_auth_prefix
                await session.commit()
            else:
                raise LookupError("Service not found")

        manager.upstream_url = next_upstream_url
        manager.provider_type = next_provider_type
        manager.auth_header = next_auth_header
        manager.auth_prefix = next_auth_prefix
        manager.provider_adapter = get_provider_adapter(next_config)
        return manager

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

        key = AccountKey(
            key_id=str(uuid4()),
            name=name or f"Key {len(mgr.keys) + 1}",
            secret_key=secret_key,
            weight=weight,
            monthly_quota=monthly_quota,
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

        mgr.keys.append(key)
        return key

    async def update_key_in_db(self, key_id: str, account_key: AccountKey) -> bool:
        async with async_session() as session:
            stmt = select(AccountKeyModel).where(AccountKeyModel.id == key_id)
            res = await session.execute(stmt)
            km = res.scalar_one_or_none()
            if not km:
                return False
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
            return True

    async def update_key_runtime_state(self, key_id: str, account_key: AccountKey) -> None:
        """Persist hot-path state without rewriting or re-encrypting the credential."""
        async with async_session() as session:
            stmt = select(AccountKeyModel).where(AccountKeyModel.id == key_id)
            res = await session.execute(stmt)
            key_model = res.scalar_one_or_none()
            if key_model:
                key_model.is_active = account_key.is_active
                key_model.quota_exhausted = account_key.quota_exhausted
                key_model.paused_until = account_key.paused_until
                key_model.fail_count = account_key.fail_count
                key_model.requests_count = account_key.requests_count
                key_model.last_used = account_key.last_used
                key_model.used_offset = account_key.used_offset
                key_model.provider_quota_snapshot = account_key.provider_quota_snapshot
                key_model.provider_quota_error = account_key.provider_quota_error
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
            try:
                await self.update_key_runtime_state(key_id, key)
            except Exception:
                logger.exception("Failed to persist upstream key state", extra={"key_id": key_id})
        return key

    async def delete_key_from_db(self, service_id: str, key_id: str) -> bool:
        mgr = self.get_manager(service_id)
        if not mgr:
            return False

        async with async_session() as session:
            stmt = select(AccountKeyModel).where(AccountKeyModel.id == key_id)
            res = await session.execute(stmt)
            km = res.scalar_one_or_none()
            if km:
                await session.delete(km)
                await session.commit()
            else:
                return False
        mgr.keys = [k for k in mgr.keys if k.key_id != key_id]
        return True

    async def _load_monthly_usage(self) -> dict[str, int]:
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

    async def get_monthly_usage(self) -> dict[str, int]:
        """Return the in-process monthly ledger, loading SQLite once per month."""
        now = datetime.now(UTC)
        current_month = (now.year, now.month)
        async with self._monthly_usage_lock:
            if self._monthly_usage_month != current_month:
                self._monthly_usage_cache = await self._load_monthly_usage()
                self._monthly_usage_month = current_month
            return dict(self._monthly_usage_cache)

    async def reserve_key(
        self,
        manager: KeyPoolManager,
        excluded_key_ids: set[str],
        *,
        preferred_key_id: str | None = None,
    ) -> AccountKey | None:
        """Select and reserve quota atomically within this single-node process."""
        async with self._quota_reservations_lock:
            effective_usage = await self.get_monthly_usage()
            for key_id, count in self._quota_reservations.items():
                effective_usage[key_id] = effective_usage.get(key_id, 0) + count
            key = manager.get_current_key(
                effective_usage,
                excluded_key_ids,
                preferred_key_id=preferred_key_id,
            )
            if key is not None:
                self._quota_reservations[key.key_id] = (
                    self._quota_reservations.get(key.key_id, 0) + 1
                )
            return key

    async def release_key_reservation(self, key_id: str) -> None:
        async with self._quota_reservations_lock:
            count = self._quota_reservations.get(key_id, 0)
            if count <= 1:
                self._quota_reservations.pop(key_id, None)
            else:
                self._quota_reservations[key_id] = count - 1

    async def get_session_key_id(self, session_id: str, service_id: str) -> str | None:
        """Resolve a live MCP session to its original upstream key."""
        now = time.monotonic()
        ttl = self._settings.session_affinity_ttl_seconds
        binding_key = (service_id, session_id)
        async with self._session_bindings_lock:
            binding = self._session_bindings.get(binding_key)
            if binding is None:
                return None
            if now - binding.last_seen > ttl:
                self._session_bindings.pop(binding_key, None)
                return None
            binding.last_seen = now
            self._session_bindings.move_to_end(binding_key)
            return binding.key_id

    async def bind_session(self, session_id: str, service_id: str, key_id: str) -> None:
        now = time.monotonic()
        binding_key = (service_id, session_id)
        async with self._session_bindings_lock:
            if (
                binding_key not in self._session_bindings
                and len(self._session_bindings) >= self._settings.session_affinity_max_entries
            ):
                self._session_bindings.popitem(last=False)
            self._session_bindings[binding_key] = SessionBinding(
                service_id=service_id,
                key_id=key_id,
                last_seen=now,
            )
            self._session_bindings.move_to_end(binding_key)

    async def unbind_session(self, session_id: str, service_id: str) -> None:
        async with self._session_bindings_lock:
            self._session_bindings.pop((service_id, session_id), None)

    async def prune_request_logs(self) -> int:
        """Delete audit rows older than the configured retention window."""
        now = datetime.now(UTC)
        retention_cutoff = now - timedelta(days=self._settings.request_log_retention_days)
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        # Request logs currently back the durable monthly quota ledger. Preserve the
        # whole current month even when the configured audit retention is shorter.
        cutoff = min(retention_cutoff, month_start)
        async with async_session() as session:
            result = await session.execute(
                delete(RequestLogModel).where(RequestLogModel.timestamp < cutoff)
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0) or 0)

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

        try:
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
        except Exception:
            logger.exception(
                "Failed to persist request audit log",
                extra={"request_id": log_item.id},
            )
        if log_item.key_id is not None:
            timestamp = log_item.timestamp
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            current_month = (now.year, now.month)
            if (timestamp.year, timestamp.month) == current_month:
                async with self._monthly_usage_lock:
                    if self._monthly_usage_month == current_month:
                        self._monthly_usage_cache[log_item.key_id] = (
                            self._monthly_usage_cache.get(log_item.key_id, 0) + 1
                        )
        if time.monotonic() - self._last_log_prune_at >= 24 * 60 * 60:
            self._last_log_prune_at = time.monotonic()
            try:
                await self.prune_request_logs()
            except Exception:
                logger.exception("Failed to prune expired request audit logs")

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

        Returns empty string only when anonymous gateway access is explicitly enabled.
        Returns the key name if valid. Returns None if invalid.
        """
        if not self._client_keys:
            return "" if self._settings.allow_anonymous_gateway else None
        if not raw_token:
            return None
        clean_token = raw_token.replace("Bearer ", "").strip()
        key_hash = hash_client_api_key(clean_token, self._application_secret)
        return self._client_keys.get(key_hash)

    async def update_external_url(self, new_url: str) -> None:
        normalized_url = new_url.rstrip("/")
        async with async_session() as session:
            stmt = select(SystemSettingModel).where(
                SystemSettingModel.key == "gateway_external_url"
            )
            res = await session.execute(stmt)
            setting = res.scalar_one_or_none()
            if not setting:
                setting = SystemSettingModel(key="gateway_external_url", value=normalized_url)
                session.add(setting)
            else:
                setting.value = normalized_url
            await session.commit()
        self.gateway_external_url = normalized_url

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
                key_hash = ck.api_key
                await session.delete(ck)
                await session.commit()
                self._client_keys.pop(key_hash, None)
                return True
        return False
