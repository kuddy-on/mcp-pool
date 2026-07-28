import json
import math
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from mcp_pool import __version__, admin_routes
from mcp_pool.admin_routes import router as admin_router
from mcp_pool.auth_routes import router as auth_router
from mcp_pool.config import get_settings
from mcp_pool.db import init_db
from mcp_pool.domain.admin import RequestLogItem
from mcp_pool.pool import KeyPoolManager, KeyPoolRegistry
from mcp_pool.providers.base import ProviderSignalKind
from mcp_pool.providers.context7 import Context7ProviderAdapter

pool_registry: KeyPoolRegistry | None = None
http_client: httpx.AsyncClient | None = None

HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
SAFE_MCP_METHODS = {
    "initialize",
    "ping",
    "tools/list",
    "prompts/list",
    "resources/list",
    "resources/read",
    "resources/templates/list",
    "completion/complete",
}
DEFINITIVE_REJECTION_SIGNALS = {
    ProviderSignalKind.QUOTA_EXHAUSTED,
    ProviderSignalKind.AUTH_INVALID,
    ProviderSignalKind.RATE_LIMITED,
}
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


async def _stream_response(response: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()


def extract_mcp_method(body_bytes: bytes) -> str | None:
    """Extract MCP JSON-RPC method and tool name from request body."""
    if not body_bytes:
        return None
    try:
        data = json.loads(body_bytes.decode("utf-8"))
        if isinstance(data, dict):
            method = data.get("method")
            if not method:
                return None
            params = data.get("params")
            if isinstance(params, dict) and "name" in params:
                return f"{method} ({params['name']})"
            return str(method)
    except Exception:
        pass
    return None


def is_probe_request(method: str, path: str, mcp_method: str | None = None) -> bool:
    """Check if the request is an HTTP preflight/probe, OAuth discovery, or capability list."""
    if method == "OPTIONS":
        return True
    clean_path = path.strip("/")
    if ".well-known" in clean_path:
        return True
    if method == "GET" and clean_path in ("mcp", "health", ""):
        return True
    return mcp_method in ("tools/list", "prompts/list", "resources/list", "initialize", "ping")


def is_ambiguous_retry_safe(http_method: str, mcp_method: str | None) -> bool:
    """Whether a transport error or 5xx may be retried on another account."""
    if http_method in SAFE_HTTP_METHODS:
        return True
    if not mcp_method:
        return False
    method_name = mcp_method.split(" (", 1)[0]
    return method_name in SAFE_MCP_METHODS


def authenticate_gateway_request(request: Request, registry: KeyPoolRegistry) -> str:
    client_key_name = registry.validate_client_key(request.headers.get("authorization"))
    if client_key_name is None:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or missing client Gateway API Key",
        )
    return client_key_name


def build_upstream_url(manager: KeyPoolManager, path: str, query: str) -> str:
    base_url = manager.upstream_url
    clean_path = path.lstrip("/")
    if base_url.endswith("/mcp") and (clean_path == "mcp" or not clean_path):
        url = base_url
    elif clean_path:
        url = f"{base_url}/{clean_path}"
    else:
        url = base_url
    return f"{url}?{query}" if query else url


def response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS
    }


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global pool_registry, http_client
    await init_db()
    settings = get_settings()
    pool_registry = KeyPoolRegistry(settings.services)
    await pool_registry.initialize()
    admin_routes.registry = pool_registry
    http_client = httpx.AsyncClient(timeout=60.0)
    yield
    if http_client:
        await http_client.aclose()


async def proxy_request(
    request: Request,
    path: str,
    manager: KeyPoolManager,
    registry: KeyPoolRegistry,
    client: httpx.AsyncClient,
    client_key_name: str,
) -> Response:
    body = await request.body()
    mcp_method = extract_mcp_method(body)
    monthly_usage = await registry.get_monthly_usage()
    attempted_key_ids: set[str] = set()
    failover_chain: list[str] = []
    rate_limited_until: list[datetime] = []
    start_time = time.perf_counter()
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )

    async def add_request_log(
        key_id: str,
        key_name: str,
        status_code: int,
        signal_kind: ProviderSignalKind,
    ) -> None:
        if is_probe_request(request.method, path, mcp_method):
            return
        await registry.add_log(
            RequestLogItem(
                id=str(uuid4()),
                service_name=manager.service_name,
                timestamp=datetime.now(UTC),
                method=request.method,
                path=path,
                mcp_method=mcp_method,
                key_id=key_id,
                key_name=key_name,
                client_key_name=client_key_name or None,
                client_ip=client_ip,
                status_code=status_code,
                signal_kind=signal_kind.value,
                duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                failover_chain=failover_chain,
            )
        )

    for _ in range(len(manager.keys) or 1):
        key = manager.get_current_key(monthly_usage, attempted_key_ids)
        if key is None:
            break
        attempted_key_ids.add(key.key_id)

        credential = key.secret_key
        headers = manager.provider_adapter.prepare_headers(
            credential,
            httpx.Headers(request.headers),
        )
        headers.pop("x-mcp-service", None)
        upstream_request = client.build_request(
            method=request.method,
            url=build_upstream_url(manager, path, request.url.query),
            headers=headers,
            content=body,
        )

        try:
            upstream_response = await client.send(upstream_request, stream=True)
        except httpx.RequestError as exc:
            await registry.record_signal(
                manager,
                key.key_id,
                ProviderSignalKind.UPSTREAM_UNHEALTHY,
            )
            failover_chain.append(f"{key.name}:unhealthy")
            if is_ambiguous_retry_safe(request.method, mcp_method):
                continue
            await add_request_log(
                key.key_id,
                key.name,
                502,
                ProviderSignalKind.UPSTREAM_UNHEALTHY,
            )
            raise HTTPException(
                status_code=502,
                detail="Upstream connection failed; request was not retried because "
                "the operation may be non-idempotent",
            ) from exc

        signal = await manager.provider_adapter.classify_response(upstream_response)
        if key.secret_key == credential:
            if isinstance(manager.provider_adapter, Context7ProviderAdapter):
                manager.provider_adapter.capture_quota_response(
                    key,
                    upstream_response,
                    expected_credential=credential,
                )
            await registry.record_signal(
                manager,
                key.key_id,
                signal.kind,
                signal.retry_at,
            )
        failover_chain.append(f"{key.name}:{signal.kind.value}")

        if signal.kind in DEFINITIVE_REJECTION_SIGNALS:
            if signal.kind == ProviderSignalKind.RATE_LIMITED and signal.retry_at:
                rate_limited_until.append(signal.retry_at)
            await upstream_response.aclose()
            continue

        if signal.kind == ProviderSignalKind.UPSTREAM_UNHEALTHY and is_ambiguous_retry_safe(
            request.method, mcp_method
        ):
            await upstream_response.aclose()
            continue

        await add_request_log(
            key.key_id,
            key.name,
            upstream_response.status_code,
            signal.kind,
        )
        return StreamingResponse(
            content=_stream_response(upstream_response),
            status_code=upstream_response.status_code,
            headers=response_headers(upstream_response),
        )

    if rate_limited_until:
        retry_at = min(rate_limited_until)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        retry_after = max(
            1,
            math.ceil((retry_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()),
        )
        raise HTTPException(
            status_code=429,
            detail="All eligible upstream accounts are rate limited",
            headers={"Retry-After": str(retry_after)},
        )

    raise HTTPException(
        status_code=503,
        detail="All MCP API keys failed, are unavailable, or reached their configured quota",
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MCPPool",
        version=__version__,
        description="Multi-account pooling and quota-aware routing gateway for MCP services.",
        lifespan=lifespan,
    )

    # Mount auth and admin API routes under /api
    app.include_router(auth_router)
    app.include_router(admin_router)

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> dict[str, str]:
        return {"status": "ready", "environment": settings.environment}

    @app.api_route("/s/{service_name}/{path:path}", methods=HTTP_METHODS)
    async def proxy_mcp_by_service(request: Request, service_name: str, path: str) -> Response:
        if pool_registry is None or http_client is None:
            raise HTTPException(status_code=503, detail="Gateway initializing")

        client_key_name = authenticate_gateway_request(request, pool_registry)
        pool_manager = pool_registry.get_manager(service_name)
        if pool_manager is None:
            raise HTTPException(
                status_code=404, detail=f"No matching MCP service '{service_name}' found"
            )
        return await proxy_request(
            request,
            path,
            pool_manager,
            pool_registry,
            http_client,
            client_key_name,
        )

    @app.api_route("/{path:path}", methods=HTTP_METHODS)
    async def proxy_mcp(request: Request, path: str) -> Response:
        if pool_registry is None or http_client is None:
            raise HTTPException(status_code=503, detail="Gateway initializing")

        client_key_name = authenticate_gateway_request(request, pool_registry)
        service_name = request.headers.get("x-mcp-service")
        pool_manager = pool_registry.get_manager(service_name)
        if pool_manager is None:
            raise HTTPException(status_code=404, detail="No matching MCP service found")
        return await proxy_request(
            request,
            path,
            pool_manager,
            pool_registry,
            http_client,
            client_key_name,
        )

    return app


app = create_app()
