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
    # The API key travels as a Bearer header and never in the request body.
    assert observed[0]["authorization"] == "Bearer tvly-test-key"
    assert "tvly-test-key" not in json.dumps(observed[0]["payload"])
    assert observed[0]["url"] == "https://api.tavily.com/search"
    assert observed[0]["payload"] == {
        "query": "current mars mission",
        "max_results": 3,
        "search_depth": "basic",
    }
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

    assert observed[0]["max_results"] == 20
    assert observed[1]["max_results"] == 1


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
