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

    async def reserve(self, user_id, is_operator, wanted, now=None, override=None, daily_override=None, include_pool=True):
        self.wanted.append(wanted)
        return min(wanted, self.grant)

    async def provider_used(self, provider, now=None):
        return 0

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


# The deploy harnesses spend the same live Tavily allowance people do. On
# 2026-09-06 they were three quarters of the month's searches: the journey
# sweep and the search harness both run on every deploy and both ask real
# questions of a real provider. Tavily bills an advanced search at two credits
# and a basic one at one, and a question may take up to SEARCH_MAX_ROUNDS
# separate searches - the account is charged once for the question, the
# provider once per round, which is why the real spend ran so far ahead of the
# per-account counters.
#
# Neither harness asserts anything that reads the extra depth or the later
# rounds: they check which tool ran and how the answer is shaped.
def test_a_harness_search_asks_for_the_cheap_depth():
    from backend.search.tavily import TavilySearchProvider
    from backend.search.types import frugal_search

    provider = TavilySearchProvider(api_key="k", search_depth="advanced")
    token = frugal_search.set(True)
    try:
        assert provider._payload_depth() == "basic"
    finally:
        frugal_search.reset(token)
    assert provider._payload_depth() == "advanced"


def test_a_person_keeps_the_depth_the_deployment_configured():
    from backend.search.tavily import TavilySearchProvider

    assert TavilySearchProvider(api_key="k", search_depth="advanced")._payload_depth() == "advanced"
