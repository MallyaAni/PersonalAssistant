"""Brave Search API as a web-search provider.

Chosen 2026-08-25 when Google's Custom Search JSON API turned out to be closed
to new customers and the Tavily key had spent its month. Brave's Search plan
is $5 per 1,000 requests with $5 of credit a month, metered in dollars: its
rate-limit headers report the monthly window as `0;w=2678400`, i.e. nothing
on the wire stops at the credit's edge. The local monthly quota below is what
does, held under the credit so the card on file is never charged.

Results are classic web hits - title, URL, a 200-350 character description -
fresher and broader than Tavily's but thinner per result; Tavily returns
extracted page text. The chain in the internet server takes that into
account by order, not by mixing.
"""

from __future__ import annotations

import httpx

from backend.core.interfaces import SearchProvider
from backend.search.quota import SearchQuotaExceededError, SQLiteMonthlySearchQuota
from backend.search.types import SearchResult, SearchResults

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
# The provider's own "no more this period": 429 is also its per-second
# limiter, so a body is consulted before treating one as the month.
_QUOTA_STATUSES = frozenset({402, 429})


class BraveSearchProvider(SearchProvider):
    """Bounded, quota-guarded web search against Brave's index."""

    def __init__(
        self,
        api_key: str | None,
        max_results: int,
        timeout_seconds: float,
        max_content_chars: int,
        quota: SQLiteMonthlySearchQuota | None = None,
        search_lang: str = "en",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or None
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self.max_content_chars = max_content_chars
        self.quota = quota
        self.search_lang = search_lang
        self.client = client

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, max_results: int | None = None) -> SearchResults:
        if not self.is_enabled():
            raise RuntimeError("Brave Search is not configured.")
        bounded = max(1, min(max_results or self.max_results, 20))
        if self.quota is not None:
            await self.quota.consume()
        params = {"q": query, "count": bounded, "search_lang": self.search_lang}
        headers = {"X-Subscription-Token": self.api_key, "Accept": "application/json"}
        try:
            if self.client is not None:
                response = await self.client.get(_ENDPOINT, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(_ENDPOINT, params=params, headers=headers)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            if self.quota is not None:
                await self.quota.release()
            if exc.response.status_code in _QUOTA_STATUSES and _looks_like_the_month(exc.response):
                raise SearchQuotaExceededError("brave monthly plan is exhausted") from exc
            raise
        except Exception:
            if self.quota is not None:
                await self.quota.release()
            raise
        raw = ((body.get("web") or {}).get("results") if isinstance(body, dict) else None) or []
        results: list[SearchResult] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            snippets = [str(item.get("description") or "").strip()]
            snippets.extend(str(s).strip() for s in (item.get("extra_snippets") or []) if s)
            content = " ".join(s for s in snippets if s)[: self.max_content_chars]
            results.append(
                SearchResult(title=title, url=url, content=content, score=None, provider="brave")
            )
            if len(results) >= bounded:
                break
        return SearchResults(query=query, results=tuple(results), provider="brave")


# A 429 carrying a per-second limiter is a retry; one carrying the plan is
# the month. Brave names the difference in the body, and 402 is always the plan.
def _looks_like_the_month(response: httpx.Response) -> bool:
    if response.status_code == 402:
        return True
    text = response.text.lower()
    return any(word in text for word in ("quota", "plan", "subscription", "credit", "usage limit"))
