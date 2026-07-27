# ADR 0002: One API key per routed account

- Status: Superseded for the SQLite deployment
- Date: 2026-07-27

## Context

The original design separated accounts from credentials to model shared subscription quota. The
current deployment is intentionally smaller and manages API keys directly.

## Decision

Treat each configured API key as one routed account:

```text
Service
  -> Account key   credential, routing state, and configured monthly quota
```

The upstream secret is encrypted at rest. Availability, cooldown, provider rejection state, monthly
quota, and manual usage offset are stored on the same SQLite record.

## Consequences

- The model and administration UI remain straightforward.
- Quotas shared by several API keys must be apportioned manually between those keys.
- OAuth credentials and refresh workflows are out of scope.
