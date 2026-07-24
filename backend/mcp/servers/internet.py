"""Read-only MCP server with Google research and Tavily fallback."""

import json
import os

from mcp.server.fastmcp import FastMCP

from backend.search.google_adk import GoogleADKSearchProvider
from backend.search.hybrid import HybridSearchProvider
from backend.search.quota import SQLiteDailySearchQuota
from backend.search.tavily import TavilySearchProvider
from backend.search.types import SearchResults

mcp = FastMCP("AniOS Internet Search")
_MAX_SERIALIZED_RESULT_CHARS = 3_500


# Compose the Google-first provider policy from operator-owned environment.
def _build_search_provider() -> HybridSearchProvider:
    max_results = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    max_content_chars = int(os.getenv("SEARCH_MAX_CONTENT_CHARS", "2000"))
    google = GoogleADKSearchProvider(
        api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
        enabled=os.getenv("GOOGLE_SEARCH_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        model=os.getenv("GOOGLE_SEARCH_MODEL", "gemini-3.6-flash"),
        timeout_seconds=float(os.getenv("GOOGLE_SEARCH_TIMEOUT_SECONDS", "30")),
        max_results=max_results,
        max_content_chars=max_content_chars,
        max_output_tokens=int(os.getenv("GOOGLE_SEARCH_MAX_OUTPUT_TOKENS", "2048")),
        quota=SQLiteDailySearchQuota(
            path=os.getenv(
                "GOOGLE_SEARCH_QUOTA_DB_PATH",
                "data/search/google_search_quota.sqlite3",
            ),
            provider="google",
            daily_limit=int(os.getenv("GOOGLE_SEARCH_DAILY_LIMIT", "450")),
        ),
    )
    tavily = TavilySearchProvider(
        base_url=os.getenv("SEARCH_BASE_URL", "https://api.tavily.com"),
        api_key=os.getenv("SEARCH_API_KEY"),
        max_results=max_results,
        timeout_seconds=float(os.getenv("SEARCH_TIMEOUT_SECONDS", "15")),
        max_content_chars=max_content_chars,
        min_score=float(os.getenv("SEARCH_MIN_SCORE", "0.4")),
        search_depth=os.getenv("SEARCH_DEPTH", "basic"),
    )
    return HybridSearchProvider(
        primary=google,
        fallback=tavily,
        max_results=max_results,
    )


# Serialize compact results without letting the generic MCP cap corrupt JSON.
def _encode_results(found: SearchResults) -> str:
    results: list[dict[str, object]] = []
    for item in found.results:
        candidate: dict[str, object] = {
            "title": item.title[:200],
            "url": item.url[:500],
            "content": item.content[:500],
            "score": item.score,
            "provider": item.provider,
        }
        proposed = json.dumps(
            {"provider": found.provider, "results": [*results, candidate]},
            ensure_ascii=False,
        )
        if len(proposed) > _MAX_SERIALIZED_RESULT_CHARS:
            break
        results.append(candidate)
    return json.dumps(
        {"provider": found.provider, "results": results},
        ensure_ascii=False,
    )


# Search with Google first, Tavily fallback, or both for explicit verification.
@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> str:
    """Research a minimized public query with bounded free-provider policy."""
    provider = _build_search_provider()
    found = await provider.search(query, max_results=max_results)
    return _encode_results(found)


# Run the internet server over stdio for the configured AniOS MCP client.
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
