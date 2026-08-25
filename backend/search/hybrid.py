"""Application-owned provider policy for free web-search capacity."""

import asyncio
import logging
import re
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.core.interfaces import SearchProvider
from backend.search.quota import SearchQuotaExceededError
from backend.search.types import SearchResult, SearchResults


class EveryProviderExhausted(RuntimeError):
    """Each configured provider has spent its budget for the period."""


# A provider answering with its plan spent (Tavily 432; 402 generally).
_PLAN_STATUSES = frozenset({402, 432})

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
        ahead: tuple[SearchProvider, ...] = (),
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.max_results = max_results
        # Providers tried before the primary, in order - Brave since
        # 2026-08-25. Each falls through on failure, on an exhausted budget,
        # or on an empty answer; the operator's chain is order, not mixing.
        self.ahead = tuple(ahead)

    # Every provider in the order it is tried.
    @property
    def chain(self) -> tuple[SearchProvider, ...]:
        return (*self.ahead, self.primary, self.fallback)

    # Enable search whenever at least one free provider is configured.
    def is_enabled(self) -> bool:
        return any(provider.is_enabled() for provider in self.chain)

    # Apply deterministic normal, fallback, or dual-provider search policy.
    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> SearchResults:
        bounded = max(1, min(max_results or self.max_results, self.max_results))
        if requires_cross_check(query):
            return await self._cross_check(query, bounded)
        exhausted: list[Exception] = []
        enabled = [provider for provider in self.chain if provider.is_enabled()]
        for position, provider in enumerate(enabled):
            last = position == len(enabled) - 1
            try:
                found = await provider.search(query, bounded)
            except SearchQuotaExceededError as exc:
                # This one's budget for the period is spent; the next may not be.
                exhausted.append(exc)
                continue
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in _PLAN_STATUSES:
                    exhausted.append(exc)
                    continue
                if last:
                    raise
                logger.warning("Web-search provider failed; trying the next", exc_info=True)
                continue
            except Exception:
                if last:
                    raise
                logger.warning("Web-search provider failed; trying the next", exc_info=True)
                continue
            if found.results or last:
                return found
        if exhausted and len(exhausted) == len(enabled):
            raise EveryProviderExhausted("every web-search provider has spent its budget")
        if exhausted:
            raise exhausted[-1]
        raise RuntimeError("No web-search provider is available.")

    # Query every configured provider once and merge whatever succeeds.
    async def _cross_check(self, query: str, limit: int) -> SearchResults:
        providers = [provider for provider in self.chain if provider.is_enabled()]
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
