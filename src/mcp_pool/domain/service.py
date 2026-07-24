from pydantic import BaseModel, Field


class ServiceConfig(BaseModel):
    """Configuration for an upstream MCP service."""

    name: str
    upstream_url: str
    provider_type: str = "generic"  # e.g., "generic", "context7"
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    api_keys: list[str] = Field(default_factory=list)
