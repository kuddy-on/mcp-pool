from uuid import uuid4

from mcp_pool.domain.account import AccountSnapshot, AccountStatus


def test_active_account_is_eligible() -> None:
    account = AccountSnapshot(
        id=uuid4(),
        status=AccountStatus.ACTIVE,
        max_concurrency=2,
    )

    assert account.is_eligible()


def test_saturated_account_is_not_eligible() -> None:
    account = AccountSnapshot(
        id=uuid4(),
        status=AccountStatus.ACTIVE,
        inflight=2,
        max_concurrency=2,
    )

    assert not account.is_eligible()
