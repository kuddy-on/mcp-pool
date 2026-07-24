# Architecture

## Scope

MCPPool presents one logical MCP endpoint backed by multiple accounts for the same upstream MCP service. The gateway is protocol-aware enough to preserve MCP sessions and identify JSON-RPC method boundaries, but it avoids reimplementing an upstream server unless termination is explicitly required.

## Core concepts

- **Service**: one logical upstream MCP service, such as Context7.
- **Account**: the upstream identity that owns subscription quota and policy.
- **Credential**: an API key, access token, refresh token, or other authentication material belonging to an account.
- **Quota bucket**: a limit attached to an account and optional scope such as tool, model, project, minute, day, or month.
- **Session binding**: a stable mapping from a gateway session to an account and upstream session.

An account may contain multiple credentials, but credentials do not become independent quota owners unless a provider explicitly documents that behavior.

## Request flow

1. Authenticate the MCP client against MCPPool.
2. Parse only the minimum JSON-RPC envelope required for routing and policy.
3. Resolve a stable session key.
4. Reuse an existing account binding or select an eligible account.
5. Acquire an account concurrency lease.
6. Load and decrypt an eligible credential.
7. Let the provider adapter inject authentication and provider headers.
8. Stream the request and response without transforming successful payloads.
9. Classify response signals and update account state.
10. Release the lease and emit metrics and audit metadata.

## Planes

### Data plane

The data plane handles MCP traffic and must remain stateless across replicas except for external session and lease storage. It includes:

- client authentication
- Streamable HTTP and SSE forwarding
- session resolution and binding
- account eligibility and routing
- credential injection
- response classification
- safe retry enforcement

### Control plane

The control plane manages durable configuration:

- services and provider adapters
- accounts and credentials
- routing policy and weights
- quota buckets and reset observations
- manual pause, resume, and disable operations
- client API keys and access policy

### Worker plane

Workers perform operations outside the request critical path:

- OAuth refresh with distributed locking
- quota reset recovery
- paused-account probing
- health checks
- usage aggregation and retention cleanup

## State placement

### PostgreSQL

PostgreSQL is the source of truth for services, accounts, encrypted credentials, quota observations, durable pauses, policies, and audit history.

### Redis

Redis stores high-frequency runtime state such as session bindings, inflight counters, leases, short cooldowns, refresh locks, and hot routing snapshots.

A Redis restart must not reactivate an account whose monthly quota exhaustion is persisted in PostgreSQL.

## Account state machine

```text
ACTIVE
  -> COOLDOWN          short rate limit or Retry-After
  -> QUOTA_PAUSED      daily/monthly quota exhausted
  -> REFRESHING        access credential expired
  -> AUTH_INVALID      refresh or authentication rejected
  -> UNHEALTHY         transport or repeated upstream failure
  -> MANUAL_PAUSED     operator action
  -> DISABLED          configuration action

COOLDOWN / QUOTA_PAUSED / UNHEALTHY
  -> PROBING
  -> ACTIVE            successful probe
```

Unknown `429` responses use bounded exponential cooldown. They must not be interpreted as monthly exhaustion without authoritative headers or provider-specific body evidence.

## Routing

The default strategy is weighted rendezvous hashing for stable-session traffic. It provides deterministic session affinity without a global round-robin cursor and moves only a subset of sessions when the pool changes.

Requests without a stable session key use least-inflight selection among eligible accounts.

Eligibility requires:

- account enabled and active
- valid credential
- relevant quota buckets available
- pause or cooldown expired
- current inflight below maximum concurrency

## Retry safety

Cross-account retries are allowed by default only for protocol and read-oriented operations such as initialization, ping, listing, and resource reads.

`tools/call` is not retried across accounts unless the configured tool policy declares it idempotent or the provider supports an idempotency key. A timeout after an upstream side effect may otherwise duplicate the operation.

## Provider adapters

Provider-specific logic is isolated behind adapters. An adapter may:

- inject API keys or OAuth tokens
- refresh credentials
- classify quota, rate-limit, authentication, and health responses
- parse authoritative reset timestamps
- probe account availability
- declare whether a session can be rebound safely

Context7 is the first planned adapter. A generic header/body-rule adapter follows after the core routing path is stable.

## Initial deployment

The first production shape is one repository with separate process commands:

```text
mcp-pool serve
mcp-pool worker
```

The gateway may scale horizontally behind a load balancer once session bindings and leases are externalized to Redis. PostgreSQL remains authoritative for durable state.
