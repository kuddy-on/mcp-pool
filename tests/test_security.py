from uuid import uuid4

import pytest
from sqlalchemy import select

from mcp_pool.crypto import HASHED_KEY_PREFIX
from mcp_pool.db import (
    AccountKeyModel,
    ClientApiKeyModel,
    ServiceModel,
    async_session,
)
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
