"""Serve a repeated search from the last answer instead of buying it twice.

Every deploy runs `sweep_journeys`, which asks the same ten live questions
("what's on in Arlington this weekend?", "how much does a PlayStation 5
cost right now?") to prove the search chain end to end. Measured on
2026-08-29: of 403 search requests this month, 344 came from those
verification runs and 59 from the people using the system - the operator's
Brave allowance was being spent almost entirely on testing, and Brave
retired its free tier in February 2026.

So an answer is kept for a short while and reused. Three properties make
that safe to do to a system whose whole discipline is "never present stale
as current":

- **short by default.** `SEARCH_CACHE_TTL_SECONDS` is 30 minutes. Prices,
  hours and listings do not turn over inside that window, and a deploy's
  repeat run lands well inside it.
- **no query text at rest.** The key is a SHA-256 of the normalized query
  and limit; the value is the results, which are public web pages. A dump
  of this file says what was fetched, never what anyone asked.
- **failures are never cached.** An empty result set is what an outage
  looks like, and caching one would turn a blip into half an hour of
  "nothing found".

It is a cache, not a store: losing it costs a search, and it prunes itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from backend.search.types import SearchResult, SearchResults

# Bounded so a long-running instance cannot grow the file without limit; the
# oldest rows go first, which is also the least useful.
MAX_ROWS = 2_000



logger = logging.getLogger(__name__)

def _key(query: str, limit: int) -> str:
    normalized = " ".join(str(query or "").split()).casefold()
    return hashlib.sha256(f"{limit}:{normalized}".encode()).hexdigest()


def _dump(results: SearchResults) -> str:
    return json.dumps(
        {
            "provider": results.provider,
            "results": [
                {
                    "title": item.title,
                    "url": item.url,
                    "content": item.content,
                    "score": item.score,
                    "provider": item.provider,
                }
                for item in results.results
            ],
        }
    )


def _load(query: str, payload: str) -> SearchResults | None:
    try:
        data = json.loads(payload)
        items = tuple(
            SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                content=str(item.get("content") or ""),
                score=item.get("score"),
                provider=item.get("provider"),
            )
            for item in data.get("results") or ()
        )
    except (ValueError, AttributeError, TypeError):
        return None
    if not items:
        return None
    return SearchResults(query=query, results=items, provider=str(data.get("provider") or "cache"))


class SQLiteSearchCache:
    """Keep one recent answer per question, across short-lived MCP processes."""

    def __init__(self, path: str, ttl_seconds: float) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(0.0, float(ttl_seconds))

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    # The stored answer for this question, or None. Never raises: a cache
    # that cannot be read is a cache miss, not a failed search.
    async def get(self, query: str, limit: int) -> SearchResults | None:
        if not self.enabled:
            return None
        try:
            payload = await asyncio.to_thread(self._get_sync, _key(query, limit))
        except Exception:
            # Broader than sqlite3.Error on purpose: `_connect` creates the
            # directory, so a read-only or full disk raises OSError, which
            # would have escaped a promise this docstring makes.
            logger.warning("Search cache unreadable; treating as a miss", exc_info=True)
            return None
        return _load(query, payload) if payload else None

    # Keep one answer. An empty result set is never kept - that is what an
    # outage looks like, and it would be served for the whole window.
    async def put(self, query: str, limit: int, results: SearchResults) -> None:
        if not self.enabled or not results.results:
            return
        try:
            await asyncio.to_thread(self._put_sync, _key(query, limit), _dump(results))
        except Exception:
            # Same reasoning as `get`: a cache that cannot be written is a
            # cache that will miss, never a search that failed.
            logger.warning("Search cache unwritable; the answer is not kept", exc_info=True)
            return

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS search_cache ("
            " cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, stored_at REAL NOT NULL)"
        )
        return connection

    def _get_sync(self, cache_key: str) -> str | None:
        if not self.path.exists():
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload, stored_at FROM search_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
            if row is None:
                return None
            if time.time() - float(row[1]) > self.ttl_seconds:
                connection.execute("DELETE FROM search_cache WHERE cache_key = ?", (cache_key,))
                connection.commit()
                return None
            return str(row[0])

    def _put_sync(self, cache_key: str, payload: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO search_cache (cache_key, payload, stored_at) VALUES (?, ?, ?)"
                " ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload,"
                " stored_at = excluded.stored_at",
                (cache_key, payload, time.time()),
            )
            connection.execute(
                "DELETE FROM search_cache WHERE cache_key NOT IN ("
                " SELECT cache_key FROM search_cache ORDER BY stored_at DESC LIMIT ?)",
                (MAX_ROWS,),
            )
            connection.commit()
