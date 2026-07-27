import uuid

import httpx
import pytest
from sqlalchemy import select

from mcp_pool.app import create_app, lifespan
from mcp_pool.crypto import HASHED_KEY_PREFIX
from mcp_pool.db import AccountKeyModel, ClientApiKeyModel, async_session


@pytest.mark.asyncio
async def test_admin_api_endpoints() -> None:
    app = create_app()

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        # 1. Login as default admin
        login_res = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_res.status_code == 200
        token = login_res.json()["token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # 2. Get Summary
        res = await client.get("/api/admin/summary", headers=auth_headers)
        assert res.status_code == 200

        # 3. List Services
        res = await client.get("/api/admin/services", headers=auth_headers)
        assert res.status_code == 200

        # 4. Add Service
        unique_name = f"brand-new-service-{uuid.uuid4().hex[:6]}"
        res = await client.post(
            "/api/admin/services",
            headers=auth_headers,
            json={
                "name": unique_name,
                "upstream_url": "https://api.test.com/mcp",
                "provider_type": "generic",
                "api_keys": ["sk-123"],
            },
        )
        assert res.status_code == 200
        new_service = res.json()
        assert new_service["name"] == unique_name
        service_id = new_service["id"]

        # 5. Add Key
        res = await client.post(
            f"/api/admin/services/{service_id}/keys",
            headers=auth_headers,
            json={"name": "New Key", "secret_key": "sk-test-999"},
        )
        assert res.status_code == 200
        key_data = res.json()
        assert key_data["name"] == "New Key"
        assert key_data["key_masked"] == "sk-t...-999"

        # 6. Every admin route, including item routes, requires authentication.
        unauthenticated = await client.patch(
            f"/api/admin/services/{service_id}",
            json={"upstream_url": "https://attacker.invalid/mcp"},
        )
        assert unauthenticated.status_code == 401

        missing_service = await client.get(
            f"/api/admin/services/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert missing_service.status_code == 404

        # 7. Upstream credentials are encrypted in SQLite.
        async with async_session() as session:
            result = await session.execute(
                select(AccountKeyModel).where(AccountKeyModel.id == key_data["id"])
            )
            stored_upstream_key = result.scalar_one()
            assert stored_upstream_key.secret_key.startswith("enc:v1:")
            assert stored_upstream_key.secret_key != "sk-test-999"

        # 8. Gateway keys are returned once and persisted only as HMAC digests.
        gateway_res = await client.post(
            "/api/admin/client-keys",
            headers=auth_headers,
            json={"name": f"admin-test-{uuid.uuid4().hex[:6]}"},
        )
        assert gateway_res.status_code == 200
        raw_gateway_key = gateway_res.json()["api_key"]

        async with async_session() as session:
            gateway_key_result = await session.execute(
                select(ClientApiKeyModel).where(ClientApiKeyModel.id == gateway_res.json()["id"])
            )
            stored_gateway_key = gateway_key_result.scalar_one()
            assert stored_gateway_key.api_key.startswith(HASHED_KEY_PREFIX)
            assert stored_gateway_key.api_key != raw_gateway_key

        # 9. A regular user cannot read or mutate another user's service.
        username = f"user-{uuid.uuid4().hex[:8]}"
        create_user_res = await client.post(
            "/api/admin/users",
            headers=auth_headers,
            json={"username": username, "password": "test-password", "role": "user"},
        )
        assert create_user_res.status_code == 200
        user_login_res = await client.post(
            "/api/auth/login",
            json={"username": username, "password": "test-password"},
        )
        user_headers = {"Authorization": f"Bearer {user_login_res.json()['token']}"}

        forbidden_read = await client.get(
            f"/api/admin/services/{service_id}",
            headers=user_headers,
        )
        forbidden_write = await client.patch(
            f"/api/admin/services/{service_id}",
            headers=user_headers,
            json={"upstream_url": "https://forbidden.invalid/mcp"},
        )
        assert forbidden_read.status_code == 403
        assert forbidden_write.status_code == 403
