import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from mcp_pool.domain.admin import (
    KeyCreateRequest,
    KeyResponse,
    KeyUpdateRequest,
    RequestLogItem,
    ServiceCreateRequest,
    ServiceResponse,
    ServiceUpdateRequest,
    TestResultItem,
)
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.pool import KeyPoolRegistry
from mcp_pool.providers.base import ProviderSignalKind

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Global reference injected in app lifecycle
registry: KeyPoolRegistry | None = None


def get_registry() -> KeyPoolRegistry:
    if registry is None:
        raise HTTPException(status_code=503, detail="Registry not initialized")
    return registry


@router.get("/summary")
async def get_summary() -> dict[str, Any]:
    reg = get_registry()
    services = reg.list_services()
    total_services = len(services)
    total_keys = sum(s.total_keys for s in services)
    active_keys = sum(s.active_keys for s in services)

    return {
        "total_services": total_services,
        "total_keys": total_keys,
        "active_keys": active_keys,
        "status": "healthy" if active_keys > 0 or total_keys == 0 else "degraded",
    }


@router.get("/services", response_model=list[ServiceResponse])
async def list_services() -> list[ServiceResponse]:
    return get_registry().list_services()


@router.post("/services", response_model=ServiceResponse)
async def create_service(req: ServiceCreateRequest) -> ServiceResponse:
    reg = get_registry()
    if reg.get_manager_by_name(req.name):
        raise HTTPException(status_code=400, detail=f"Service '{req.name}' already exists")

    cfg = ServiceConfig(
        name=req.name,
        upstream_url=req.upstream_url,
        provider_type=req.provider_type,
        auth_header=req.auth_header,
        auth_prefix=req.auth_prefix,
        api_keys=req.api_keys,
    )
    mgr = await reg.add_service(cfg)
    return mgr.to_response()


@router.get("/services/{service_id}", response_model=ServiceResponse)
async def get_service(service_id: str) -> ServiceResponse:
    mgr = get_registry().get_manager(service_id)
    if not mgr:
        raise HTTPException(status_code=404, detail="Service not found")
    return mgr.to_response()


@router.patch("/services/{service_id}", response_model=ServiceResponse)
async def update_service(service_id: str, req: ServiceUpdateRequest) -> ServiceResponse:
    mgr = get_registry().get_manager(service_id)
    if not mgr:
        raise HTTPException(status_code=404, detail="Service not found")

    if req.upstream_url is not None:
        mgr.upstream_url = req.upstream_url.rstrip("/")
    if req.provider_type is not None:
        mgr.provider_type = req.provider_type
    if req.auth_header is not None:
        mgr.auth_header = req.auth_header
    if req.auth_prefix is not None:
        mgr.auth_prefix = req.auth_prefix

    return mgr.to_response()


@router.delete("/services/{service_id}")
async def delete_service(service_id: str) -> dict[str, str]:
    if await get_registry().remove_service(service_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Service not found")


@router.get("/services/{service_id}/keys", response_model=list[KeyResponse])
async def list_keys(service_id: str) -> list[KeyResponse]:
    mgr = get_registry().get_manager(service_id)
    if not mgr:
        raise HTTPException(status_code=404, detail="Service not found")
    return [k.to_response() for k in mgr.keys]


@router.post("/services/{service_id}/keys", response_model=KeyResponse)
async def add_key(service_id: str, req: KeyCreateRequest) -> KeyResponse:
    reg = get_registry()
    key = await reg.add_key_to_service(
        service_id=service_id, secret_key=req.secret_key, name=req.name, weight=req.weight
    )
    if not key:
        raise HTTPException(status_code=404, detail="Service not found")
    return key.to_response()


@router.patch("/services/{service_id}/keys/{key_id}", response_model=KeyResponse)
async def update_key(service_id: str, key_id: str, req: KeyUpdateRequest) -> KeyResponse:
    reg = get_registry()
    mgr = reg.get_manager(service_id)
    if not mgr:
        raise HTTPException(status_code=404, detail="Service not found")

    target_key = next((k for k in mgr.keys if k.key_id == key_id), None)
    if not target_key:
        raise HTTPException(status_code=404, detail="Key not found")

    if req.name is not None:
        target_key.name = req.name
    if req.secret_key is not None:
        target_key.secret_key = req.secret_key
    if req.weight is not None:
        target_key.weight = req.weight
    if req.is_active is not None:
        target_key.is_active = req.is_active
        if req.is_active:
            target_key.quota_exhausted = False

    await reg.update_key_in_db(key_id, target_key)
    return target_key.to_response()


@router.delete("/services/{service_id}/keys/{key_id}")
async def delete_key(service_id: str, key_id: str) -> dict[str, str]:
    if await get_registry().delete_key_from_db(service_id, key_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Service or Key not found")


@router.post("/services/{service_id}/test", response_model=list[TestResultItem])
async def test_service(service_id: str) -> list[TestResultItem]:
    mgr = get_registry().get_manager(service_id)
    if not mgr:
        raise HTTPException(status_code=404, detail="Service not found")

    results: list[TestResultItem] = []

    # 1. HTTP Endpoint connectivity check
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.options(mgr.upstream_url)
            duration = (time.perf_counter() - start) * 1000
            results.append(
                TestResultItem(
                    step="Upstream HTTP OPTIONS",
                    success=resp.status_code < 500,
                    message=f"HTTP Status {resp.status_code}",
                    duration_ms=round(duration, 2),
                )
            )
    except Exception as exc:
        results.append(
            TestResultItem(
                step="Upstream HTTP OPTIONS",
                success=False,
                message=str(exc),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        )

    # 2. Key Availability check
    active_count = sum(1 for k in mgr.keys if k.is_available())
    results.append(
        TestResultItem(
            step="Key Pool Readiness",
            success=active_count > 0,
            message=f"{active_count} of {len(mgr.keys)} keys active & available",
            duration_ms=0.0,
        )
    )

    return results


@router.post("/services/{service_id}/keys/{key_id}/test", response_model=TestResultItem)
async def test_key(service_id: str, key_id: str) -> TestResultItem:
    mgr = get_registry().get_manager(service_id)
    if not mgr:
        raise HTTPException(status_code=404, detail="Service not found")

    target_key = next((k for k in mgr.keys if k.key_id == key_id), None)
    if not target_key:
        raise HTTPException(status_code=404, detail="Key not found")

    start = time.perf_counter()
    headers = mgr.provider_adapter.prepare_headers(
        target_key.secret_key, httpx.Headers({"accept": "application/json"})
    )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Send MCP JSON-RPC ping
            resp = await client.post(
                mgr.upstream_url,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            )
            duration = round((time.perf_counter() - start) * 1000, 2)
            signal = await mgr.provider_adapter.classify_response(resp)

            if signal.kind == ProviderSignalKind.SUCCESS:
                return TestResultItem(
                    step="MCP Read-only Ping",
                    success=True,
                    message=f"Ping succeeded ({resp.status_code})",
                    duration_ms=duration,
                )
            return TestResultItem(
                step="MCP Read-only Ping",
                success=False,
                message=f"Ping failed: {signal.reason or resp.status_code}",
                duration_ms=duration,
            )
    except Exception as exc:
        return TestResultItem(
            step="MCP Read-only Ping",
            success=False,
            message=f"Connection error: {exc}",
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )


@router.get("/requests", response_model=list[RequestLogItem])
async def list_request_logs(limit: int = Query(default=50, le=200)) -> list[RequestLogItem]:
    return get_registry().get_logs(limit=limit)
