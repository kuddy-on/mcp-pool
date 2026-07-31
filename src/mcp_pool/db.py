from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from mcp_pool.config import get_settings


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="user")  # "admin" or "user"
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    services: Mapped[list["ServiceModel"]] = relationship("ServiceModel", back_populates="owner")


class ServiceModel(Base):
    __tablename__ = "mcp_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    upstream_url: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), default="generic")
    auth_header: Mapped[str] = mapped_column(String(64), default="Authorization")
    auth_prefix: Mapped[str] = mapped_column(String(32), default="Bearer ")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    owner: Mapped[UserModel | None] = relationship("UserModel", back_populates="services")
    keys: Mapped[list["AccountKeyModel"]] = relationship(
        "AccountKeyModel", back_populates="service", cascade="all, delete-orphan"
    )


class AccountKeyModel(Base):
    __tablename__ = "account_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("mcp_services.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_key: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    quota_exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    requests_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    monthly_quota: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    used_offset: Mapped[int] = mapped_column(Integer, default=0)  # manual offset
    provider_quota_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_quota_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    service: Mapped[ServiceModel] = relationship("ServiceModel", back_populates="keys")


class RequestLogModel(Base):
    __tablename__ = "request_logs"
    __table_args__ = (Index("ix_request_logs_timestamp_key_id", "timestamp", "key_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    service_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    mcp_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    key_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_key_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    failover_chain: Mapped[str] = mapped_column(Text, default="")  # JSON or comma-separated string


class SystemSettingModel(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class ClientApiKeyModel(Base):
    __tablename__ = "client_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Stores an HMAC digest, never the recoverable Gateway API key.
    api_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(32), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


def _configure_sqlite_connection(
    dbapi_connection: Any,  # noqa: ANN401 - SQLAlchemy supplies a driver-specific connection
    _connection_record: Any,  # noqa: ANN401 - SQLAlchemy event protocol
) -> None:
    """Apply connection-local SQLite safety and contention settings."""
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)

SCHEMA_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            "ALTER TABLE mcp_services ADD COLUMN owner_id VARCHAR(36)",
            "ALTER TABLE request_logs ADD COLUMN key_name VARCHAR(64)",
            "ALTER TABLE request_logs ADD COLUMN client_key_name VARCHAR(64)",
            "ALTER TABLE request_logs ADD COLUMN client_ip VARCHAR(64)",
            "ALTER TABLE account_keys ADD COLUMN monthly_quota INTEGER DEFAULT 0",
            "ALTER TABLE account_keys ADD COLUMN used_offset INTEGER DEFAULT 0",
            "ALTER TABLE account_keys ADD COLUMN provider_quota_snapshot TEXT",
            "ALTER TABLE account_keys ADD COLUMN provider_quota_error TEXT",
            "ALTER TABLE request_logs ADD COLUMN mcp_method VARCHAR(128)",
            "ALTER TABLE request_logs ADD COLUMN key_id VARCHAR(64)",
            "ALTER TABLE client_api_keys ADD COLUMN key_hint VARCHAR(32) DEFAULT ''",
            "ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0",
        ),
    ),
    (
        2,
        (
            "CREATE INDEX IF NOT EXISTS ix_request_logs_timestamp_key_id "
            "ON request_logs (timestamp, key_id)",
        ),
    ),
)


async def init_db() -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        result = await conn.execute(text("SELECT COALESCE(MAX(version), 0) FROM schema_migrations"))
        current_version = int(result.scalar_one())
        await conn.run_sync(Base.metadata.create_all)
        for version, statements in SCHEMA_MIGRATIONS:
            if version <= current_version:
                continue
            for statement in statements:
                try:
                    await conn.execute(text(statement))
                except OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            await conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": version},
            )


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
