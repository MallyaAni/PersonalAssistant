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
    """Track one provider's daily call count without retaining search text."""

    # Configure the durable counter used by short-lived stdio MCP processes.
    def __init__(self, path: str, provider: str, daily_limit: int) -> None:
        self.path = Path(path)
        self.provider = provider
        self.daily_limit = daily_limit

    # Reserve one call atomically, failing before provider work at the limit.
    async def consume(self, now: datetime | None = None) -> None:
        quota_day = (now or datetime.now(UTC)).astimezone(_GOOGLE_RESET_ZONE).date()
        await asyncio.to_thread(self._consume_sync, quota_day.isoformat())

    # Return a reservation whose call never produced a usable result.
    #
    # The budget exists to bound real provider usage, so an attempt that failed
    # or was refused must not spend a slot. Without this, a provider that is
    # rejecting every request still exhausts the local budget, and the limiter
    # keeps blocking after the provider itself recovers.
    async def release(self, now: datetime | None = None) -> None:
        quota_day = (now or datetime.now(UTC)).astimezone(_GOOGLE_RESET_ZONE).date()
        await asyncio.to_thread(self._release_sync, quota_day.isoformat())

    # Decrement today's counter without letting it fall below zero.
    def _release_sync(self, quota_day: str) -> None:
        if not self.path.exists():
            return
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE daily_search_quota
                SET request_count = request_count - 1
                WHERE provider = ? AND quota_day = ? AND request_count > 0
                """,
                (self.provider, quota_day),
            )
            connection.commit()

    # Commit one counter increment under SQLite's cross-process write lock.
    def _consume_sync(self, quota_day: str) -> None:
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
            if used >= self.daily_limit:
                connection.rollback()
                raise SearchQuotaExceededError(
                    f"{self.provider} daily search budget is exhausted"
                )
            connection.execute(
                """
                INSERT INTO daily_search_quota(provider, quota_day, request_count)
                VALUES (?, ?, 1)
                ON CONFLICT(provider, quota_day)
                DO UPDATE SET request_count = request_count + 1
                """,
                (self.provider, quota_day),
            )
            connection.commit()
