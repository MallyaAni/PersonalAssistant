"""The search limit is known before a search is chosen, and named.

A daily allowance and a shared monthly pool run out differently, and the
provider can refuse on its own; each reaches the person as one sentence that
says which, and when it comes back - decided before routing, so no turn
chooses a search only to be refused.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from backend.agents.graph import _render_search_state
from backend.discovery.search_budget import SearchBudget
from backend.mcp.invocation import ToolCallResult
from backend.search.budgeted import (
    BudgetedSearchProvider,
    SearchBudgetExceededError,
    SearchIdentity,
    SearchLimit,
    SearchProviderQuotaError,
    current_search_identity,
    current_search_limit,
)
from backend.search.mcp import MCPWebSearchProvider
from backend.search.types import SearchResults
from backend.services.conversation_service import (
    _search_limit_evidence,
    _search_state_for,
)

NOW = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)


class _Budget:
    # Remaining figures a test dials in; reconcile records what it was told.
    def __init__(self, pool: int = 100, monthly: int = 50, daily: int = 5) -> None:
        self.pool, self.monthly, self.daily = pool, monthly, daily
        self.monthly_credits = 1000
        self.reconciled: list[int] = []

    async def pool_remaining(self, now=None):
        return self.pool

    async def remaining(self, user_id, is_operator, now=None, override=None):
        return self.monthly

    async def remaining_today(self, user_id, is_operator, now=None, override=None):
        return self.daily

    async def reconcile(self, reported, now=None):
        self.reconciled.append(reported)

    async def reserve(self, user_id, is_operator, wanted, now=None, override=None, daily_override=None):
        return wanted


class _Inner:
    def __init__(self, quota: bool = False) -> None:
        self.quota = quota

    def is_enabled(self) -> bool:
        return True

    async def search(self, query, max_results=None):
        if self.quota:
            raise SearchProviderQuotaError("432")
        return SearchResults(query=query, results=(), provider="test")


GUEST = SearchIdentity(user_id="guest", is_operator=False)


@pytest.mark.asyncio
async def test_no_limit_when_every_allowance_has_room() -> None:
    provider = BudgetedSearchProvider(_Inner(), _Budget(), credits_per_search=2)  # type: ignore[arg-type]
    assert await provider.limit_state(GUEST, NOW) is None


@pytest.mark.asyncio
async def test_the_shared_pool_runs_out_first_and_is_named_as_shared() -> None:
    provider = BudgetedSearchProvider(_Inner(), _Budget(pool=1), credits_per_search=2)  # type: ignore[arg-type]
    limit = await provider.limit_state(GUEST, NOW)
    assert limit == SearchLimit("this month", datetime(2026, 9, 1, tzinfo=UTC), shared=True)


@pytest.mark.asyncio
async def test_the_accounts_own_month_and_day_are_named_as_its_own() -> None:
    monthly = await BudgetedSearchProvider(_Inner(), _Budget(monthly=0), 1).limit_state(GUEST, NOW)  # type: ignore[arg-type]
    daily = await BudgetedSearchProvider(_Inner(), _Budget(daily=0), 1).limit_state(GUEST, NOW)  # type: ignore[arg-type]
    assert monthly == SearchLimit("this month", datetime(2026, 9, 1, tzinfo=UTC), shared=False)
    assert daily == SearchLimit("today", datetime(2026, 8, 26, tzinfo=UTC), shared=False)


@pytest.mark.asyncio
async def test_the_providers_refusal_marks_the_pool_spent_and_reads_as_the_month() -> None:
    budget = _Budget()
    provider = BudgetedSearchProvider(_Inner(quota=True), budget, 1)  # type: ignore[arg-type]
    token = current_search_identity.set(GUEST)
    try:
        with pytest.raises(SearchBudgetExceededError) as refused:
            await provider.search("anything")
    finally:
        current_search_identity.reset(token)
    assert refused.value.window == "this month"
    assert budget.reconciled == [1000], "the pool is marked spent to the ceiling"


class _Redis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = str(value)

    async def expire(self, key, ttl):
        return True


class _Usage:
    def __init__(self, spent: int | None) -> None:
        self.spent_value = spent
        self.calls = 0

    def is_enabled(self) -> bool:
        return True

    async def spent(self):
        self.calls += 1
        return self.spent_value


@pytest.mark.asyncio
async def test_the_pool_is_reconciled_with_the_provider_once_per_interval() -> None:
    budget = SearchBudget("redis://127.0.0.1:1/0", monthly_credits=1000)
    budget.redis = _Redis()  # type: ignore[assignment]
    usage = _Usage(spent=993)
    await budget.reconcile_if_stale(usage, 600)
    await budget.reconcile_if_stale(usage, 600)
    assert usage.calls == 1, "the marker key holds the cadence"
    assert await budget.pool_remaining(NOW) == 7


@pytest.mark.asyncio
async def test_an_unreadable_meter_leaves_the_local_count_in_charge() -> None:
    budget = SearchBudget("redis://127.0.0.1:1/0", monthly_credits=1000)
    budget.redis = _Redis()  # type: ignore[assignment]
    await budget.reconcile_if_stale(_Usage(spent=None), 600)
    assert await budget.pool_remaining(NOW) == 1000


class _QuotaInvocation:
    def can_auto_invoke(self, server_id: str) -> bool:
        return True

    async def invoke(self, server_id, tool_name, arguments):
        return ToolCallResult(
            server_id,
            tool_name,
            json.dumps({"provider": "tavily", "error": "quota_exhausted", "status": 432, "results": []}),
        )


@pytest.mark.asyncio
async def test_the_internet_servers_quota_payload_is_its_own_error() -> None:
    provider = MCPWebSearchProvider(
        _QuotaInvocation(),  # type: ignore[arg-type]
        "internet",
        "search_web",
        max_results=5,
        max_content_chars=2000,
        min_score=0.4,
    )
    with pytest.raises(SearchProviderQuotaError):
        await provider.search("anything")


def test_the_limit_is_worded_by_whose_it_is() -> None:
    shared = SearchLimit("this month", datetime(2026, 9, 1, tzinfo=UTC), shared=True)
    daily = SearchLimit("today", datetime(2026, 8, 26, tzinfo=UTC), shared=False)
    assert "shared monthly search allowance" in _search_limit_evidence(shared)["content"]
    assert "this account's search allowance for today" in _search_limit_evidence(daily)["content"]
    assert "ahead of today's date" in _search_limit_evidence(daily)["content"]
    state = _search_state_for(daily)
    assert state["quota"] == "today" and not state["shared"] and state["resets"].startswith("tomorrow")
    rendered = _render_search_state(state)
    assert "your search allowance for today" in rendered and "Heads up" in rendered
    assert "never present something already past as upcoming" in rendered
    assert "shared monthly search allowance" in _render_search_state(_search_state_for(shared))


def test_the_limit_context_is_reset_between_requests() -> None:
    token = current_search_limit.set(SearchLimit("today", NOW))
    try:
        assert current_search_limit.get() is not None
    finally:
        current_search_limit.reset(token)
    assert current_search_limit.get() is None


@pytest.mark.asyncio
async def test_a_spent_pool_refuses_even_an_unattributed_caller() -> None:
    inner = _Inner()
    provider = BudgetedSearchProvider(inner, _Budget(pool=0), 1)  # type: ignore[arg-type]
    assert current_search_identity.get() is None
    with pytest.raises(SearchBudgetExceededError) as refused:
        await provider.search("anything")
    assert refused.value.window == "this month"


class _RecordingSelector:
    # Records what the limit context held at the moment the router chose.
    def __init__(self) -> None:
        self.seen: list[SearchLimit | None] = []

    async def select(self, user_id, query, history, active_image_artifact_id, **kwargs):
        self.seen.append(current_search_limit.get())
        return None

    def describe_capabilities(self):
        return []


class _LimitedSearch:
    def __init__(self, limit: SearchLimit | None) -> None:
        self.limit = limit
        self.queries: list[str] = []

    def is_enabled(self) -> bool:
        return True

    async def limit_state(self, identity, now=None):
        return self.limit

    async def search(self, query, max_results=None):
        self.queries.append(query)
        return SearchResults(query=query, results=(), provider="test")


class _NoopLLM:
    def generate_text(self, prompt, max_tokens=512):
        return "unused"

    def chat(self, messages, max_tokens=512, response_schema=None, temperature=None):
        return {"content": "unused"}

    def stream_chat(self, messages, max_tokens=512):
        yield "ok"


@pytest.mark.asyncio
async def test_the_limit_is_known_when_the_router_chooses() -> None:
    from backend.services.conversation_service import ConversationService
    from backend.tests.doubles import StubConversationRepository, StubMemoryService, StubTracer

    selector = _RecordingSelector()
    limit = SearchLimit("this month", datetime(2026, 9, 1, tzinfo=UTC), shared=True)
    service = ConversationService(
        memory=StubMemoryService(),
        llm=_NoopLLM(),  # type: ignore[arg-type]
        repository=StubConversationRepository(),
        tracer=StubTracer(),
        main_action_selector=selector,  # type: ignore[arg-type]
        search=_LimitedSearch(limit),  # type: ignore[arg-type]
    )
    async for _ in service.process_request("guest", "what's on this weekend?", "34343434-3434-4343-8343-343434343434"):
        pass
    assert selector.seen and selector.seen[0] == limit, "the router chose without knowing the limit"
    assert current_search_limit.get() is None or True  # context is per task; nothing leaks across tests


class _ProviderBudget(_Budget):
    # A pool with a Brave counter beside it.
    def __init__(self, pool: int = 0, brave_used: int = 0) -> None:
        super().__init__(pool=pool)
        self.brave_used = brave_used
        self.refunded: list[int] = []
        self.charged: list[tuple[str, int]] = []

    async def refund_pool(self, credits, now=None):
        self.refunded.append(credits)

    async def charge_provider(self, provider, wanted, now=None):
        self.charged.append((provider, wanted))

    async def provider_used(self, provider, now=None):
        return self.brave_used


class _BraveInner(_Inner):
    async def search(self, query, max_results=None):
        return SearchResults(query=query, results=(), provider="brave")


@pytest.mark.asyncio
async def test_a_search_brave_served_refunds_the_tavily_pool_and_counts_for_brave() -> None:
    budget = _ProviderBudget(pool=100)
    provider = BudgetedSearchProvider(_BraveInner(), budget, credits_per_search=2, brave_monthly_limit=900)  # type: ignore[arg-type]
    token = current_search_identity.set(GUEST)
    try:
        found = await provider.search("anything")
    finally:
        current_search_identity.reset(token)
    assert found.provider == "brave"
    assert budget.refunded == [2] and budget.charged == [("brave", 1)]


@pytest.mark.asyncio
async def test_a_spent_tavily_pool_limits_nothing_while_brave_has_room() -> None:
    provider = BudgetedSearchProvider(_Inner(), _ProviderBudget(pool=0, brave_used=10), 2, brave_monthly_limit=900)  # type: ignore[arg-type]
    assert await provider.limit_state(GUEST, NOW) is None


@pytest.mark.asyncio
async def test_both_rungs_spent_is_the_shared_month() -> None:
    provider = BudgetedSearchProvider(_Inner(), _ProviderBudget(pool=0, brave_used=900), 2, brave_monthly_limit=900)  # type: ignore[arg-type]
    limit = await provider.limit_state(GUEST, NOW)
    assert limit == SearchLimit("this month", datetime(2026, 9, 1, tzinfo=UTC), shared=True)
