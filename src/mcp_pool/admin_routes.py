import time
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from mcp_pool.auth import UserDTO, get_current_user, require_admin
from mcp_pool.domain.admin import (
    ClientApiKeyCreateRequest,
    ClientApiKeyResponse,
    KeyCreateRequest,
    KeyResponse,
    KeyUpdateRequest,
    RequestLogItem,
    ServiceCreateRequest,
    ServiceResponse,
    ServiceUpdateRequest,
    SystemSettingsResponse,
    SystemSettingsUpdateRequest,
    TestResultItem,
)
from mcp_pool.domain.quota import ProviderQuotaServiceResponse
from mcp_pool.domain.service import ServiceConfig
from mcp_pool.pool import KeyPoolManager, KeyPoolRegistry
from mcp_pool.providers.base import ProviderSignalKind
from mcp_pool.providers.context7 import Context7ProviderAdapter
from mcp_pool.quota import (
    ProviderQuotaRefreshBatchTooLargeError,
    ProviderQuotaRefreshCooldownError,
    ProviderQuotaRefreshInProgressError,
    get_provider_quota_status,
    refresh_provider_quota_status,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_user)],
)

# Global reference injected in app lifecycle
registry: KeyPoolRegistry | None = None


def get_registry() -> KeyPoolRegistry:
    if registry is None:
        raise HTTPException(status_code=503, detail="Registry not initialized")
    return registry


def get_authorized_manager(
    service_id: str,
    user: UserDTO,
    *,
    write: bool,
) -> KeyPoolManager:
    manager = get_registry().get_manager(service_id)
    if manager is None:
        raise HTTPException(status_code=404, detail="Service not found")
    if user.role == "admin" or manager.owner_id == user.id:
        return manager
    if not write and manager.owner_id is None:
        return manager
    raise HTTPException(status_code=403, detail="You do not have access to this service")


@router.get("/summary")
async def get_summary(user: Annotated[UserDTO, Depends(get_current_user)]) -> dict[str, Any]:
    reg = get_registry()
    services = await reg.list_services_async(user_id=user.id, is_admin=(user.role == "admin"))
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
async def list_services(
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> list[ServiceResponse]:
    return await get_registry().list_services_async(
        user_id=user.id, is_admin=(user.role == "admin")
    )


@router.post("/services", response_model=ServiceResponse)
async def create_service(
    req: ServiceCreateRequest, user: Annotated[UserDTO, Depends(get_current_user)]
) -> ServiceResponse:
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
    mgr = await reg.add_service(cfg, owner_id=user.id)
    return mgr.to_response()


@router.get("/services/{service_id}", response_model=ServiceResponse)
async def get_service(
    service_id: str,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> ServiceResponse:
    reg = get_registry()
    mgr = get_authorized_manager(service_id, user, write=False)
    usage = await reg.get_monthly_usage()
    return mgr.to_response(usage)


@router.get(
    "/services/{service_id}/quota-status",
    response_model=ProviderQuotaServiceResponse,
)
async def get_service_quota_status(
    service_id: str,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> ProviderQuotaServiceResponse:
    manager = get_authorized_manager(service_id, user, write=False)
    can_refresh = user.role == "admin" or manager.owner_id == user.id
    return get_provider_quota_status(manager, can_refresh=can_refresh)


@router.post(
    "/services/{service_id}/quota-status/refresh",
    response_model=ProviderQuotaServiceResponse,
)
async def refresh_service_quota_status(
    service_id: str,
    user: Annotated[UserDTO, Depends(get_current_user)],
    key_id: str | None = Query(default=None),
) -> ProviderQuotaServiceResponse:
    """Refresh Context7 quota.

    Each selected Context7 key is checked with one official HEAD request. That
    request consumes one unit, so returned remaining/used values are post-check.
    """
    manager = get_authorized_manager(service_id, user, write=True)
    try:
        return await refresh_provider_quota_status(
            manager,
            get_registry(),
            key_id=key_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Key not found") from exc
    except ProviderQuotaRefreshInProgressError as exc:
        raise HTTPException(
            status_code=409,
            detail="A quota refresh is already in progress for a selected key",
        ) from exc
    except ProviderQuotaRefreshCooldownError as exc:
        raise HTTPException(
            status_code=429,
            detail="Quota was queried too recently",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except ProviderQuotaRefreshBatchTooLargeError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "Bulk quota refresh is limited to "
                f"{exc.max_batch_size} keys; refresh a specific key instead"
            ),
        ) from exc


@router.patch("/services/{service_id}", response_model=ServiceResponse)
async def update_service(
    service_id: str,
    req: ServiceUpdateRequest,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> ServiceResponse:
    reg = get_registry()
    mgr = get_authorized_manager(service_id, user, write=True)

    if req.upstream_url is not None:
        mgr.upstream_url = req.upstream_url.rstrip("/")
    if req.provider_type is not None:
        mgr.provider_type = req.provider_type
    if req.auth_header is not None:
        mgr.auth_header = req.auth_header
    if req.auth_prefix is not None:
        mgr.auth_prefix = req.auth_prefix

    await reg.update_service_in_db(mgr)
    usage = await reg.get_monthly_usage()
    return mgr.to_response(usage)


@router.delete("/services/{service_id}")
async def delete_service(
    service_id: str,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> dict[str, str]:
    manager = get_authorized_manager(service_id, user, write=True)
    if await get_registry().remove_service(manager.service_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Service not found")


@router.get("/services/{service_id}/keys", response_model=list[KeyResponse])
async def list_keys(
    service_id: str,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> list[KeyResponse]:
    reg = get_registry()
    mgr = get_authorized_manager(service_id, user, write=False)
    usage = await reg.get_monthly_usage()
    return [k.to_response(usage) for k in mgr.keys]


@router.post("/services/{service_id}/keys", response_model=KeyResponse)
async def add_key(
    service_id: str,
    req: KeyCreateRequest,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> KeyResponse:
    reg = get_registry()
    manager = get_authorized_manager(service_id, user, write=True)
    key = await reg.add_key_to_service(
        service_id=manager.service_id,
        secret_key=req.secret_key,
        name=req.name,
        weight=req.weight,
        monthly_quota=req.monthly_quota,
    )
    if not key:
        raise HTTPException(status_code=404, detail="Service not found")
    usage = await reg.get_monthly_usage()
    return key.to_response(usage)


@router.patch("/services/{service_id}/keys/{key_id}", response_model=KeyResponse)
async def update_key(
    service_id: str,
    key_id: str,
    req: KeyUpdateRequest,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> KeyResponse:
    reg = get_registry()
    mgr = get_authorized_manager(service_id, user, write=True)

    target_key = next((k for k in mgr.keys if k.key_id == key_id), None)
    if not target_key:
        raise HTTPException(status_code=404, detail="Key not found")

    if req.name is not None:
        target_key.name = req.name
    if req.secret_key is not None:
        target_key.secret_key = req.secret_key
        target_key.provider_quota_snapshot = None
        target_key.provider_quota_error = None
        await reg.reset_provider_quota_refresh_cooldown(key_id)
    if req.weight is not None:
        target_key.weight = req.weight
    if req.monthly_quota is not None:
        target_key.monthly_quota = req.monthly_quota
    if req.used_this_month is not None:
        usage = await reg.get_monthly_usage()
        log_count = usage.get(target_key.key_id, 0)
        target_key.used_offset = req.used_this_month - log_count
    if req.is_active is not None:
        target_key.is_active = req.is_active
        if req.is_active:
            target_key.quota_exhausted = False

    await reg.update_key_in_db(key_id, target_key)
    usage = await reg.get_monthly_usage()
    return target_key.to_response(usage)


@router.delete("/services/{service_id}/keys/{key_id}")
async def delete_key(
    service_id: str,
    key_id: str,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> dict[str, str]:
    manager = get_authorized_manager(service_id, user, write=True)
    if await get_registry().delete_key_from_db(manager.service_id, key_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Service or Key not found")


@router.post("/services/{service_id}/test", response_model=list[TestResultItem])
async def test_service(
    service_id: str,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> list[TestResultItem]:
    reg = get_registry()
    mgr = get_authorized_manager(service_id, user, write=True)

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
    usage = await reg.get_monthly_usage()
    active_count = sum(
        1
        for key in mgr.keys
        if key.is_available(used_this_month=usage.get(key.key_id, 0) + key.used_offset)
    )
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
async def test_key(
    service_id: str,
    key_id: str,
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> TestResultItem:
    reg = get_registry()
    mgr = get_authorized_manager(service_id, user, write=True)

    target_key = next((k for k in mgr.keys if k.key_id == key_id), None)
    if not target_key:
        raise HTTPException(status_code=404, detail="Key not found")

    start = time.perf_counter()
    credential = target_key.secret_key
    headers = mgr.provider_adapter.prepare_headers(
        credential, httpx.Headers({"accept": "application/json"})
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
            if target_key.secret_key == credential:
                if isinstance(mgr.provider_adapter, Context7ProviderAdapter):
                    mgr.provider_adapter.capture_quota_response(
                        target_key,
                        resp,
                        expected_credential=credential,
                    )
                await reg.record_signal(
                    mgr,
                    target_key.key_id,
                    signal.kind,
                    signal.retry_at,
                )

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
async def list_request_logs(
    user: Annotated[UserDTO, Depends(get_current_user)],
    limit: int = Query(default=50, le=200),
) -> list[RequestLogItem]:
    reg = get_registry()
    service_names = reg.visible_service_names(user.id, user.role == "admin")
    return reg.get_logs(limit=limit, service_names=service_names)


@router.get("/settings", response_model=SystemSettingsResponse)
async def get_system_settings(
    user: Annotated[UserDTO, Depends(get_current_user)],
) -> SystemSettingsResponse:
    reg = get_registry()
    return SystemSettingsResponse(gateway_external_url=reg.gateway_external_url)


@router.patch("/settings", response_model=SystemSettingsResponse)
async def update_system_settings(
    req: SystemSettingsUpdateRequest, admin: Annotated[UserDTO, Depends(require_admin)]
) -> SystemSettingsResponse:
    reg = get_registry()
    await reg.update_external_url(req.gateway_external_url)
    return SystemSettingsResponse(gateway_external_url=reg.gateway_external_url)


@router.get("/client-keys", response_model=list[ClientApiKeyResponse])
async def list_client_api_keys(
    admin: Annotated[UserDTO, Depends(require_admin)],
) -> list[ClientApiKeyResponse]:
    reg = get_registry()
    db_keys = await reg.list_client_api_keys()
    out: list[ClientApiKeyResponse] = []
    for k in db_keys:
        out.append(
            ClientApiKeyResponse(
                id=k.id,
                name=k.name,
                api_key_masked=k.key_hint or "mcp_live_****",
                is_active=k.is_active,
                created_at=k.created_at,
            )
        )
    return out


@router.post("/client-keys")
async def create_client_api_key(
    req: ClientApiKeyCreateRequest, admin: Annotated[UserDTO, Depends(require_admin)]
) -> dict[str, str]:
    reg = get_registry()
    ck, raw_key = await reg.create_client_api_key(req.name)
    return {
        "id": ck.id,
        "name": ck.name,
        "api_key": raw_key,
    }


@router.delete("/client-keys/{key_id}")
async def delete_client_api_key(
    key_id: str, admin: Annotated[UserDTO, Depends(require_admin)]
) -> dict[str, str]:
    reg = get_registry()
    if await reg.delete_client_api_key(key_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Client key not found")
