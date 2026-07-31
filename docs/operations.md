# Operations runbook

## Back up and restore

Keep the SQLite database and `MCP_POOL_SECRET_KEY` in the same recovery set. Before an upgrade,
stop writes or stop the gateway, then use SQLite's online backup command:

```bash
sqlite3 data/mcp_pool.db ".backup 'mcp_pool.backup.db'"
sqlite3 mcp_pool.backup.db "PRAGMA integrity_check;"
```

To restore, stop the gateway, preserve the failed database for diagnosis, place the verified backup
at the configured database path, restore the matching application secret, and start one gateway
process. Readiness must return 200 before the dashboard is exposed.

Test recovery periodically in an isolated environment. A backup without its matching secret cannot
recover encrypted upstream credentials.

## Upgrade and rollback

1. Read `CHANGELOG.md`, back up the database, and record the current image/package version.
2. Run the new release against a copy of the database and verify schema migrations, login, service
   listing, and a read-only upstream request.
3. Deploy one gateway process and wait for `/health/ready`.
4. Verify `/metrics`, error logs, quota state, and one MCP session.

Schema changes are versioned in `schema_migrations` and applied in order during startup. A migration
failure stops startup and is not marked complete. To roll application code back after a schema
upgrade, restore the pre-upgrade database backup; down migrations are intentionally not automated.

### Password-hash upgrade

MCPPool accepts only versioned scrypt password hashes. Databases created by releases that used
legacy password digests must reset each affected account before upgrading:

```bash
docker compose run --rm gateway mcp-pool reset-password admin
```

The command reads the new password from a hidden confirmation prompt, stores a salted scrypt hash,
and revokes existing access tokens. It never accepts the password as a command-line argument.

## Secret rotation

The application secret currently protects credential encryption, JWT signing, and Gateway-key
digests. These uses are domain-separated by their algorithms and stored-value prefixes, but they
still share one root secret. Rotating it requires a controlled maintenance window:

1. Export or otherwise retain every upstream credential and plan to issue new Gateway API keys.
2. Stop the gateway and back up the database and old secret.
3. Reconfigure credentials and Gateway keys under the new secret in an isolated deployment.
4. Verify login, decryption, proxy authentication, and rollback before exposing the deployment.

Never replace the secret in place against the only copy of a production database.

## Alerts

Scrape `/metrics` only from the operations network. Alert on readiness failures, sustained
non-success upstream signals, stream errors/cancellations, high p95 proxy duration, disk growth,
and quota exhaustion. Service names are metric labels and should not contain secrets or personal
data.
