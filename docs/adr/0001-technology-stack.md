# ADR 0001: Technology stack

- Status: Accepted
- Date: 2026-07-24

## Context

MCPPool needs low-latency asynchronous proxying, streaming responses, typed configuration, durable quota state, distributed runtime coordination, and a straightforward contribution workflow.

## Decision

Use:

- Python 3.12+
- uv for dependency and environment management
- FastAPI and Starlette for ASGI endpoints
- httpx for asynchronous HTTP/2 and streaming upstream calls
- PostgreSQL with SQLAlchemy async for durable state
- Redis for sessions, leases, counters, locks, and short cooldowns
- Pydantic v2 and pydantic-settings for validation and configuration
- cryptography for credential envelope encryption
- Prometheus, structured logging, and OpenTelemetry-ready interfaces for observability
- Ruff, mypy, and pytest for quality gates

The gateway forwarding path will use low-level ASGI and HTTP streaming primitives. A high-level MCP SDK may be used for protocol types, contract tests, and future termination mode, but it will not own the proxy data path.

## Consequences

- The stack aligns with the maintainer's existing Python and FastAPI experience.
- PostgreSQL and Redis add operational dependencies but provide correct multi-replica behavior.
- Provider-specific complexity remains in application code rather than external proxy configuration.
- Avoiding a high-level MCP server abstraction in the hot path preserves unknown extensions and streaming behavior.
