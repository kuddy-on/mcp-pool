# Security policy

## Supported versions

Security fixes are applied to the latest release on the `main` branch. Pre-1.0 releases may include
breaking changes when a safe fix requires one.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private vulnerability
reporting for `kuddy-on/mcp-pool`. Include the affected version, deployment model, reproduction,
impact, and any suggested mitigation. You should receive an acknowledgement within 72 hours and a
status update within seven days.

## Deployment baseline

- Generate a unique `MCP_POOL_SECRET_KEY` with at least 32 random characters and back it up.
- Set a unique `MCP_POOL_INITIAL_ADMIN_PASSWORD` before the first startup, then remove it from the
  runtime environment after the administrator has been created.
- Keep `MCP_POOL_ALLOW_ANONYMOUS_GATEWAY=false`.
- Create a Gateway API key before exposing an MCP endpoint.
- Terminate TLS at a trusted reverse proxy and enable `MCP_POOL_TRUST_PROXY_HEADERS` only when
  direct client access to the gateway is blocked.
- Keep private upstream access disabled unless the deployment explicitly requires it.

Upstream credentials are encrypted at rest, but request metadata and account names remain in the
SQLite database. Protect database backups accordingly.
