"""Structural coverage for preselected visual grounding queries."""

import json

import pytest

from backend.mcp.invocation import ToolCallResult
from backend.mcp.types import MCPTool
from backend.services.visual_search_grounding import VisualSearchGrounding


class RecordingInvocation:
    """Expose one read-only search tool and record its arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    # Permit the configured search server to be called autonomously.
    def can_auto_invoke(self, server_id: str) -> bool:
        return server_id == "internet"

    # Return the live schema required by the guarded invocation boundary.
    async def resolve_tool(self, server_id: str, tool_name: str) -> MCPTool:
        return MCPTool(
            server_id,
            tool_name,
            "Search public web sources",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        )

    # Return one bounded result without making a network request.
    async def invoke(self, server_id: str, tool_name: str, arguments: dict):
        self.calls.append((server_id, tool_name, arguments))
        return ToolCallResult(
            server_id,
            tool_name,
            json.dumps({"results": [{"title": "Matched device"}]}),
        )


# A query chosen during the image inspection must execute without another LLM.
@pytest.mark.asyncio
async def test_preselected_query_invokes_search_directly() -> None:
    invocation = RecordingInvocation()
    grounding = VisualSearchGrounding(
        llm=None,
        mcp_invocation=invocation,  # type: ignore[arg-type]
        search_server_id="internet",
        search_tool_name="search_web",
    )

    result = await grounding.ground_query("gold perforated desktop computer")

    assert result is not None
    assert invocation.calls == [
        (
            "internet",
            "search_web",
            {"query": "gold perforated desktop computer", "max_results": 5},
        )
    ]


# Missing diagnostic evidence produces no query and therefore no tool call.
@pytest.mark.asyncio
async def test_blank_preselected_query_never_searches() -> None:
    invocation = RecordingInvocation()
    grounding = VisualSearchGrounding(
        llm=None,
        mcp_invocation=invocation,  # type: ignore[arg-type]
        search_server_id="internet",
        search_tool_name="search_web",
    )

    assert await grounding.ground_query("   ") is None
    assert invocation.calls == []
