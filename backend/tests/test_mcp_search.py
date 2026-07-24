import json

import pytest

from backend.mcp.invocation import ToolCallResult
from backend.search.mcp import MCPWebSearchProvider


class RecordingInvocation:
    """Record fixed MCP search calls without starting a server."""

    # Configure whether the server is autonomous and what it returns.
    def __init__(self, enabled: bool = True, content: str | None = None) -> None:
        self.enabled = enabled
        self.content = content or json.dumps(
            {
                "results": [
                    {
                        "title": "Current result",
                        "url": "https://example.test/current",
                        "content": "fresh facts",
                        "score": 0.9,
                        "provider": "google",
                    },
                    {
                        "title": "Noise",
                        "url": "https://example.test/noise",
                        "content": "low relevance",
                        "score": 0.1,
                    },
                ]
            }
        )
        self.calls: list[tuple] = []

    # Report the configured autonomous policy result.
    def can_auto_invoke(self, server_id: str) -> bool:
        return self.enabled and server_id == "internet"

    # Return one fixed MCP result and capture arguments.
    async def invoke(self, server_id, tool_name, arguments):
        self.calls.append((server_id, tool_name, arguments))
        return ToolCallResult(server_id, tool_name, self.content)


# Build the bounded MCP search adapter used in each test.
def _provider(invocation: RecordingInvocation) -> MCPWebSearchProvider:
    return MCPWebSearchProvider(
        invocation,  # type: ignore[arg-type]
        "internet",
        "search_web",
        max_results=5,
        max_content_chars=20,
        min_score=0.4,
    )


# Verify internet search executes through MCP and filters untrusted results.
@pytest.mark.asyncio
async def test_mcp_search_invokes_fixed_tool_and_returns_bounded_results():
    invocation = RecordingInvocation()

    found = await _provider(invocation).search("latest Python", max_results=3)

    assert invocation.calls == [
        ("internet", "search_web", {"query": "latest Python", "max_results": 3})
    ]
    assert found.provider == "mcp:internet/search_web"
    assert [item.title for item in found.results] == ["Current result"]
    assert found.results[0].content == "fresh facts"
    assert found.results[0].provider == "google"


# Verify local risk policy disables the outbound provider before any call.
@pytest.mark.asyncio
async def test_mcp_search_is_disabled_when_server_is_not_auto_invocable():
    invocation = RecordingInvocation(enabled=False)
    provider = _provider(invocation)

    assert provider.is_enabled() is False
    with pytest.raises(RuntimeError, match="not available"):
        await provider.search("latest Python")
    assert invocation.calls == []


# Verify malformed MCP output never becomes quoted web context.
@pytest.mark.asyncio
async def test_mcp_search_rejects_malformed_result():
    provider = _provider(RecordingInvocation(content="not-json"))

    with pytest.raises(RuntimeError, match="invalid"):
        await provider.search("latest Python")
