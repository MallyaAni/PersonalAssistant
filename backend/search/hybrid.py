"""Application-owned provider policy for free web-search capacity."""

import asyncio
import logging
import re
from urllib.parse import urlsplit, urlunsplit

from backend.core.interfaces import SearchProvider
from backend.search.types import SearchResult, SearchResults

logger = logging.getLogger(__name__)
_CROSS_CHECK = re.compile(
    r"\b(?:cross[- ]?check|double[- ]?check|verify|corroborate|"
    r"compare\s+(?:multiple|independent)\s+sources)\b",
    re.IGNORECASE,
)


# Detect explicit requests that justify spending both providers' free quota.
def requires_cross_check(query: str) -> bool:
    return bool(_CROSS_CHECK.search(query))


# Normalize a URL enough to deduplicate equivalent provider results.
def _url_key(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.strip().lower()
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower().removeprefix("www."),
            parts.path.rstrip("/"),
            parts.query,
            "",
        )
    )


# Merge provider results in order while retaining source attribution.
def _merge_results(
    groups: list[tuple[SearchResult, ...]],
    limit: int,
) -> tuple[SearchResult, ...]:
    merged: list[SearchResult] = []
    seen: set[str] = set()
    for group in groups:
        for result in group:
            key = _url_key(result.url)
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)
            if len(merged) >= limit:
                return tuple(merged)
    return tuple(merged)


class HybridSearchProvider(SearchProvider):
    """Prefer Google research, fall back to Tavily, and cross-check on request."""

    # Configure the provider order and one shared result budget.
    def __init__(
        self,
        primary: SearchProvider,
        fallback: SearchProvider,
        max_results: int,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.max_results = max_results

    # Enable search whenever at least one free provider is configured.
    def is_enabled(self) -> bool:
        return self.primary.is_enabled() or self.fallback.is_enabled()

    # Apply deterministic normal, fallback, or dual-provider search policy.
    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> SearchResults:
        bounded = max(1, min(max_results or self.max_results, self.max_results))
        if requires_cross_check(query):
            return await self._cross_check(query, bounded)
        if self.primary.is_enabled():
            try:
                found = await self.primary.search(query, bounded)
                if found.results:
                    return found
            except Exception:
                logger.warning(
                    "Primary web-search provider failed; trying fallback",
                    exc_info=True,
                )
        if self.fallback.is_enabled():
            return await self.fallback.search(query, bounded)
        raise RuntimeError("No web-search provider is available.")

    # Query every configured provider once and merge whatever succeeds.
    async def _cross_check(self, query: str, limit: int) -> SearchResults:
        providers = [
            provider
            for provider in (self.primary, self.fallback)
            if provider.is_enabled()
        ]
        if not providers:
            raise RuntimeError("No web-search provider is available.")
        outcomes = await asyncio.gather(
            *(provider.search(query, limit) for provider in providers),
            return_exceptions=True,
        )
        successes = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, SearchResults) and outcome.results
        ]
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                logger.warning("Cross-check provider failed", exc_info=outcome)
        if not successes:
            raise RuntimeError("Every web-search provider failed.")
        return SearchResults(
            query=query,
            results=_merge_results(
                [success.results for success in successes],
                limit,
            ),
            provider="+".join(success.provider for success in successes),
        )
