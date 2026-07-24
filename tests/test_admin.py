import httpx
import pytest

from mcp_pool.app import create_app, lifespan


@pytest.mark.asyncio
async def test_admin_api_endpoints() -> None:
    app = create_app()

    async with lifespan(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Summary
        res = await client.get("/api/admin/summary")
        assert res.status_code == 200
        data = res.json()
        assert data["total_services"] == 1

        # 2. List services
        res = await client.get("/api/admin/services")
        assert res.status_code == 200
        services = res.json()
        assert len(services) == 1
        service_id = services[0]["id"]

        # 3. Add new service
        res = await client.post(
            "/api/admin/services",
            json={
                "name": "brand-new-service",
                "upstream_url": "https://api.test.com/mcp",
                "provider_type": "generic",
                "api_keys": ["sk-123"],
            },
        )
        assert res.status_code == 200
        new_service = res.json()
        assert new_service["name"] == "brand-new-service"

        # 4. Add Key
        res = await client.post(
            f"/api/admin/services/{service_id}/keys",
            json={"name": "New Key", "secret_key": "sk-test-999"},
        )
        assert res.status_code == 200
        key_data = res.json()
        assert key_data["name"] == "New Key"
        assert key_data["key_masked"] == "sk-t...-999"
