import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest

from backend.search.quota import (
    SearchQuotaExceededError,
    SQLiteDailySearchQuota,
)


# Verify the counter blocks calls after the daily budget is reserved.
@pytest.mark.asyncio
async def test_daily_search_quota_enforces_limit_without_storing_queries(
    tmp_path,
) -> None:
    path = tmp_path / "search-quota.sqlite3"
    quota = SQLiteDailySearchQuota(str(path), "google", daily_limit=2)
    now = datetime(2026, 7, 23, 16, tzinfo=UTC)

    await quota.consume(now)
    await quota.consume(now)
    with pytest.raises(SearchQuotaExceededError, match="budget is exhausted"):
        await quota.consume(now)

    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            "SELECT provider, quota_day, request_count FROM daily_search_quota"
        ).fetchall()
    assert stored == [("google", "2026-07-23", 2)]


# Verify the budget resets on the next Pacific calendar day.
@pytest.mark.asyncio
async def test_daily_search_quota_resets_on_google_budget_day(tmp_path) -> None:
    quota = SQLiteDailySearchQuota(
        str(tmp_path / "search-quota.sqlite3"),
        "google",
        daily_limit=1,
    )

    await quota.consume(datetime(2026, 7, 23, 6, 30, tzinfo=UTC))
    await quota.consume(datetime(2026, 7, 23, 7, 30, tzinfo=UTC))


# Verify concurrent processes cannot reserve more calls than the configured cap.
@pytest.mark.asyncio
async def test_daily_search_quota_reserves_concurrent_calls_atomically(
    tmp_path,
) -> None:
    quota = SQLiteDailySearchQuota(
        str(tmp_path / "search-quota.sqlite3"),
        "google",
        daily_limit=1,
    )
    now = datetime(2026, 7, 23, 16, tzinfo=UTC)

    outcomes = await asyncio.gather(
        quota.consume(now),
        quota.consume(now),
        return_exceptions=True,
    )

    assert sum(outcome is None for outcome in outcomes) == 1
    assert (
        sum(isinstance(outcome, SearchQuotaExceededError) for outcome in outcomes) == 1
    )
