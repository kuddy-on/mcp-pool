import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import select

from mcp_pool.admin_routes import get_registry
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
        forbidden_create = await client.post(
            "/api/admin/services",
            headers=user_headers,
            json={
                "name": "user-controlled-upstream",
                "upstream_url": "http://2130706433/mcp",
            },
        )
        assert forbidden_read.status_code == 403
        assert forbidden_write.status_code == 403
        assert forbidden_create.status_code == 403

        # 10. Exercise the remaining authenticated CRUD lifecycle.
        listed_users = await client.get("/api/admin/users", headers=auth_headers)
        assert listed_users.status_code == 200
        assert any(user["username"] == username for user in listed_users.json())

        duplicate_user = await client.post(
            "/api/admin/users",
            headers=auth_headers,
            json={"username": username, "password": "test-password", "role": "user"},
        )
        assert duplicate_user.status_code == 400

        current_admin_id = login_res.json()["user"]["id"]
        cannot_delete_self = await client.delete(
            f"/api/admin/users/{current_admin_id}",
            headers=auth_headers,
        )
        assert cannot_delete_self.status_code == 400

        settings = await client.patch(
            "/api/admin/settings",
            headers=auth_headers,
            json={"gateway_external_url": "https://gateway.example.com"},
        )
        assert settings.status_code == 200
        assert (await client.get("/api/admin/settings", headers=auth_headers)).json()[
            "gateway_external_url"
        ] == "https://gateway.example.com"

        updated_service = await client.patch(
            f"/api/admin/services/{service_id}",
            headers=auth_headers,
            json={
                "upstream_url": "https://api.example.com/mcp",
                "auth_header": "X-API-Key",
                "auth_prefix": "",
            },
        )
        assert updated_service.status_code == 200
        assert updated_service.json()["auth_header"] == "X-API-Key"

        updated_key = await client.patch(
            f"/api/admin/services/{service_id}/keys/{key_data['id']}",
            headers=auth_headers,
            json={"name": "Updated Key", "weight": 2, "monthly_quota": 100},
        )
        assert updated_key.status_code == 200
        assert updated_key.json()["name"] == "Updated Key"
        assert (
            await client.get(
                f"/api/admin/services/{service_id}/keys",
                headers=auth_headers,
            )
        ).status_code == 200

        assert (
            await client.get("/api/admin/requests?limit=10", headers=auth_headers)
        ).status_code == 200
        listed_gateway_keys = await client.get("/api/admin/client-keys", headers=auth_headers)
        assert listed_gateway_keys.status_code == 200
        assert any(item["id"] == gateway_res.json()["id"] for item in listed_gateway_keys.json())

        deleted_gateway_key = await client.delete(
            f"/api/admin/client-keys/{gateway_res.json()['id']}",
            headers=auth_headers,
        )
        assert deleted_gateway_key.status_code == 200
        assert (
            await client.delete(
                f"/api/admin/client-keys/{uuid.uuid4()}",
                headers=auth_headers,
            )
        ).status_code == 404

        assert (
            await client.delete(
                f"/api/admin/services/{service_id}/keys/{key_data['id']}",
                headers=auth_headers,
            )
        ).status_code == 200
        assert (
            await client.delete(
                f"/api/admin/services/{service_id}",
                headers=auth_headers,
            )
        ).status_code == 200
        assert (
            await client.delete(
                f"/api/admin/users/{create_user_res.json()['id']}",
                headers=auth_headers,
            )
        ).status_code == 200
        assert (
            await client.delete(
                f"/api/admin/users/{uuid.uuid4()}",
                headers=auth_headers,
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_concurrent_key_updates_are_serialized_and_failed_commit_is_not_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        login = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        service = (
            await client.post(
                "/api/admin/services",
                headers=headers,
                json={
                    "name": f"concurrent-{uuid.uuid4().hex[:8]}",
                    "upstream_url": "https://api.test.com/mcp",
                    "provider_type": "generic",
                },
            )
        ).json()
        key = (
            await client.post(
                f"/api/admin/services/{service['id']}/keys",
                headers=headers,
                json={"name": "Initial", "secret_key": "sk-concurrent-test"},
            )
        ).json()
        name_update, weight_update = await asyncio.gather(
            client.patch(
                f"/api/admin/services/{service['id']}/keys/{key['id']}",
                headers=headers,
                json={"name": "Serialized"},
            ),
            client.patch(
                f"/api/admin/services/{service['id']}/keys/{key['id']}",
                headers=headers,
                json={"weight": 3},
            ),
        )
        assert name_update.status_code == 200
        assert weight_update.status_code == 200

        registry = get_registry()
        manager = registry.get_manager(service["id"])
        assert manager is not None
        current = next(item for item in manager.keys if item.key_id == key["id"])
        assert current.name == "Serialized"
        assert current.weight == 3
        async with async_session() as session:
            stored = (
                await session.execute(
                    select(AccountKeyModel).where(AccountKeyModel.id == key["id"])
                )
            ).scalar_one()
            assert stored.name == current.name
            assert stored.weight == current.weight

        async def fail_update(_key_id: str, _account_key: object) -> bool:
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(registry, "update_key_in_db", fail_update)
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            await client.patch(
                f"/api/admin/services/{service['id']}/keys/{key['id']}",
                headers=headers,
                json={"name": "Must not publish"},
            )
        unchanged = next(item for item in manager.keys if item.key_id == key["id"])
        assert unchanged is current
        assert unchanged.name == "Serialized"
