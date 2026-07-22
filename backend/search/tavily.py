from typing import Any

import httpx

from backend.core.interfaces import SearchProvider
from backend.search.types import SearchResult, SearchResults

# Tavily accepts 0-20 results per request; clamp locally so a bad caller value
# becomes a bounded request instead of a provider-side validation error.
_PROVIDER_MAX_RESULTS = 20


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
        payload = {
            "query": query,
            "max_results": bounded,
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
            if result is not None and result.score >= self.min_score:
                parsed.append(result)

        return SearchResults(
            query=query,
            results=tuple(parsed[:bounded]),
            provider="tavily",
        )
