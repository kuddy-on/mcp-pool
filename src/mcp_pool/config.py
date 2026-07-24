from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_url: str = "postgresql+asyncpg://mcp_pool:mcp_pool@127.0.0.1:5432/mcp_pool"
    redis_url: str = "redis://127.0.0.1:6379/0"
    secret_key: SecretStr = SecretStr("development-only-secret")


@lru_cache
def get_settings() -> Settings:
    return Settings()
