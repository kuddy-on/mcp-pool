# ADR 0001: Technology stack

- Status: Accepted
- Date: 2026-07-24

## Context

MCPPool needs asynchronous proxying, streaming responses, typed configuration, durable quota
state, and a straightforward single-node deployment.

## Decision

Use:

- Python 3.12+
- uv for dependency and environment management
- FastAPI and Starlette for ASGI endpoints
- httpx for asynchronous streaming upstream calls
- SQLite with SQLAlchemy async for configuration, runtime state, and audit records
- Pydantic v2 and pydantic-settings for validation and configuration
- cryptography for reversible upstream-credential encryption
- HMAC digests for non-recoverable Gateway API-key storage
- Ruff, mypy, and pytest for quality gates

The gateway forwarding path will use low-level ASGI and HTTP streaming primitives. A high-level MCP SDK may be used for protocol types, contract tests, and future termination mode, but it will not own the proxy data path.

## Consequences

- The stack aligns with the maintainer's existing Python and FastAPI experience.
- SQLite keeps installation, backup, and operation simple.
- The gateway is intentionally single-node; multiple writable replicas are out of scope.
- Provider-specific complexity remains in application code rather than external proxy configuration.
- Avoiding a high-level MCP server abstraction in the hot path preserves unknown extensions and streaming behavior.
