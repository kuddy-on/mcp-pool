# ADR 0003: Quota-aware round-robin routing

- Status: Superseded for the SQLite deployment
- Date: 2026-07-27

## Context

MCPPool needs predictable routing without introducing a second state service. The current
deployment is a single gateway process backed by SQLite.

## Decision

Use an in-process round-robin cursor. Before selection, exclude keys that are disabled,
authentication-invalid, rate-limited, or at their configured monthly quota. Within one request, try
each eligible key at most once.

Explicit upstream rejection may select another key. Connection loss and `5xx` responses may select
another key only for known read-only operations.

## Consequences

- Routing is easy to inspect and operate on one node.
- `tools/call` is protected from replay after an ambiguous outcome.
- Account state and cooldowns survive gateway restarts through SQLite.
- Session affinity and multi-replica coordination remain out of scope.
