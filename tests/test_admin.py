import uuid

import httpx
import pytest

from mcp_pool.app import create_app, lifespan


@pytest.mark.asyncio
async def test_admin_api_endpoints() -> None:
    app = create_app()

    async with lifespan(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/admin/summary")
        assert res.status_code == 200

        res = await client.get("/api/admin/services")
        assert res.status_code == 200
        services = res.json()
        assert len(services) >= 1
        service_id = services[0]["id"]

        unique_name = f"brand-new-service-{uuid.uuid4().hex[:6]}"
        res = await client.post(
            "/api/admin/services",
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

        res = await client.post(
            f"/api/admin/services/{service_id}/keys",
            json={"name": "New Key", "secret_key": "sk-test-999"},
        )
        assert res.status_code == 200
        key_data = res.json()
        assert key_data["name"] == "New Key"
        assert key_data["key_masked"] == "sk-t...-999"
