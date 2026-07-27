from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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

    service: Mapped[ServiceModel] = relationship("ServiceModel", back_populates="keys")


class RequestLogModel(Base):
    __tablename__ = "request_logs"

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


async def init_db() -> None:
    import contextlib

    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Dynamic migration for SQLite columns if missing
        migrations = [
            "ALTER TABLE mcp_services ADD COLUMN owner_id VARCHAR(36)",
            "ALTER TABLE request_logs ADD COLUMN key_name VARCHAR(64)",
            "ALTER TABLE request_logs ADD COLUMN client_key_name VARCHAR(64)",
            "ALTER TABLE request_logs ADD COLUMN client_ip VARCHAR(64)",
            "ALTER TABLE account_keys ADD COLUMN monthly_quota INTEGER DEFAULT 0",
            "ALTER TABLE account_keys ADD COLUMN used_offset INTEGER DEFAULT 0",
            "ALTER TABLE request_logs ADD COLUMN mcp_method VARCHAR(128)",
            "ALTER TABLE request_logs ADD COLUMN key_id VARCHAR(64)",
            "ALTER TABLE client_api_keys ADD COLUMN key_hint VARCHAR(32) DEFAULT ''",
        ]
        for stmt in migrations:
            with contextlib.suppress(Exception):
                await conn.execute(text(stmt))


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
