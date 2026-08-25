"""The local search ceiling is in credits, and an advanced search costs two.

Tavily refused with 432 (plan limit) while the local counter showed room:
it had been counting calls, and each advanced call was billed at two credits.
"""

from __future__ import annotations

import pytest

from backend.search.budgeted import (
    BudgetedSearchProvider,
    SearchBudgetExceededError,
    SearchIdentity,
    current_search_identity,
)
from backend.search.types import SearchResults


class _Inner:
    def is_enabled(self) -> bool:
        return True

    async def search(self, query, max_results=None):
        return SearchResults(query=query, results=(), provider="test")


class _Budget:
    # Records what each search asked to reserve and grants what it is told to.
    def __init__(self, grant: int) -> None:
        self.grant = grant
        self.wanted: list[int] = []

    async def reserve(self, user_id, is_operator, wanted, now=None, override=None, daily_override=None):
        self.wanted.append(wanted)
        return min(wanted, self.grant)

    async def remaining_today(self, user_id, is_operator, override=None):
        return 0


@pytest.mark.asyncio
async def test_an_advanced_search_reserves_two_credits() -> None:
    budget = _Budget(grant=2)
    provider = BudgetedSearchProvider(_Inner(), budget, credits_per_search=2)  # type: ignore[arg-type]
    token = current_search_identity.set(SearchIdentity(user_id="u", is_operator=False))
    try:
        await provider.search("anything")
    finally:
        current_search_identity.reset(token)
    assert budget.wanted == [2]


@pytest.mark.asyncio
async def test_one_credit_left_does_not_fund_a_two_credit_search() -> None:
    budget = _Budget(grant=1)
    provider = BudgetedSearchProvider(_Inner(), budget, credits_per_search=2)  # type: ignore[arg-type]
    token = current_search_identity.set(SearchIdentity(user_id="u", is_operator=False))
    try:
        with pytest.raises(SearchBudgetExceededError):
            await provider.search("anything")
    finally:
        current_search_identity.reset(token)
