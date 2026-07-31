# ADR 0003: Quota-aware weighted routing and session affinity

- Status: Accepted
- Date: 2026-07-27

## Context

MCPPool needs predictable routing without introducing a second state service. The current
deployment is a single gateway process backed by SQLite.

## Decision

Use an in-process smooth weighted round-robin cursor. Before selection, exclude keys that are disabled,
authentication-invalid, rate-limited, or at their configured monthly quota. Within one request, try
each eligible key at most once.

Reserve the selected key's remaining configured quota until its audit record is committed. Bind
upstream `Mcp-Session-Id` values to the key that created them for a bounded time.

Explicit upstream rejection may select another key. Connection loss and `5xx` responses may select
another key only for known read-only operations.

## Consequences

- Routing is easy to inspect and operate on one node.
- `tools/call` is protected from replay after an ambiguous outcome.
- Account state and cooldowns survive gateway restarts through SQLite.
- Session affinity is intentionally process-local; durable multi-replica coordination remains out
  of scope.
