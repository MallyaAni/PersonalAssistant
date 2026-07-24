import json

from backend.mcp.servers.internet import _encode_results
from backend.search.types import SearchResult, SearchResults


# Verify the MCP boundary preserves provider attribution and nullable Google scores.
def test_internet_mcp_encodes_attributable_hybrid_results() -> None:
    encoded = _encode_results(
        SearchResults(
            query="latest Python release",
            provider="google+tavily",
            results=(
                SearchResult(
                    title="Python releases",
                    url="https://python.org/downloads/",
                    content="Current release details.",
                    score=None,
                    provider="google",
                ),
                SearchResult(
                    title="Independent report",
                    url="https://example.test/python",
                    content="Independent release report.",
                    score=0.92,
                    provider="tavily",
                ),
            ),
        )
    )

    payload = json.loads(encoded)
    assert payload["provider"] == "google+tavily"
    assert payload["results"][0]["provider"] == "google"
    assert payload["results"][0]["score"] is None
    assert payload["results"][1]["provider"] == "tavily"
