"""Read-only MCP server that wraps the configured Tavily web-search adapter."""

import json
import os

from mcp.server.fastmcp import FastMCP

from backend.search.tavily import TavilySearchProvider
from backend.search.types import SearchResults

mcp = FastMCP("AniOS Internet Search")
_MAX_SERIALIZED_RESULT_CHARS = 3_500


# Serialize compact results without letting the generic MCP cap corrupt JSON.
def _encode_results(found: SearchResults) -> str:
    results: list[dict[str, object]] = []
    for item in found.results:
        candidate: dict[str, object] = {
            "title": item.title[:200],
            "url": item.url[:500],
            "content": item.content[:500],
            "score": item.score,
        }
        proposed = json.dumps({"results": [*results, candidate]}, ensure_ascii=False)
        if len(proposed) > _MAX_SERIALIZED_RESULT_CHARS:
            break
        results.append(candidate)
    return json.dumps({"results": results}, ensure_ascii=False)


# Search the public internet and return bounded untrusted result data.
@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> str:
    """Search public web pages for current information using a minimized query."""
    provider = TavilySearchProvider(
        base_url=os.getenv("SEARCH_BASE_URL", "https://api.tavily.com"),
        api_key=os.getenv("SEARCH_API_KEY"),
        max_results=int(os.getenv("SEARCH_MAX_RESULTS", "5")),
        timeout_seconds=float(os.getenv("SEARCH_TIMEOUT_SECONDS", "15")),
        max_content_chars=int(os.getenv("SEARCH_MAX_CONTENT_CHARS", "2000")),
        min_score=float(os.getenv("SEARCH_MIN_SCORE", "0.4")),
        search_depth=os.getenv("SEARCH_DEPTH", "basic"),
    )
    found = await provider.search(query, max_results=max_results)
    return _encode_results(found)


# Run the internet server over stdio for the configured AniOS MCP client.
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
