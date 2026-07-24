# ADR 0003: Session-affine account routing

- Status: Accepted
- Date: 2026-07-24

## Context

Per-request round robin can move one MCP conversation between upstream accounts. This may break upstream session state, reduce cache locality, complicate debugging, and make retries unsafe.

A global round-robin cursor also becomes a coordination bottleneck when the gateway runs multiple replicas.

## Decision

Use weighted rendezvous hashing for requests with a stable session key:

```text
score = rendezvous(service, tenant, session, account) adjusted by account weight
```

Persist the selected account and upstream session in a session binding. Reuse that account while it remains eligible.

Use least-inflight selection for requests that do not expose a stable session key.

If a bound account becomes unavailable, fail over only when protocol and tool policy allow it. A new account may require a new upstream initialization before the client request continues.

## Consequences

- Sessions retain cache and upstream-state locality.
- Pool membership changes remap only a subset of sessions.
- Multiple gateway replicas do not require a global selection counter.
- Long sessions may produce uneven short-term consumption, so weights and account availability must be considered when assigning new sessions.
- Failover logic must distinguish safe protocol operations from potentially side-effecting tool calls.
