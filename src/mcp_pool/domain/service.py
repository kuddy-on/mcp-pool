import ipaddress
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


def normalize_upstream_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("upstream_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("upstream_url must not contain credentials")
    if parsed.fragment:
        raise ValueError("upstream_url must not contain a fragment")
    return value


def is_private_upstream(value: str) -> bool:
    hostname = (urlsplit(value).hostname or "").rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return not address.is_global


class ServiceConfig(BaseModel):
    """Configuration for an upstream MCP service."""

    name: str = Field(min_length=1, max_length=64)
    upstream_url: str = Field(min_length=8, max_length=2048)
    provider_type: str = "generic"  # e.g., "generic", "context7"
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    api_keys: list[str] = Field(default_factory=list)

    _normalize_url = field_validator("upstream_url")(normalize_upstream_url)
