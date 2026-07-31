FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/mcp_pool/__init__.py ./src/mcp_pool/__init__.py
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

RUN groupadd --system mcp-pool \
    && useradd --system --gid mcp-pool --home-dir /app mcp-pool \
    && mkdir -p /app/data \
    && chown -R mcp-pool:mcp-pool /app/data

USER mcp-pool

EXPOSE 8000

CMD ["python", "-m", "mcp_pool.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
