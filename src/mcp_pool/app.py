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
from mcp_pool.config import get_settings
from mcp_pool.db import init_db
from mcp_pool.domain.admin import RequestLogItem
from mcp_pool.pool import KeyPoolRegistry
from mcp_pool.providers.base import ProviderSignalKind

pool_registry: KeyPoolRegistry | None = None
http_client: httpx.AsyncClient | None = None

HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]


async def _stream_response(response: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in response.aiter_bytes():
        yield chunk
    await response.aclose()


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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MCPPool",
        version=__version__,
        description="Multi-account pooling and quota-aware routing gateway for MCP services.",
        lifespan=lifespan,
    )

    # Mount admin API routes under /api/admin
    app.include_router(admin_router)

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> dict[str, str]:
        return {"status": "ready", "environment": settings.environment}

    @app.api_route("/{path:path}", methods=HTTP_METHODS)
    async def proxy_mcp(request: Request, path: str) -> Response:
        if pool_registry is None or http_client is None:
            raise HTTPException(status_code=503, detail="Gateway initializing")

        # Resolve service name from header/prefix, else fallback to default
        service_name = request.headers.get("x-mcp-service")
        pool_manager = pool_registry.get_manager(service_name)
        if pool_manager is None:
            raise HTTPException(status_code=404, detail="No matching MCP service found")

        body = await request.body()
        max_attempts = len(pool_manager.keys) or 1
        failover_chain: list[str] = []
        start_time = time.perf_counter()

        for _ in range(max_attempts):
            key = pool_manager.get_current_key()
            if key is None:
                raise HTTPException(
                    status_code=503, detail="All MCP API keys are exhausted or unavailable"
                )

            url = f"{pool_manager.upstream_url}/{path}"
            if request.url.query:
                url = f"{url}?{request.url.query}"

            headers = pool_manager.provider_adapter.prepare_headers(
                key.secret_key, httpx.Headers(request.headers)
            )
            headers.pop("x-mcp-service", None)

            try:
                upstream_req = http_client.build_request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    content=body,
                )
                upstream_resp = await http_client.send(upstream_req, stream=True)

                signal = await pool_manager.provider_adapter.classify_response(upstream_resp)
                pool_manager.mark_signal(key.key_id, signal.kind, signal.retry_at)
                failover_chain.append(f"{key.name}:{signal.kind.value}")

                if signal.kind in (
                    ProviderSignalKind.QUOTA_EXHAUSTED,
                    ProviderSignalKind.AUTH_INVALID,
                ):
                    await upstream_resp.aclose()
                    continue

                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                await pool_registry.add_log(
                    RequestLogItem(
                        id=str(uuid4()),
                        service_name=pool_manager.service_name,
                        timestamp=datetime.now(UTC),
                        method=request.method,
                        path=path,
                        key_id=key.key_id,
                        status_code=upstream_resp.status_code,
                        signal_kind=signal.kind.value,
                        duration_ms=duration_ms,
                        failover_chain=failover_chain,
                    )
                )

                resp_headers = dict(upstream_resp.headers)
                resp_headers.pop("transfer-encoding", None)
                resp_headers.pop("content-length", None)

                return StreamingResponse(
                    content=_stream_response(upstream_resp),
                    status_code=upstream_resp.status_code,
                    headers=resp_headers,
                )
            except httpx.RequestError:
                pool_manager.mark_signal(key.key_id, ProviderSignalKind.UPSTREAM_UNHEALTHY)
                failover_chain.append(f"{key.name}:unhealthy")
                continue

        raise HTTPException(status_code=503, detail="All MCP API keys failed or quota exhausted")

    return app


app = create_app()
