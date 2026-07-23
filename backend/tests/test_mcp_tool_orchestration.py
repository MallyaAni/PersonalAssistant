import json

import pytest

from backend.core.llm import LLMClient
from backend.mcp.invocation import ToolCallResult
from backend.mcp.types import MCPServerConfig, MCPTool
from backend.services.mcp_invocation_service import MCPInvocationService
from backend.services.mcp_tool_orchestration_service import (
    MCPToolOrchestrationService,
    MCPToolSelectionError,
)

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}
TOOL = MCPTool(
    server_id="weather",
    name="current_weather",
    description="Returns the current weather for a city.",
    input_schema=SCHEMA,
)


class DescriptorMemory:
    """Return one indexed descriptor without requiring PostgreSQL."""

    # Capture search inputs and return the configured descriptor list.
    def __init__(self, descriptors: list[dict] | None = None) -> None:
        self.descriptors = (
            descriptors
            if descriptors is not None
            else [
                {
                    "server_id": TOOL.server_id,
                    "tool_name": TOOL.name,
                    "schema_fingerprint": TOOL.schema_fingerprint,
                }
            ]
        )
        self.calls: list[tuple] = []

    # Return semantically shortlisted tool descriptors for the test user.
    async def search_descriptors(
        self,
        user_id,
        query,
        server_id,
        top_k,
        query_embedding=None,
    ):
        self.calls.append((user_id, query, server_id, top_k, query_embedding))
        return self.descriptors


class FixedToolLLM(LLMClient):
    """Return a controlled native tool decision and record exposed schemas."""

    # Configure one provider-style message for the next decision.
    def __init__(self, message: dict) -> None:
        self.message = message
        self.tools: list[dict] = []

    # Return unused plain text for the abstract provider contract.
    def generate_text(self, prompt, max_tokens=1024):
        return "unused"

    # Return unused plain chat for the abstract provider contract.
    def chat(self, messages, max_tokens=1024):
        return {"content": "unused"}

    # Return unused streaming chat for the abstract provider contract.
    def stream_chat(self, messages, max_tokens=1024):
        yield "unused"

    # Return the controlled native tool-call message.
    def chat_with_tools(self, messages, tools, max_tokens=256):
        self.tools = tools
        return self.message


class LiveLister:
    """Return one live MCP contract."""

    # Return the current test catalogue.
    async def list_tools(self, server):
        return [TOOL]


class RecordingInvoker:
    """Record the call that passed every invocation gate."""

    # Start with no executed calls.
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    # Record and return one bounded tool result.
    async def call_tool(self, server, tool_name, arguments):
        self.calls.append((server.server_id, tool_name, arguments))
        return ToolCallResult(server.server_id, tool_name, "Weather is 72 F")


# Build the orchestration service around deterministic test doubles.
def _service(message: dict, risk: str = "read_only"):
    memory = DescriptorMemory()
    llm = FixedToolLLM(message)
    invoker = RecordingInvoker()
    invocation = MCPInvocationService(
        invoker,  # type: ignore[arg-type]
        LiveLister(),  # type: ignore[arg-type]
        (
            MCPServerConfig(
                server_id="weather",
                command="noop",
                risk_classification=risk,
            ),
        ),
    )
    service = MCPToolOrchestrationService(
        memory,  # type: ignore[arg-type]
        invocation,
        llm,
    )
    return service, memory, llm, invoker


# Verify Gemma selects a live schema and execution still passes through MCP gates.
@pytest.mark.asyncio
async def test_native_tool_selection_executes_the_guarded_live_tool():
    service, memory, llm, invoker = _service(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "mcp_tool_0",
                        "arguments": json.dumps({"city": "Raleigh"}),
                    }
                }
            ]
        }
    )

    plan = await service.select("ani.mallya", "weather now", [0.1, 0.2])
    assert plan is not None
    result = await service.execute(plan)

    assert memory.calls == [("ani.mallya", "weather now", None, 5, [0.1, 0.2])]
    assert llm.tools[0]["function"]["parameters"] == SCHEMA
    assert invoker.calls == [("weather", "current_weather", {"city": "Raleigh"})]
    assert result.content == "Weather is 72 F"


# Verify the model can decline every candidate without invoking anything.
@pytest.mark.asyncio
async def test_no_tool_decision_does_not_execute():
    service, _memory, _llm, invoker = _service({"content": "NO_TOOL"})

    plan = await service.select("ani.mallya", "say hello")

    assert plan is None
    assert invoker.calls == []


# Verify consequential servers are never exposed for autonomous model selection.
@pytest.mark.asyncio
async def test_consequential_tool_is_not_exposed_to_gemma():
    service, _memory, llm, invoker = _service({"content": "NO_TOOL"}, "untrusted")

    plan = await service.select("ani.mallya", "delete everything")

    assert plan is None
    assert llm.tools == []
    assert invoker.calls == []


# Verify malformed model arguments fail closed before any MCP invocation.
@pytest.mark.asyncio
async def test_malformed_model_arguments_fail_before_execution():
    service, _memory, _llm, invoker = _service(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "mcp_tool_0",
                        "arguments": "not-json",
                    }
                }
            ]
        }
    )

    with pytest.raises(MCPToolSelectionError, match="invalid_tool_arguments"):
        await service.select("ani.mallya", "weather now")

    assert invoker.calls == []
