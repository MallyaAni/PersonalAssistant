"""Search is metered and the key belongs to the operator.

Every guest's sweep spends from one ceiling, and the failure is silent and late:
Scout stops finding things for everyone and nobody can tell why. These tests
cover the bound that makes that impossible, and the two deliberate choices in it.
"""

import os
import uuid
from datetime import UTC, datetime

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.search_budget import (
    GUEST_MONTHLY_QUERIES,
    OPERATOR_MONTHLY_QUERIES,
    SearchBudget,
)

_REDIS = "redis://localhost:6379/0"
_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _budget() -> SearchBudget:
    return SearchBudget(_REDIS)


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
    await budget.reserve(user, False, GUEST_MONTHLY_QUERIES - 2, _NOW)

    granted = await budget.reserve(user, False, 4, _NOW)

    assert granted == 2
    assert await budget.remaining(user, False, _NOW) == 0


@pytest.mark.asyncio
async def test_an_exhausted_account_is_granted_nothing():
    user = _user()
    budget = _budget()
    await budget.reserve(user, False, GUEST_MONTHLY_QUERIES, _NOW)

    assert await budget.reserve(user, False, 4, _NOW) == 0


@pytest.mark.asyncio
async def test_the_operator_has_a_larger_allowance_but_is_not_exempt():
    # An exempt operator makes the shared ceiling invisible again, which is the
    # problem this exists to solve.
    user = _user()
    budget = _budget()
    assert OPERATOR_MONTHLY_QUERIES > GUEST_MONTHLY_QUERIES
    await budget.reserve(user, True, OPERATOR_MONTHLY_QUERIES, _NOW)

    assert await budget.reserve(user, True, 1, _NOW) == 0


@pytest.mark.asyncio
async def test_one_account_cannot_spend_anothers_allowance():
    first, second = _user(), _user()
    budget = _budget()
    await budget.reserve(first, False, GUEST_MONTHLY_QUERIES, _NOW)

    assert await budget.remaining(second, False, _NOW) == GUEST_MONTHLY_QUERIES


@pytest.mark.asyncio
async def test_a_new_month_starts_fresh():
    user = _user()
    budget = _budget()
    await budget.reserve(user, False, GUEST_MONTHLY_QUERIES, _NOW)
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
