# Changelog

Notable changes are documented here. The project follows Semantic Versioning after the first stable
release and uses the Keep a Changelog structure.

## [Unreleased]

### Added

- Bounded request bodies, MCP session affinity, weighted key routing, request-log retention,
  database readiness, and Prometheus metrics.
- Versioned database migrations, WAL-backed SQLite operation, request correlation IDs, and
  cancellation-safe upstream resource cleanup.
- Backend, frontend, container, and CodeQL CI checks plus Dependabot configuration.
- Backend coverage enforcement at 85%, dashboard unit tests, and desktop/mobile Playwright flows.
- Security, contribution, conduct, and licensing documentation.

### Changed

- Passwords now use salted scrypt hashes; legacy hashes are upgraded after successful login.
- Production rejects default or short application secrets and requires an explicit first-start
  administrator password.
- Gateway proxy access is denied until a client API key exists unless anonymous access is
  explicitly enabled.
- The upstream HTTP client supports long-lived SSE responses and filters hop-by-hop headers.
- Quota admission now uses a serialized, monotonic monthly ledger instead of stale request
  snapshots, and session affinity lookups are constant time.
- Dashboard tokens use tab-scoped storage and logout revokes the server-side token.

### Security

- Private literal upstream addresses are disabled by default, untrusted forwarding headers are
  ignored, containers run without root privileges, and the dashboard sends defensive headers.
- The vulnerable `cryptography` dependency range was upgraded and both Python and npm dependency
  audits report no known vulnerabilities.
