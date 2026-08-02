"""Search is metered and the key belongs to the operator.

Every guest's sweep spends from one ceiling, and the failure is silent and late:
Scout stops finding things for everyone and nobody can tell why. These tests
cover the bound that makes that impossible, and the two deliberate choices in it.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.search_budget import (
    GUEST_DAILY_QUERIES,
    GUEST_MONTHLY_QUERIES,
    OPERATOR_MONTHLY_QUERIES,
    SearchBudget,
)

_REDIS = "redis://localhost:6379/0"
_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _budget() -> SearchBudget:
    return SearchBudget(_REDIS)


# Wide enough that the day never binds, so a test that names the month
# measures the month.
_NO_DAILY_BOUND = 10_000


def _user() -> str:
    return f"budget_{uuid.uuid4().hex[:12]}"


@pytest.mark.asyncio
async def test_a_guest_may_spend_up_to_their_allowance():
    user = _user()
    budget = _budget()
    assert await budget.remaining(user, False, _NOW) == GUEST_MONTHLY_QUERIES
    assert await budget.reserve(user, False, 4, _NOW) == 4
    assert await budget.remaining(user, False, _NOW) == GUEST_MONTHLY_QUERIES - 4


@pytest.mark.asyncio
async def test_a_sweep_past_the_ceiling_is_reduced_rather_than_refused():
    # Finding less beats finding nothing, so a partial grant still runs.
    user = _user()
    budget = _budget()
    await budget.reserve(
        user, False, GUEST_MONTHLY_QUERIES - 2, _NOW, daily_override=_NO_DAILY_BOUND
    )

    granted = await budget.reserve(user, False, 4, _NOW, daily_override=_NO_DAILY_BOUND)

    assert granted == 2
    assert await budget.remaining(user, False, _NOW) == 0


@pytest.mark.asyncio
async def test_an_exhausted_account_is_granted_nothing():
    user = _user()
    budget = _budget()
    await budget.reserve(
        user, False, GUEST_MONTHLY_QUERIES, _NOW, daily_override=_NO_DAILY_BOUND
    )

    assert (
        await budget.reserve(user, False, 4, _NOW, daily_override=_NO_DAILY_BOUND) == 0
    )


@pytest.mark.asyncio
async def test_the_operator_has_a_larger_allowance_but_is_not_exempt():
    # An exempt operator makes the shared ceiling invisible again, which is the
    # problem this exists to solve.
    user = _user()
    budget = _budget()
    assert OPERATOR_MONTHLY_QUERIES > GUEST_MONTHLY_QUERIES
    await budget.reserve(
        user, True, OPERATOR_MONTHLY_QUERIES, _NOW, daily_override=_NO_DAILY_BOUND
    )

    assert (
        await budget.reserve(user, True, 1, _NOW, daily_override=_NO_DAILY_BOUND) == 0
    )


@pytest.mark.asyncio
async def test_one_account_cannot_spend_anothers_allowance():
    first, second = _user(), _user()
    budget = _budget()
    await budget.reserve(
        first, False, GUEST_MONTHLY_QUERIES, _NOW, daily_override=_NO_DAILY_BOUND
    )

    assert await budget.remaining(second, False, _NOW) == GUEST_MONTHLY_QUERIES


@pytest.mark.asyncio
async def test_a_new_month_starts_fresh():
    user = _user()
    budget = _budget()
    await budget.reserve(
        user, False, GUEST_MONTHLY_QUERIES, _NOW, daily_override=_NO_DAILY_BOUND
    )
    september = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    assert await budget.remaining(user, False, september) == GUEST_MONTHLY_QUERIES


@pytest.mark.asyncio
async def test_an_unavailable_counter_permits_the_sweep():
    # This is a rate limiter, not an authorization boundary. Failing closed
    # would take the feature down for everyone because a cache restarted.
    broken = SearchBudget("redis://127.0.0.1:6390/0")

    assert await broken.reserve(_user(), False, 4, _NOW) == 4


@pytest.mark.asyncio
async def test_a_disabled_budget_grants_everything():
    disabled = SearchBudget(_REDIS, enabled=False)
    assert await disabled.reserve(_user(), False, 9, _NOW) == 9


@pytest.mark.asyncio
async def test_a_day_bounds_what_a_single_bad_day_can_cost():
    # The month is the billing period but the wrong unit to protect: an account
    # in a loop on the first can spend the whole month before anything notices.
    user = _user()
    budget = _budget()
    assert GUEST_DAILY_QUERIES < GUEST_MONTHLY_QUERIES
    await budget.reserve(user, False, GUEST_DAILY_QUERIES, _NOW)

    assert await budget.reserve(user, False, 1, _NOW) == 0
    # The day is spent; the month is not, which is the whole point.
    assert await budget.remaining(user, False, _NOW) > 0
    assert await budget.remaining_today(user, False, _NOW) == 0


@pytest.mark.asyncio
async def test_tomorrow_refills_the_day_without_refilling_the_month():
    user = _user()
    budget = _budget()
    await budget.reserve(user, False, GUEST_DAILY_QUERIES, _NOW)
    tomorrow = _NOW + timedelta(days=1)

    assert await budget.remaining_today(user, False, tomorrow) == GUEST_DAILY_QUERIES
    spent = GUEST_MONTHLY_QUERIES - GUEST_DAILY_QUERIES
    assert await budget.remaining(user, False, tomorrow) == spent


@pytest.mark.asyncio
async def test_a_query_the_month_refuses_does_not_burn_the_day():
    # The day is charged first, so a request the month then rejects has to give
    # the day back. Otherwise an exhausted month would silently eat every
    # remaining day as well.
    user = _user()
    budget = _budget()
    await budget.reserve(
        user, False, GUEST_MONTHLY_QUERIES, _NOW, daily_override=_NO_DAILY_BOUND
    )
    before = await budget.remaining_today(user, False, _NOW)

    assert await budget.reserve(user, False, 1, _NOW) == 0
    assert await budget.remaining_today(user, False, _NOW) == before


@pytest.mark.asyncio
async def test_the_operator_may_set_a_daily_limit_for_one_account():
    user = _user()
    budget = _budget()

    assert await budget.reserve(user, False, 3, _NOW, daily_override=2) == 2
    # Zero stops an account searching without removing it.
    assert await budget.reserve(_user(), False, 1, _NOW, daily_override=0) == 0
