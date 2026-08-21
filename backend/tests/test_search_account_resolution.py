"""Whose allowance a sweep spends.

The sweep's search budget is charged with a flag fixed when the runner is
built, and for months both factories built it with the guest default - so
the operator's own scheduled sweeps burned the guest allowance and stopped
searching the day it ran out, while the operator's real budget sat unspent.
These pin the resolution both ways so the default can never quietly return.
"""

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.core.dependencies import resolve_search_account


class _Account:
    def __init__(self, is_admin: bool, search_monthly_limit: int | None) -> None:
        self.is_admin = is_admin
        self.search_monthly_limit = search_monthly_limit


class _Db:
    def __init__(self, row: _Account | None) -> None:
        self._row = row

    async def scalar(self, statement: object) -> _Account | None:
        return self._row


@pytest.mark.asyncio
async def test_an_admin_account_is_charged_as_the_operator():
    is_operator, limit = await resolve_search_account(
        _Db(_Account(is_admin=True, search_monthly_limit=120)), "ani.mallya"
    )
    assert is_operator is True
    assert limit == 120


@pytest.mark.asyncio
async def test_a_regular_account_keeps_the_guest_budget():
    is_operator, limit = await resolve_search_account(
        _Db(_Account(is_admin=False, search_monthly_limit=None)), "guest"
    )
    assert is_operator is False
    assert limit is None


# An account row that does not exist must not be promoted by accident.
@pytest.mark.asyncio
async def test_an_unknown_user_is_charged_as_a_guest():
    assert await resolve_search_account(_Db(None), "nobody") == (False, None)
