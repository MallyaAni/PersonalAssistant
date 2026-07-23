import json

from backend.mcp.servers.internet import _encode_results
from backend.search.types import SearchResult, SearchResults


# Verify long web pages remain valid bounded JSON before generic MCP truncation.
def test_internet_mcp_result_is_compact_valid_json():
    found = SearchResults(
        query="latest release",
        provider="stub",
        results=tuple(
            SearchResult(
                title=f"Result {index}",
                url=f"https://example.test/{index}",
                content="x" * 5_000,
                score=0.9,
            )
            for index in range(5)
        ),
    )

    encoded = _encode_results(found)
    payload = json.loads(encoded)

    assert len(encoded) <= 3_500
    assert len(payload["results"]) == 5
    assert all(len(item["content"]) == 500 for item in payload["results"])
