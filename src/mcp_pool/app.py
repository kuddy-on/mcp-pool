from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mcp_pool import __version__
from mcp_pool.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Database, Redis, and shared HTTP clients will be initialized here.
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MCPPool",
        version=__version__,
        description="Multi-account pooling and quota-aware routing gateway for MCP services.",
        lifespan=lifespan,
    )

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> dict[str, str]:
        # Replace with dependency checks once persistence adapters are wired.
        return {"status": "ready", "environment": settings.environment}

    return app


app = create_app()
