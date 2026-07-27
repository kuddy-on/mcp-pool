# Architecture

## Scope

MCPPool presents one logical MCP endpoint backed by multiple API-key accounts for the same
upstream MCP service. The gateway reads only enough of the JSON-RPC envelope to identify the MCP
method and apply safe retry rules.

## Core concepts

- **Service**: one logical upstream MCP service, such as Context7.
- **Account key**: one upstream API key with its own enabled state, cooldown, and configured monthly
  quota.
- **Gateway key**: a client-facing key that authorizes use of MCPPool.
- **Provider adapter**: provider-specific authentication and response classification.

## Request flow

1. Authenticate the MCP client against MCPPool.
2. Parse the minimum JSON-RPC envelope required for retry policy and audit metadata.
3. Read monthly usage and select the next eligible account key.
4. Decrypt the credential in memory and let the provider adapter inject authentication.
5. Forward the request and classify the upstream response.
6. Persist key state and audit metadata in SQLite.
7. Stream the response without transforming successful payloads.

## Planes

### Proxy path

The proxy path handles MCP traffic:

- client authentication
- Streamable HTTP and SSE forwarding
- quota-aware round-robin account routing
- credential injection
- response classification
- safe retry enforcement

### Administration path

The administration path manages:

- services and provider adapters
- account keys and encrypted credentials
- configured monthly quotas and manual usage offsets
- manual pause, resume, and disable operations
- client API keys and access policy
- users, settings, and request logs

## State placement

SQLite is the only state store. It holds services, encrypted upstream credentials, HMAC Gateway-key
digests, account availability, cooldowns, quota configuration, users, settings, and audit history.
Proxy processes keep a small in-memory routing view and persist every classified account signal
back to SQLite.

## Account state machine

```text
ACTIVE
  -> RATE_LIMITED      Retry-After or bounded default cooldown
  -> QUOTA_EXHAUSTED   authoritative provider response
  -> AUTH_INVALID      authentication rejected
  -> DISABLED          operator action

RATE_LIMITED
  -> ACTIVE            cooldown elapsed
```

Configured monthly quota is evaluated independently when selecting a key. A `429` uses
`Retry-After` seconds or HTTP-date when available, otherwise a 60-second cooldown.

## Routing

The current strategy is round-robin across eligible account keys. A request tries each eligible key
at most once.

Eligibility requires:

- account enabled and active
- configured monthly usage below quota
- rate-limit cooldown expired
- not rejected by upstream authentication

## Retry safety

Explicit rejections (`401`, `403`, or `429`) indicate that the upstream did not accept the request
and may fail over to another key. Connection errors and `5xx` responses are ambiguous and fail over
only for HTTP/MCP operations known to be read-only.

`tools/call` is never retried after an ambiguous outcome. A timeout after an upstream side effect
may otherwise duplicate the operation.

## Provider adapters

Provider-specific logic is isolated behind adapters. An adapter may:

- inject API keys or OAuth tokens
- classify quota, rate-limit, authentication, and health responses
- parse `Retry-After`

Context7 has a dedicated adapter. A configurable generic-header adapter supports other services.

## Initial deployment

The deployment consists of one gateway process and an optional dashboard:

```text
mcp-pool serve
nginx + static React dashboard
```

SQLite is mounted as a persistent Docker volume. Horizontal writable replicas are intentionally out
of scope for this simple deployment.
