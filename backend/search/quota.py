"""Persist non-content provider budgets across short-lived MCP processes."""

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_GOOGLE_RESET_ZONE = ZoneInfo("America/Los_Angeles")


class SearchQuotaExceededError(RuntimeError):
    """Raised before a provider call would exceed its configured free budget."""


class SQLiteDailySearchQuota:
    """Track one provider's daily billable units without retaining search text."""

    # Configure the durable counter used by short-lived stdio MCP processes.
    def __init__(self, path: str, provider: str, daily_limit: int) -> None:
        self.path = Path(path)
        self.provider = provider
        self.daily_limit = daily_limit

    # The period a moment falls in - a calendar day in the provider's zone.
    def _period(self, now: datetime | None) -> str:
        return (now or datetime.now(UTC)).astimezone(_GOOGLE_RESET_ZONE).date().isoformat()

    # Reserve a bounded number of billable units atomically before provider work.
    async def consume(self, now: datetime | None = None, count: int = 1) -> None:
        if count < 1:
            raise ValueError("quota consumption must be positive")
        await asyncio.to_thread(self._consume_sync, self._period(now), count)

    # Calls counted in the current period, for the meter.
    async def used(self, now: datetime | None = None) -> int:
        return await asyncio.to_thread(self._used_sync, self._period(now))

    def _used_sync(self, quota_day: str) -> int:
        if not self.path.exists():
            return 0
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            row = connection.execute(
                "SELECT request_count FROM daily_search_quota WHERE provider = ? AND quota_day = ?",
                (self.provider, quota_day),
            ).fetchone()
        return int(row[0]) if row else 0

    # Return a reservation whose call never produced a usable result.
    #
    # The budget exists to bound real provider usage, so an attempt that failed
    # or was refused must not spend a slot. Without this, a provider that is
    # rejecting every request still exhausts the local budget, and the limiter
    # keeps blocking after the provider itself recovers.
    async def release(self, now: datetime | None = None, count: int = 1) -> None:
        if count < 1:
            raise ValueError("quota release must be positive")
        await asyncio.to_thread(self._release_sync, self._period(now), count)

    # Replace a pre-call reservation with the provider's observed billable usage.
    async def reconcile(
        self,
        reserved_count: int,
        actual_count: int,
        now: datetime | None = None,
    ) -> None:
        if reserved_count < 1 or actual_count < 0:
            raise ValueError("quota reconciliation counts are invalid")
        await asyncio.to_thread(
            self._reconcile_sync,
            self._period(now),
            reserved_count,
            actual_count,
        )

    # Decrement today's counter by a bounded amount without crossing zero.
    def _release_sync(self, quota_day: str, count: int) -> None:
        if not self.path.exists():
            return
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE daily_search_quota
                SET request_count = MAX(0, request_count - ?)
                WHERE provider = ? AND quota_day = ? AND request_count > 0
                """,
                (count, self.provider, quota_day),
            )
            connection.commit()

    # Commit one multi-unit counter increment under SQLite's write lock.
    def _consume_sync(self, quota_day: str, count: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS daily_search_quota (
                    provider TEXT NOT NULL,
                    quota_day TEXT NOT NULL,
                    request_count INTEGER NOT NULL,
                    PRIMARY KEY (provider, quota_day)
                )
                """)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_count
                FROM daily_search_quota
                WHERE provider = ? AND quota_day = ?
                """,
                (self.provider, quota_day),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used + count > self.daily_limit:
                connection.rollback()
                raise SearchQuotaExceededError(
                    f"{self.provider} daily search budget is exhausted"
                )
            connection.execute(
                """
                INSERT INTO daily_search_quota(provider, quota_day, request_count)
                VALUES (?, ?, ?)
                ON CONFLICT(provider, quota_day)
                DO UPDATE SET request_count = request_count + excluded.request_count
                """,
                (self.provider, quota_day, count),
            )
            connection.commit()

    # Record actual provider usage even when it exceeded the pre-call reservation.
    def _reconcile_sync(
        self,
        quota_day: str,
        reserved_count: int,
        actual_count: int,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO daily_search_quota(provider, quota_day, request_count)
                VALUES (?, ?, ?)
                ON CONFLICT(provider, quota_day)
                DO UPDATE SET request_count = MAX(
                    0,
                    request_count + ?
                )
                """,
                (
                    self.provider,
                    quota_day,
                    actual_count,
                    actual_count - reserved_count,
                ),
            )
            connection.commit()


class SQLiteMonthlySearchQuota(SQLiteDailySearchQuota):
    """The same counter over a calendar month, in UTC.

    Brave meters its free credit per month in dollars, and its headers promise
    no stop at the credit's edge; this is the stop. Rows share the daily
    table, keyed by `YYYY-MM`, so one file holds every provider's budget.
    """

    def __init__(self, path: str, provider: str, monthly_limit: int) -> None:
        super().__init__(path, provider, monthly_limit)
        self.monthly_limit = monthly_limit

    def _period(self, now: datetime | None) -> str:
        return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m")


class EveryQuota:
    """Budgets that must all permit a call - a daily rate and a monthly ceiling.

    Google's Search grounding is free only above a billing switch, and only
    up to a monthly allowance (5,000 search queries a month on the Gemini 3.x
    family as of 2026-08-29, then $14 per 1,000). A daily cap alone cannot
    hold that line: 450 a day is 13,500 a month. Both are counted, and a
    call that the second budget refuses gives the first its credit back, so
    a refusal costs nothing.
    """

    def __init__(self, *quotas: SQLiteDailySearchQuota) -> None:
        self.quotas = tuple(quotas)

    # Reserve the same billable units against every budget, or none.
    async def consume(self, now: datetime | None = None, count: int = 1) -> None:
        taken: list[SQLiteDailySearchQuota] = []
        for quota in self.quotas:
            try:
                await quota.consume(now, count=count)
            except SearchQuotaExceededError:
                for spent in reversed(taken):
                    await spent.release(now, count=count)
                raise
            taken.append(quota)

    # Give back the same billable units to every budget that took them.
    async def release(self, now: datetime | None = None, count: int = 1) -> None:
        for quota in reversed(self.quotas):
            await quota.release(now, count=count)

    # Reconcile every budget to the billable usage reported by the provider.
    async def reconcile(
        self,
        reserved_count: int,
        actual_count: int,
        now: datetime | None = None,
    ) -> None:
        for quota in self.quotas:
            await quota.reconcile(reserved_count, actual_count, now)

    # The first budget's count, which is the one a rate is read against.
    async def used(self, now: datetime | None = None) -> int:
        return await self.quotas[0].used(now) if self.quotas else 0
