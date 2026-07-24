from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class AccountStatus(StrEnum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    QUOTA_PAUSED = "quota_paused"
    REFRESHING = "refreshing"
    AUTH_INVALID = "auth_invalid"
    UNHEALTHY = "unhealthy"
    MANUAL_PAUSED = "manual_paused"
    DISABLED = "disabled"
    PROBING = "probing"


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Routing-relevant account state.

    Accounts own quota. Credentials are authentication material attached to an
    account and must not be treated as independent quota buckets by default.
    """

    id: UUID
    status: AccountStatus
    enabled: bool = True
    credential_valid: bool = True
    quota_available: bool = True
    inflight: int = 0
    max_concurrency: int = 1
    paused_until: datetime | None = None
    weight: float = 1.0

    def is_eligible(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        if not self.enabled or self.status is not AccountStatus.ACTIVE:
            return False
        if not self.credential_valid or not self.quota_available:
            return False
        if self.inflight >= self.max_concurrency:
            return False
        return self.paused_until is None or self.paused_until <= current_time
