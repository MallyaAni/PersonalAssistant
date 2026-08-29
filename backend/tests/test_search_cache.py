"""The search cache: same question inside the window costs nothing, no
question is written to disk, and an empty answer is never kept."""

import asyncio
import json
import sqlite3

import pytest

from backend.search.cache import MAX_ROWS, SQLiteSearchCache, _key
from backend.search.types import SearchResult, SearchResults


def _results(query: str = "ps5 price", provider: str = "brave") -> SearchResults:
    return SearchResults(
        query=query,
        provider=provider,
        results=(
            SearchResult(title="PS5 at Best Buy", url="https://example.com/a", content="$499", score=0.9, provider=provider),
            SearchResult(title="PS5 deals", url="https://example.com/b", content="$449 refurb", score=0.7, provider=None),
        ),
    )


@pytest.mark.asyncio
async def test_a_repeat_question_inside_the_window_is_served_from_the_answer(tmp_path):
    cache = SQLiteSearchCache(str(tmp_path / "c.sqlite3"), ttl_seconds=600)
    assert await cache.get("ps5 price", 5) is None
    await cache.put("ps5 price", 5, _results())
    found = await cache.get("ps5 price", 5)
    assert found is not None
    assert [r.url for r in found.results] == ["https://example.com/a", "https://example.com/b"]
    assert found.results[0].title == "PS5 at Best Buy" and found.results[0].score == 0.9
    assert found.provider == "brave" and found.query == "ps5 price"
    # Wording and case do not make it a different question; the limit does.
    assert await cache.get("  PS5   Price ", 5) is not None
    assert await cache.get("ps5 price", 3) is None


@pytest.mark.asyncio
async def test_an_expired_answer_is_a_miss_and_is_dropped(tmp_path):
    path = tmp_path / "c.sqlite3"
    cache = SQLiteSearchCache(str(path), ttl_seconds=0.05)
    await cache.put("ps5 price", 5, _results())
    await asyncio.sleep(0.06)
    assert await cache.get("ps5 price", 5) is None
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from search_cache").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_an_empty_answer_is_never_kept(tmp_path):
    # An outage looks like an empty result set; caching one would serve the
    # outage for the whole window.
    cache = SQLiteSearchCache(str(tmp_path / "c.sqlite3"), ttl_seconds=600)
    await cache.put("ps5 price", 5, SearchResults(query="ps5 price", results=(), provider="brave"))
    assert await cache.get("ps5 price", 5) is None


@pytest.mark.asyncio
async def test_no_question_is_written_to_disk(tmp_path):
    path = tmp_path / "c.sqlite3"
    cache = SQLiteSearchCache(str(path), ttl_seconds=600)
    await cache.put("did the merger go through", 5, _results(query="did the merger go through"))
    raw = path.read_bytes()
    assert b"merger" not in raw
    # The results themselves are public web pages and are kept as they are.
    assert b"Best Buy" in raw
    assert _key("did the merger go through", 5) != _key("did the merger go through", 4)


@pytest.mark.asyncio
async def test_switched_off_by_a_zero_window(tmp_path):
    cache = SQLiteSearchCache(str(tmp_path / "c.sqlite3"), ttl_seconds=0)
    assert not cache.enabled
    await cache.put("ps5 price", 5, _results())
    assert await cache.get("ps5 price", 5) is None
    assert not (tmp_path / "c.sqlite3").exists()


@pytest.mark.asyncio
async def test_an_unreadable_cache_is_a_miss_not_a_failure(tmp_path):
    path = tmp_path / "c.sqlite3"
    path.write_bytes(b"this is not a database")
    cache = SQLiteSearchCache(str(path), ttl_seconds=600)
    assert await cache.get("ps5 price", 5) is None
    await cache.put("ps5 price", 5, _results())  # must not raise


@pytest.mark.asyncio
async def test_the_file_cannot_grow_without_limit(tmp_path):
    path = tmp_path / "c.sqlite3"
    cache = SQLiteSearchCache(str(path), ttl_seconds=600)
    for index in range(MAX_ROWS + 20):
        await cache.put(f"question {index}", 5, _results())
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from search_cache").fetchone()[0] <= MAX_ROWS
    # The newest survive.
    assert await cache.get(f"question {MAX_ROWS + 19}", 5) is not None


@pytest.mark.asyncio
async def test_a_corrupt_payload_is_a_miss(tmp_path):
    path = tmp_path / "c.sqlite3"
    cache = SQLiteSearchCache(str(path), ttl_seconds=600)
    await cache.put("ps5 price", 5, _results())
    with sqlite3.connect(path) as db:
        db.execute("update search_cache set payload = ?", (json.dumps({"results": "not a list"}),))
        db.commit()
    assert await cache.get("ps5 price", 5) is None


# --- Two budgets at once, for a provider whose free allowance is monthly ---


@pytest.mark.asyncio
async def test_both_budgets_must_permit_a_call_and_a_refusal_costs_nothing(tmp_path):
    """Grounding is free only to a monthly allowance, so a daily rate alone
    cannot hold the line (450 a day is 13,500 a month). A call the month
    refuses must give the day its credit back, or the day drifts down for
    calls that never happened."""
    from backend.search.quota import (
        EveryQuota,
        SearchQuotaExceededError,
        SQLiteDailySearchQuota,
        SQLiteMonthlySearchQuota,
    )

    path = str(tmp_path / "q.sqlite3")
    day = SQLiteDailySearchQuota(path, "google", daily_limit=10)
    month = SQLiteMonthlySearchQuota(path, "google-month", monthly_limit=2)
    both = EveryQuota(day, month)

    await both.consume()
    await both.consume()
    assert await day.used() == 2 and await month.used() == 2

    with pytest.raises(SearchQuotaExceededError):
        await both.consume()
    # The month refused, so the day is not charged for it.
    assert await day.used() == 2
    assert await both.used() == 2

    await both.release()
    assert await day.used() == 1 and await month.used() == 1


@pytest.mark.asyncio
async def test_the_daily_rate_still_stops_a_burst(tmp_path):
    from backend.search.quota import (
        EveryQuota,
        SearchQuotaExceededError,
        SQLiteDailySearchQuota,
        SQLiteMonthlySearchQuota,
    )

    path = str(tmp_path / "q.sqlite3")
    both = EveryQuota(
        SQLiteDailySearchQuota(path, "google", daily_limit=1),
        SQLiteMonthlySearchQuota(path, "google-month", monthly_limit=100),
    )
    await both.consume()
    with pytest.raises(SearchQuotaExceededError):
        await both.consume()


# Reconcile one multi-query reservation in both daily and monthly periods.
@pytest.mark.asyncio
async def test_google_query_reservation_reconciles_both_periods(tmp_path):
    from backend.search.quota import (
        EveryQuota,
        SQLiteDailySearchQuota,
        SQLiteMonthlySearchQuota,
    )

    path = str(tmp_path / "q.sqlite3")
    day = SQLiteDailySearchQuota(path, "google", daily_limit=20)
    month = SQLiteMonthlySearchQuota(path, "google-month", monthly_limit=20)
    both = EveryQuota(day, month)

    await both.consume(count=10)
    await both.reconcile(10, 2)

    assert await day.used() == 2
    assert await month.used() == 2


# Preserve unexpected overage in the meter and refuse all later work.
@pytest.mark.asyncio
async def test_reconciliation_records_an_unexpected_query_overage(tmp_path):
    from backend.search.quota import (
        SearchQuotaExceededError,
        SQLiteMonthlySearchQuota,
    )

    quota = SQLiteMonthlySearchQuota(
        str(tmp_path / "q.sqlite3"), "google-month", monthly_limit=12
    )
    await quota.consume(count=10)
    await quota.reconcile(10, 13)

    assert await quota.used() == 13
    with pytest.raises(SearchQuotaExceededError):
        await quota.consume()
