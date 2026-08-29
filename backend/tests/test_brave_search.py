"""Brave as the first rung: parsed, quota-guarded, and the chain falls through."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from backend.search.brave import BraveSearchProvider
from backend.search.hybrid import EveryProviderExhausted, HybridSearchProvider
from backend.search.quota import SearchQuotaExceededError, SQLiteMonthlySearchQuota
from backend.search.types import SearchResult, SearchResults

_BODY = {
    "web": {
        "results": [
            {"title": "Canggu events", "url": "https://www.eventbrite.com/d/indonesia--canggu/events/", "description": "What's on this weekend.", "extra_snippets": ["Friday night market."]},
            {"title": "Meetup Canggu", "url": "https://www.meetup.com/find/id--canggu/", "description": "Groups and events."},
            {"title": "", "url": "https://nothing.example", "description": "no title, dropped"},
        ]
    }
}


def _client(status: int = 200, body: dict | None = None, text: str = "") -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "k"
        assert request.url.params["q"] == "events in canggu"
        if body is not None:
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=text)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_results_carry_title_url_snippets_and_the_provider(tmp_path) -> None:
    quota = SQLiteMonthlySearchQuota(str(tmp_path / "q.sqlite3"), "brave", 5)
    provider = BraveSearchProvider("k", 5, 5.0, 500, quota=quota, client=_client(body=_BODY))
    found = await provider.search("events in canggu")
    assert found.provider == "brave"
    assert [r.url for r in found.results] == [
        "https://www.eventbrite.com/d/indonesia--canggu/events/",
        "https://www.meetup.com/find/id--canggu/",
    ]
    assert found.results[0].content == "What's on this weekend. Friday night market."
    assert found.results[0].provider == "brave" and found.results[0].score is None
    assert await quota.used() == 1


@pytest.mark.asyncio
async def test_the_local_monthly_cap_stops_before_the_call(tmp_path) -> None:
    quota = SQLiteMonthlySearchQuota(str(tmp_path / "q.sqlite3"), "brave", 1)
    provider = BraveSearchProvider("k", 5, 5.0, 500, quota=quota, client=_client(body=_BODY))
    await provider.search("events in canggu")
    with pytest.raises(SearchQuotaExceededError):
        await provider.search("events in canggu")
    assert await quota.used() == 1, "the refused call did not spend a slot"


@pytest.mark.asyncio
async def test_a_failed_call_hands_its_slot_back(tmp_path) -> None:
    quota = SQLiteMonthlySearchQuota(str(tmp_path / "q.sqlite3"), "brave", 5)
    provider = BraveSearchProvider("k", 5, 5.0, 500, quota=quota, client=_client(500, text="boom"))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.search("events in canggu")
    assert await quota.used() == 0


@pytest.mark.asyncio
async def test_the_plan_being_spent_reads_as_exhausted_a_burst_limit_does_not(tmp_path) -> None:
    quota = SQLiteMonthlySearchQuota(str(tmp_path / "q.sqlite3"), "brave", 5)
    spent = BraveSearchProvider("k", 5, 5.0, 500, quota=quota, client=_client(429, text='{"error": "quota exceeded for plan"}'))
    with pytest.raises(SearchQuotaExceededError):
        await spent.search("events in canggu")
    burst = BraveSearchProvider("k", 5, 5.0, 500, quota=quota, client=_client(429, text="rate limited: too many requests per second"))
    with pytest.raises(httpx.HTTPStatusError):
        await burst.search("events in canggu")


def test_a_missing_key_disables_the_rung() -> None:
    assert not BraveSearchProvider(None, 5, 5.0, 500).is_enabled()
    assert not BraveSearchProvider("", 5, 5.0, 500).is_enabled()


class _Rung:
    def __init__(self, name: str, *, enabled: bool = True, results: int = 1, raises: Exception | None = None) -> None:
        self.name, self.enabled, self.count, self.raises = name, enabled, results, raises
        self.calls = 0

    def is_enabled(self) -> bool:
        return self.enabled

    async def search(self, query, max_results=None):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return SearchResults(
            query=query,
            results=tuple(
                SearchResult(title=f"{self.name} {n}", url=f"https://{self.name}.example/{n}", content="x", score=None, provider=self.name)
                for n in range(self.count)
            ),
            provider=self.name,
        )


@pytest.mark.asyncio
async def test_the_first_rung_answers_and_the_others_are_not_called() -> None:
    brave, google, tavily = _Rung("brave"), _Rung("google", enabled=False), _Rung("tavily")
    chain = HybridSearchProvider(google, tavily, 5, ahead=(brave,))
    found = await chain.search("anything")
    assert found.provider == "brave" and (brave.calls, tavily.calls) == (1, 0)


@pytest.mark.asyncio
async def test_a_spent_first_rung_falls_through_to_the_next() -> None:
    brave = _Rung("brave", raises=SearchQuotaExceededError("brave monthly plan is exhausted"))
    tavily = _Rung("tavily")
    chain = HybridSearchProvider(_Rung("google", enabled=False), tavily, 5, ahead=(brave,))
    found = await chain.search("anything")
    assert found.provider == "tavily" and (brave.calls, tavily.calls) == (1, 1)


@pytest.mark.asyncio
async def test_every_rung_spent_is_named_as_such() -> None:
    refusal = httpx.HTTPStatusError(
        "432", request=httpx.Request("POST", "https://api.tavily.com/search"), response=httpx.Response(432)
    )
    brave = _Rung("brave", raises=SearchQuotaExceededError("spent"))
    tavily = _Rung("tavily", raises=refusal)
    chain = HybridSearchProvider(_Rung("google", enabled=False), tavily, 5, ahead=(brave,))
    with pytest.raises(EveryProviderExhausted):
        await chain.search("anything")


@pytest.mark.asyncio
async def test_an_empty_first_answer_is_not_the_final_answer() -> None:
    brave, tavily = _Rung("brave", results=0), _Rung("tavily")
    chain = HybridSearchProvider(_Rung("google", enabled=False), tavily, 5, ahead=(brave,))
    found = await chain.search("anything")
    assert found.provider == "tavily"


@pytest.mark.asyncio
async def test_the_monthly_counter_rolls_over_by_calendar_month(tmp_path) -> None:
    quota = SQLiteMonthlySearchQuota(str(tmp_path / "q.sqlite3"), "brave", 1)
    august = datetime(2026, 8, 25, tzinfo=UTC)
    september = datetime(2026, 9, 1, tzinfo=UTC)
    await quota.consume(august)
    with pytest.raises(SearchQuotaExceededError):
        await quota.consume(august)
    await quota.consume(september)
    assert await quota.used(september) == 1


@pytest.mark.asyncio
async def test_the_internet_server_reports_the_brave_meter(monkeypatch, tmp_path) -> None:
    from backend.mcp.servers import internet

    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    monkeypatch.setenv("BRAVE_SEARCH_MONTHLY_LIMIT", "900")
    # Pinned rather than inherited: this asserts what the meter reports for a
    # given order, and the machine's own order changed on 2026-08-29 (Tavily
    # first, since Brave began metering) which failed it for no defect.
    monkeypatch.setenv("SEARCH_PROVIDER_ORDER", "brave,google,tavily")
    monkeypatch.setenv("BRAVE_SEARCH_QUOTA_DB_PATH", str(tmp_path / "q.sqlite3"))
    await SQLiteMonthlySearchQuota(str(tmp_path / "q.sqlite3"), "brave", 900).consume()

    async def report():
        return {"plan": "Researcher", "spent": 1000, "limit": 1000, "remaining": 0}

    monkeypatch.setattr(internet, "_usage_report", report)
    payload = json.loads(await internet.search_credits())
    assert payload["brave"] == {"used": 1, "limit": 900, "remaining": 899, "period": "this calendar month, counted locally under the free credit"}
    assert payload["order"] == "brave,google,tavily"
