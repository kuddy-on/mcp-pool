# ADR 0002: Separate accounts from credentials

- Status: Accepted
- Date: 2026-07-24

## Context

Many upstream services allow one account to own multiple API keys or OAuth credentials while all of those credentials share the same subscription quota. Treating every key as an independent pool member would overestimate available quota and cause incorrect pause and recovery behavior.

## Decision

Model accounts and credentials separately:

```text
Service
  -> Account       quota owner and routing unit
       -> Credential   authentication material
       -> Quota bucket
```

Routing, concurrency, health, pause state, and quota exhaustion belong to the account. Credential records contain encrypted secrets, expiry, refresh metadata, and credential-specific validity.

A provider adapter may explicitly declare a credential-scoped quota, but account scope is the default.

## Consequences

- Multiple credentials can be rotated for security without manufacturing additional quota.
- OAuth refresh failures can invalidate one credential without losing the account model.
- Quota observations and reset timestamps remain attached to the correct owner.
- The data model is slightly more complex than a flat API-key list, but it reflects real provider behavior.
