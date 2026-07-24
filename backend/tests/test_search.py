import json

import httpx
import pytest

from backend.search.tavily import TavilySearchProvider


def _provider(
    handler: object,
    *,
    api_key: str | None = "tvly-test-key",
    max_results: int = 3,
    max_content_chars: int = 50,
) -> tuple[TavilySearchProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    provider = TavilySearchProvider(
        base_url="https://api.tavily.com/",
        api_key=api_key,
        max_results=max_results,
        timeout_seconds=5.0,
        max_content_chars=max_content_chars,
        client=client,
    )
    return provider, client


@pytest.mark.asyncio
async def test_search_sends_bearer_auth_and_returns_bounded_truncated_results():
    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("Authorization"),
                "payload": json.loads(request.content),
            }
        )
        return httpx.Response(
            200,
            json={
                "query": "current mars mission",
                "results": [
                    {
                        "title": "Mission update",
                        "url": "https://example.test/a",
                        "content": "x" * 500,
                        "score": 0.91,
                    },
                    {
                        "title": "Second",
                        "url": "https://example.test/b",
                        "content": "short",
                        "score": 0.4,
                    },
                ],
            },
        )

    provider, client = _provider(handler)
    async with client:
        results = await provider.search("current mars mission")

    assert results.provider == "tavily"
    assert results.query == "current mars mission"
    assert len(results.results) == 2
    assert {result.provider for result in results.results} == {"tavily"}
    # The API key travels as a Bearer header and never in the request body.
    assert observed[0]["authorization"] == "Bearer tvly-test-key"
    assert "tvly-test-key" not in json.dumps(observed[0]["payload"])
    assert observed[0]["url"] == "https://api.tavily.com/search"
    assert observed[0]["payload"]["query"] == "current mars mission"
    assert observed[0]["payload"]["search_depth"] == "basic"
    # The request size is a candidate pool, not the caller's limit, so the
    # relevance floor has alternatives to choose between.
    assert observed[0]["payload"]["max_results"] >= 3
    # A verbose page is truncated so it cannot dominate the prompt budget.
    assert len(results.results[0].content) == 50
    assert results.results[1].content == "short"


@pytest.mark.asyncio
async def test_search_clamps_requested_results_to_the_provider_maximum():
    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    provider, client = _provider(handler)
    async with client:
        await provider.search("anything", max_results=500)
        await provider.search("anything", max_results=0)

    # An oversized request is clamped to what the provider accepts, and an
    # undersized one is raised to the candidate pool rather than sent as-is.
    assert observed[0]["max_results"] == 20
    assert observed[1]["max_results"] >= 1
    assert observed[1]["max_results"] <= 20


@pytest.mark.asyncio
async def test_search_skips_malformed_untrusted_results_without_failing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    "not-an-object",
                    {"url": "https://example.test/no-title"},
                    {"title": "No url"},
                    {"title": "Valid", "url": "https://example.test/ok"},
                    {"title": "Bad score", "url": "https://e.test/s", "score": "high"},
                ]
            },
        )

    provider, client = _provider(handler)
    async with client:
        results = await provider.search("q", max_results=10)

    assert [r.title for r in results.results] == ["Valid", "Bad score"]
    # Missing content and unusable scores degrade to safe defaults.
    assert results.results[0].content == ""
    assert results.results[1].score == 0.0


@pytest.mark.asyncio
async def test_search_is_disabled_without_a_configured_key():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("disabled provider must not issue a request")

    provider, client = _provider(handler, api_key=None)
    async with client:
        assert provider.is_enabled() is False
        with pytest.raises(RuntimeError, match="SEARCH_API_KEY"):
            await provider.search("q")


@pytest.mark.asyncio
async def test_search_propagates_provider_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "rate limited"})

    provider, client = _provider(handler)
    async with client:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.search("q")


@pytest.mark.asyncio
async def test_low_relevance_results_are_dropped_before_the_prompt():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Real hit",
                        "url": "https://e.test/a",
                        "content": "x",
                        "score": 0.90,
                    },
                    {
                        "title": "Weak hit",
                        "url": "https://e.test/b",
                        "content": "x",
                        "score": 0.42,
                    },
                    {
                        "title": "Dictionary noise",
                        "url": "https://e.test/c",
                        "content": "x",
                        "score": 0.12,
                    },
                    {"title": "No score", "url": "https://e.test/d", "content": "x"},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilySearchProvider(
        base_url="https://api.tavily.com",
        api_key="tvly-test-key",
        max_results=10,
        timeout_seconds=5.0,
        max_content_chars=100,
        min_score=0.4,
        client=client,
    )
    async with client:
        results = await provider.search("q")

    # Noise scoring below the floor must never be quoted as authoritative.
    assert [r.title for r in results.results] == ["Real hit", "Weak hit"]


@pytest.mark.asyncio
async def test_score_floor_defaults_to_accepting_everything():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"title": "t", "url": "https://e.test/x", "score": 0.01}]
            },
        )

    provider, client = _provider(handler)
    async with client:
        assert len((await provider.search("q")).results) == 1


@pytest.mark.asyncio
async def test_a_small_request_still_fetches_a_candidate_pool():
    observed: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(json.loads(request.content)["max_results"])
        # Mirrors real Tavily behaviour: scores are not ordered, so the first
        # rows can sit below the floor while a later one clears it.
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "low a", "url": "https://e.test/a", "score": 0.04},
                    {"title": "low b", "url": "https://e.test/b", "score": 0.04},
                    {"title": "good", "url": "https://e.test/c", "score": 0.92},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilySearchProvider(
        base_url="https://api.tavily.com",
        api_key="tvly-test-key",
        max_results=5,
        timeout_seconds=5.0,
        max_content_chars=100,
        min_score=0.4,
        client=client,
    )
    async with client:
        results = await provider.search("q", max_results=1)

    # Requesting exactly one result would leave the floor nothing to pick from
    # and return an empty list, so a pool is fetched and then truncated.
    assert observed[0] >= 5
    assert [r.title for r in results.results] == ["good"]


@pytest.mark.asyncio
async def test_the_callers_limit_is_still_respected_after_over_fetching():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": f"hit {i}", "url": f"https://e.test/{i}", "score": 0.9}
                    for i in range(6)
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilySearchProvider(
        base_url="https://api.tavily.com",
        api_key="tvly-test-key",
        max_results=5,
        timeout_seconds=5.0,
        max_content_chars=100,
        min_score=0.4,
        client=client,
    )
    async with client:
        results = await provider.search("q", max_results=2)

    assert len(results.results) == 2
