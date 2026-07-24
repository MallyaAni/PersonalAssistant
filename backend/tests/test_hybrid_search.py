from __future__ import annotations

from typing import cast

import pytest

from backend.core.interfaces import SearchProvider
from backend.search.hybrid import HybridSearchProvider, requires_cross_check
from backend.search.types import SearchResult, SearchResults


class RecordingProvider:
    """Return configured search outcomes while recording every query."""

    # Configure one fake provider outcome for routing tests.
    def __init__(
        self,
        name: str,
        *,
        enabled: bool = True,
        urls: tuple[str, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self.name = name
        self.enabled = enabled
        self.urls = urls
        self.failure = failure
        self.calls: list[tuple[str, int | None]] = []

    # Report whether this fake provider is available.
    def is_enabled(self) -> bool:
        return self.enabled

    # Record the query and return or raise the configured outcome.
    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> SearchResults:
        self.calls.append((query, max_results))
        if self.failure is not None:
            raise self.failure
        return SearchResults(
            query=query,
            provider=self.name,
            results=tuple(
                SearchResult(
                    title=f"{self.name} result {index}",
                    url=url,
                    content=f"{self.name} facts",
                    score=None,
                    provider=self.name,
                )
                for index, url in enumerate(self.urls)
            ),
        )


# Treat the test double as the application search interface.
def _as_provider(provider: RecordingProvider) -> SearchProvider:
    return cast(SearchProvider, provider)


# Verify ordinary research spends only the primary provider quota.
@pytest.mark.asyncio
async def test_hybrid_search_prefers_google_without_calling_tavily() -> None:
    google = RecordingProvider("google", urls=("https://google.test/a",))
    tavily = RecordingProvider("tavily", urls=("https://tavily.test/a",))
    provider = HybridSearchProvider(_as_provider(google), _as_provider(tavily), 5)

    found = await provider.search("latest Python release", max_results=3)

    assert found.provider == "google"
    assert google.calls == [("latest Python release", 3)]
    assert tavily.calls == []


# Verify a primary failure transparently uses the configured fallback.
@pytest.mark.asyncio
async def test_hybrid_search_falls_back_to_tavily_after_google_failure() -> None:
    google = RecordingProvider("google", failure=RuntimeError("quota exhausted"))
    tavily = RecordingProvider("tavily", urls=("https://tavily.test/a",))
    provider = HybridSearchProvider(_as_provider(google), _as_provider(tavily), 5)

    found = await provider.search("latest Python release")

    assert found.provider == "tavily"
    assert google.calls == [("latest Python release", 5)]
    assert tavily.calls == [("latest Python release", 5)]


# Verify an unconfigured Google worker sends ordinary requests directly to Tavily.
@pytest.mark.asyncio
async def test_hybrid_search_uses_tavily_when_google_is_disabled() -> None:
    google = RecordingProvider("google", enabled=False)
    tavily = RecordingProvider("tavily", urls=("https://tavily.test/a",))
    provider = HybridSearchProvider(_as_provider(google), _as_provider(tavily), 5)

    found = await provider.search("latest Python release")

    assert found.provider == "tavily"
    assert google.calls == []
    assert tavily.calls == [("latest Python release", 5)]


# Verify only explicit verification language opts into dual-provider spending.
def test_cross_check_detection_requires_explicit_verification_language() -> None:
    assert requires_cross_check("Verify this with independent sources")
    assert requires_cross_check("Please cross-check that claim")
    assert not requires_cross_check("Search for the latest weather forecast")


# Verify cross-checking merges and deduplicates attributable provider results.
@pytest.mark.asyncio
async def test_hybrid_search_cross_checks_and_deduplicates_results() -> None:
    google = RecordingProvider(
        "google",
        urls=("https://www.example.test/shared/", "https://google.test/only"),
    )
    tavily = RecordingProvider(
        "tavily",
        urls=("https://example.test/shared", "https://tavily.test/only"),
    )
    provider = HybridSearchProvider(_as_provider(google), _as_provider(tavily), 5)

    found = await provider.search("Double-check this with independent sources")

    assert found.provider == "google+tavily"
    assert [result.provider for result in found.results] == [
        "google",
        "google",
        "tavily",
    ]
    assert google.calls == [("Double-check this with independent sources", 5)]
    assert tavily.calls == [("Double-check this with independent sources", 5)]


# Verify cross-check mode still succeeds when one provider is unavailable.
@pytest.mark.asyncio
async def test_hybrid_cross_check_tolerates_one_provider_failure() -> None:
    google = RecordingProvider("google", failure=RuntimeError("temporary failure"))
    tavily = RecordingProvider("tavily", urls=("https://tavily.test/a",))
    provider = HybridSearchProvider(_as_provider(google), _as_provider(tavily), 5)

    found = await provider.search("Corroborate this answer")

    assert found.provider == "tavily"
    assert [result.provider for result in found.results] == ["tavily"]


# Verify search fails clearly when neither provider is configured.
@pytest.mark.asyncio
async def test_hybrid_search_rejects_when_no_provider_is_available() -> None:
    google = RecordingProvider("google", enabled=False)
    tavily = RecordingProvider("tavily", enabled=False)
    provider = HybridSearchProvider(_as_provider(google), _as_provider(tavily), 5)

    assert provider.is_enabled() is False
    with pytest.raises(RuntimeError, match="No web-search provider"):
        await provider.search("latest Python release")
