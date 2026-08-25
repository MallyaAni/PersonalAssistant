from typing import Any

import httpx

from backend.core.interfaces import SearchProvider
from backend.search.types import SearchResult, SearchResults

# Tavily accepts 0-20 results per request; clamp locally so a bad caller value
# becomes a bounded request instead of a provider-side validation error.
_PROVIDER_MAX_RESULTS = 20
# Smallest candidate pool requested regardless of how few results the caller
# wants, so the relevance floor always has alternatives to choose between.
_MIN_CANDIDATE_POOL = 5


class TavilySearchProvider(SearchProvider):
    """Tavily HTTP search backend.

    Returned titles, URLs, and snippets are untrusted third-party content and
    must be treated as quoted data by every caller.
    """

    # Configure the Tavily endpoint; an absent key disables search entirely.
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        max_results: int,
        timeout_seconds: float,
        max_content_chars: int,
        min_score: float = 0.0,
        search_depth: str = "basic",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self.max_content_chars = max_content_chars
        self.min_score = min_score
        self.search_depth = search_depth
        self._client = client

    # Search is opt-in: without a configured key the caller must skip it.
    def is_enabled(self) -> bool:
        return bool(self.api_key)

    # Keep one untrusted result only when its required fields are well formed.
    def _parse_result(self, raw: Any) -> SearchResult | None:
        if not isinstance(raw, dict):
            return None
        title = raw.get("title")
        url = raw.get("url")
        content = raw.get("content")
        if not isinstance(title, str) or not isinstance(url, str):
            return None
        if not isinstance(content, str):
            content = ""
        score = raw.get("score")
        return SearchResult(
            title=title,
            url=url,
            # Truncate so one verbose page cannot dominate the prompt budget.
            content=content[: self.max_content_chars],
            score=float(score) if isinstance(score, (int, float)) else 0.0,
            provider="tavily",
        )

    # Execute one bounded query against Tavily and return ranked results.
    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> SearchResults:
        if not self.is_enabled():
            raise RuntimeError(
                "Search is not configured; set SEARCH_API_KEY to enable it."
            )

        requested = self.max_results if max_results is None else max_results
        bounded = max(1, min(requested, _PROVIDER_MAX_RESULTS))
        # Ask for a candidate pool rather than exactly what the caller wants.
        # Tavily's scores are not ordered, so a small request can return only
        # low-scoring rows and the relevance floor then empties the list: asking
        # for two results returned two rows scoring 0.04, and nothing survived,
        # while asking for five returned three above the floor. Over-fetching
        # gives the filter something to choose from; the caller's limit is
        # applied afterwards.
        fetch = max(bounded, _MIN_CANDIDATE_POOL)
        payload = {
            "query": query,
            "max_results": fetch,
            "search_depth": self.search_depth,
        }
        # The key travels in the Authorization header, never in the body or logs.
        headers = {"Authorization": f"Bearer {self.api_key}"}

        if self._client is not None:
            response = await self._client.post(
                f"{self.base_url}/search",
                json=payload,
                headers=headers,
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    json=payload,
                    headers=headers,
                )
        response.raise_for_status()

        body = response.json()
        raw_results = body.get("results") if isinstance(body, dict) else None
        parsed: list[SearchResult] = []
        for raw in raw_results or []:
            result = self._parse_result(raw)
            # Low-relevance hits are dropped rather than quoted to the model as
            # authoritative web data.
            if (
                result is not None
                and result.score is not None
                and result.score >= self.min_score
            ):
                parsed.append(result)

        return SearchResults(
            query=query,
            results=tuple(parsed[:bounded]),
            provider="tavily",
        )


# Where Tavily reports what the key has actually spent.
_USAGE_PATH = "/usage"

# Response shapes seen from Tavily's usage endpoint, most specific first. The
# provider is free to change this, and a wrong guess must not corrupt the local
# count, so an unrecognised body reports nothing rather than zero — zero would
# read as "nothing spent" and silently refill the pool.
_USAGE_PATHS: tuple[tuple[str, ...], ...] = (
    ("account", "plan_usage"),
    ("account", "current_plan_usage"),
    ("key", "usage"),
    ("usage",),
)


# Read one integer from a nested response without assuming the shape exists.
def _dig(payload: Any, path: tuple[str, ...]) -> int | None:
    current: Any = payload
    for step in path:
        if not isinstance(current, dict) or step not in current:
            return None
        current = current[step]
    if isinstance(current, bool) or not isinstance(current, int | float):
        return None
    return int(current)


class TavilyUsageClient:
    """Report what Tavily says the key has spent this billing period.

    The local pool counts what this system reserved, which drifts from the real
    balance in both directions: another tool sharing the key spends without us
    knowing, and a query charged locally that then fails in flight costs nothing
    while we still count it. Reconciling against the provider closes both gaps.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.client = client

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    # Credits spent this period, or None when it cannot be established.
    #
    # None rather than 0 throughout: every failure here means "unknown", and a
    # caller treating unknown as zero would reset the pool to full on any
    # outage, turning a monitoring problem into an overspend.
    async def spent(self) -> int | None:
        payload = await self._payload()
        if payload is None:
            return None
        return _spent_in(payload)

    # The plan's position this billing period - spent, limit, remaining -
    # for whoever needs to know whether the key is about to run out: the
    # admin page and the internet server's `search_credits` tool. None when
    # the provider could not be asked; a limit of None when the provider
    # reports no ceiling.
    async def report(self) -> dict[str, Any] | None:
        payload = await self._payload()
        if payload is None:
            return None
        spent = _spent_in(payload)
        if spent is None:
            return None
        account = payload.get("account")
        account = account if isinstance(account, dict) else {}
        limit = _dig(payload, ("account", "plan_limit"))
        remaining = (limit - spent) if isinstance(limit, int) and limit >= 0 else None
        return {
            "plan": str(account.get("current_plan") or "") or None,
            "spent": spent,
            "limit": limit if isinstance(limit, int) else None,
            "remaining": max(0, remaining) if remaining is not None else None,
        }

    # The usage body as the provider returned it, or None when it cannot be
    # fetched or is not an object.
    async def _payload(self) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}{_USAGE_PATH}"
        try:
            if self.client is not None:
                response = await self.client.get(url, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None


# Credits spent, read from whichever of the known shapes the body carries.
def _spent_in(payload: dict[str, Any]) -> int | None:
    for path in _USAGE_PATHS:
        found = _dig(payload, path)
        if found is not None and found >= 0:
            return found
    return None
