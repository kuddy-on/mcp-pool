from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from mcp_pool.auth import hash_password, verify_password
from mcp_pool.config import Settings
from mcp_pool.crypto import HASHED_KEY_PREFIX
from mcp_pool.db import (
    AccountKeyModel,
    ClientApiKeyModel,
    ServiceModel,
    async_session,
)
from mcp_pool.domain.service import ServiceConfig, is_private_upstream
from mcp_pool.pool import KeyPoolRegistry


@pytest.mark.asyncio
async def test_registry_migrates_legacy_plaintext_secrets() -> None:
    suffix = uuid4().hex[:8]
    service_name = f"legacy-service-{suffix}"
    upstream_secret = f"legacy-upstream-{suffix}"
    gateway_secret = f"mcp_live_legacy_{suffix}"
    key_id = f"legacy-key-{suffix}"
    client_key_id = str(uuid4())

    async with async_session() as session:
        service = ServiceModel(
            name=service_name,
            upstream_url="https://api.example.com/mcp",
            provider_type="generic",
        )
        session.add(service)
        await session.flush()
        session.add(
            AccountKeyModel(
                id=key_id,
                service_id=service.id,
                name="Legacy key",
                secret_key=upstream_secret,
            )
        )
        session.add(
            ClientApiKeyModel(
                id=client_key_id,
                name="Legacy client",
                api_key=gateway_secret,
            )
        )
        await session.commit()

    registry = KeyPoolRegistry([])
    await registry.initialize()

    async with async_session() as session:
        account_result = await session.execute(
            select(AccountKeyModel).where(AccountKeyModel.id == key_id)
        )
        client_result = await session.execute(
            select(ClientApiKeyModel).where(ClientApiKeyModel.id == client_key_id)
        )
        stored_account = account_result.scalar_one()
        stored_client = client_result.scalar_one()

    assert stored_account.secret_key.startswith("enc:v1:")
    assert stored_account.secret_key != upstream_secret
    assert stored_client.api_key.startswith(HASHED_KEY_PREFIX)
    assert stored_client.api_key != gateway_secret
    assert registry.validate_client_key(f"Bearer {gateway_secret}") == "Legacy client"


def test_password_hashes_are_salted_and_memory_hard() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first.startswith("scrypt$")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_production_rejects_default_or_short_application_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="development-only-secret")
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="too-short")

    settings = Settings(environment="production", secret_key="x" * 32)
    assert settings.environment == "production"


def test_gateway_is_closed_when_no_client_keys_exist() -> None:
    registry = KeyPoolRegistry([])

    assert registry.validate_client_key(None) is None
    assert registry.validate_client_key("Bearer unknown") is None


def test_upstream_urls_reject_unsafe_syntax_and_private_literals() -> None:
    with pytest.raises(ValidationError):
        ServiceConfig(name="bad", upstream_url="file:///etc/passwd")
    with pytest.raises(ValidationError):
        ServiceConfig(name="bad", upstream_url="https://user:pass@example.com/mcp")

    assert is_private_upstream("http://127.0.0.1:8000/mcp")
    assert is_private_upstream("http://[::1]/mcp")
    assert not is_private_upstream("https://api.example.com/mcp")
