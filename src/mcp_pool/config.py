from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_pool.domain.service import ServiceConfig


class Settings(BaseSettings):
    """Application settings loaded from MCP_POOL_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MCP_POOL_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./mcp_pool.db"
    secret_key: SecretStr = SecretStr("development-only-secret")
    initial_admin_username: str = "admin"
    initial_admin_password: SecretStr | None = None
    allow_anonymous_gateway: bool = False
    trust_proxy_headers: bool = False
    allow_private_upstreams: bool = False
    upstream_allowed_hosts: list[str] = Field(default_factory=list)
    max_request_body_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    request_log_retention_days: int = Field(default=30, ge=1, le=3650)
    session_affinity_ttl_seconds: int = Field(default=24 * 60 * 60, ge=60)
    session_affinity_max_entries: int = Field(default=10_000, ge=100)
    login_attempt_limit: int = Field(default=5, ge=1, le=100)
    login_attempt_window_seconds: int = Field(default=300, ge=10, le=86400)
    login_attempt_max_entries: int = Field(default=10_000, ge=100, le=1_000_000)

    # Generic MCP services configuration list
    services: list[ServiceConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.environment != "production":
            return self
        secret = self.secret_key.get_secret_value()
        if secret in {"development-only-secret", "replace-with-a-random-secret-before-production"}:
            raise ValueError("MCP_POOL_SECRET_KEY must be replaced in production")
        if len(secret) < 32:
            raise ValueError(
                "MCP_POOL_SECRET_KEY must contain at least 32 characters in production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
