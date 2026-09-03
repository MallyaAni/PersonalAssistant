import json

import pytest

from backend.core.llm import LLMClient
from backend.mcp.types import MCPServerConfig, MCPTool
from backend.services.main_action_selector import (
    CreateDiagramAction,
    DelegateAction,
    EditImageAction,
    GenerateImageAction,
    MainActionSelector,
    SearchAction,
    ToolboxAction,
)
from backend.services.mcp_invocation_service import MCPInvocationService
from backend.services.mcp_tool_orchestration_service import MCPToolOrchestrationService

SEARCH_TOOL = MCPTool(
    server_id="internet",
    name="search_web",
    description="Research a minimized public query.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
    },
)
WEATHER_TOOL = MCPTool(
    server_id="weather",
    name="current_weather",
    description="Returns the current weather for a city.",
    input_schema={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
)


class FixedToolLLM(LLMClient):
    """Return a controlled native tool decision and record exposed schemas."""

    def __init__(self, message: dict) -> None:
        self.message = message
        self.tools: list[dict] = []
        self.messages: list[dict] = []

    def generate_text(self, prompt, max_tokens=1024):
        return "unused"

    def chat(self, messages, max_tokens=1024):
        return {"content": "unused"}

    def stream_chat(self, messages, max_tokens=1024):
        yield "unused"

    def chat_with_tools(self, messages, tools, max_tokens=256):
        self.tools = tools
        self.messages = messages
        return self.message


class FailingLLM(LLMClient):
    def generate_text(self, prompt, max_tokens=1024):
        return "unused"

    def chat(self, messages, max_tokens=1024):
        return {"content": "unused"}

    def stream_chat(self, messages, max_tokens=1024):
        yield "unused"

    def chat_with_tools(self, messages, tools, max_tokens=256):
        raise RuntimeError("runtime unreachable")


class LiveLister:
    """Return one live MCP contract regardless of which server is asked."""

    def __init__(self, tools: dict[str, list[MCPTool]]) -> None:
        self.tools = tools

    async def list_tools(self, server):
        return self.tools.get(server.server_id, [])


class RecordingInvoker:
    async def call_tool(self, server, tool_name, arguments):
        raise AssertionError("execution is not exercised by the selector")


class DescriptorMemory:
    """Return one indexed toolbox descriptor without requiring PostgreSQL."""

    def __init__(self, descriptors: list[dict] | None = None) -> None:
        self.descriptors = (
            descriptors
            if descriptors is not None
            else [
                {
                    "server_id": WEATHER_TOOL.server_id,
                    "tool_name": WEATHER_TOOL.name,
                    "schema_fingerprint": WEATHER_TOOL.schema_fingerprint,
                }
            ]
        )

    async def search_descriptors(
        self, user_id, query, server_id, top_k, query_embedding=None
    ):
        return self.descriptors


# Build a selector with both a live search tool and a toolbox candidate.
def _selector(
    message: dict,
    diagram_enabled: bool = True,
    presentation_enabled: bool = True,
    search_risk: str = "read_only",
    llm: LLMClient | None = None,
) -> tuple[MainActionSelector, FixedToolLLM]:
    fixed_llm = llm if isinstance(llm, FixedToolLLM) else FixedToolLLM(message)
    invocation = MCPInvocationService(
        RecordingInvoker(),  # type: ignore[arg-type]
        LiveLister({"internet": [SEARCH_TOOL], "weather": [WEATHER_TOOL]}),  # type: ignore[arg-type]
        (
            MCPServerConfig(
                server_id="internet", command="noop", risk_classification=search_risk
            ),
            MCPServerConfig(
                server_id="weather", command="noop", risk_classification="read_only"
            ),
        ),
    )
    orchestration = MCPToolOrchestrationService(
        DescriptorMemory(),  # type: ignore[arg-type]
        invocation,
        fixed_llm,
    )
    selector = MainActionSelector(
        llm if llm is not None else fixed_llm,
        invocation,
        "internet",
        "search_web",
        orchestration,
        diagram_enabled=diagram_enabled,
        presentation_enabled=presentation_enabled,
    )
    return selector, fixed_llm


def _tool_call(name: str, arguments: dict) -> dict:
    return {
        "tool_calls": [{"function": {"name": name, "arguments": json.dumps(arguments)}}]
    }


@pytest.mark.asyncio
async def test_model_choosing_search_writes_its_own_query():
    selector, llm = _selector(
        _tool_call("search_web", {"query": "current weather in Raleigh NC"})
    )

    action = await selector.select("ani.mallya", "what's it like outside", [], None)

    assert action == SearchAction(
        query="current weather in Raleigh NC", max_results=None
    )
    names = {tool["function"]["name"] for tool in llm.tools}
    assert "search_web" in names


@pytest.mark.asyncio
async def test_no_tool_call_means_answer_directly():
    selector, _llm = _selector({"content": "just answer normally"})

    action = await selector.select("ani.mallya", "what is 2 plus 2", [], None)

    assert action is None


@pytest.mark.asyncio
async def test_model_choosing_generate_image():
    selector, _llm = _selector(
        _tool_call("generate_image", {"prompt": "a red bicycle at sunset"})
    )

    action = await selector.select("ani.mallya", "draw me a bike", [], None)

    assert action == GenerateImageAction(prompt="a red bicycle at sunset")


# edit_image is offered every turn, active image or not: only the model can
# judge whether the message wants a picture changed, and only the application
# (ConversationService, not this selector) can check whether one is actually
# in view to apply that to.
@pytest.mark.asyncio
async def test_edit_image_is_always_offered_regardless_of_active_image():
    selector, llm = _selector(
        _tool_call("edit_image", {"instruction": "add a straw hat"})
    )

    without_active = await selector.select("ani.mallya", "add a hat", [], None)
    assert without_active == EditImageAction(instruction="add a straw hat")
    assert "edit_image" in {tool["function"]["name"] for tool in llm.tools}


# Give the model the real interface state so it cannot deny a visible selection.
@pytest.mark.asyncio
async def test_active_image_state_is_included_in_the_model_decision():
    selector, llm = _selector({"content": "no tool"})

    await selector.select(
        "ani.mallya",
        "can you generate a labelled image of this?",
        [],
        "artifact-123",
    )

    assert "picture is currently selected and visible" in llm.messages[1]["content"]
    assert "edit_image" in {tool["function"]["name"] for tool in llm.tools}


@pytest.mark.asyncio
async def test_model_choosing_diagram():
    selector, _llm = _selector(
        _tool_call("create_diagram", {"subject": "the deploy pipeline"})
    )

    action = await selector.select(
        "ani.mallya", "draw a flowchart of the deploy pipeline", [], None
    )

    assert action == CreateDiagramAction(subject="the deploy pipeline")


@pytest.mark.asyncio
async def test_diagram_not_offered_when_disabled():
    selector, llm = _selector({"content": "no tool"}, diagram_enabled=False)

    await selector.select("ani.mallya", "draw a flowchart", [], None)

    assert "create_diagram" not in {tool["function"]["name"] for tool in llm.tools}


@pytest.mark.asyncio
async def test_model_choosing_presentation_delegation():
    selector, _llm = _selector(
        _tool_call("delegate_to_presentation_agent", {"subject": "battery storage"})
    )

    action = await selector.select(
        "ani.mallya", "put together a six-slide deck on battery storage", [], None
    )

    assert action == DelegateAction(
        capability_id="presentation_agent", subject="battery storage"
    )


# The misroute this guards: a tool chosen with nothing to make must not take
# the turn, or the user gets a queued deck about nothing instead of the
# question they asked answered.
@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["create_diagram", "delegate_to_presentation_agent"])
async def test_a_subjectless_call_is_not_an_action(tool: str):
    selector, _llm = _selector(_tool_call(tool, {"subject": "   "}))

    action = await selector.select("ani.mallya", "make me one", [], None)

    assert action is None


@pytest.mark.asyncio
async def test_presentation_not_offered_when_disabled():
    selector, llm = _selector({"content": "no tool"}, presentation_enabled=False)

    await selector.select("ani.mallya", "build me a deck", [], None)

    assert "delegate_to_presentation_agent" not in {
        tool["function"]["name"] for tool in llm.tools
    }


@pytest.mark.asyncio
async def test_model_choosing_a_registered_toolbox_tool():
    selector, _llm = _selector(_tool_call("mcp_tool_0", {"city": "Raleigh"}))

    action = await selector.select("ani.mallya", "weather now", [], None)

    assert isinstance(action, ToolboxAction)
    assert action.plan.server_id == "weather"
    assert action.plan.tool_name == "current_weather"
    assert action.plan.arguments == {"city": "Raleigh"}


@pytest.mark.asyncio
async def test_search_not_offered_when_the_server_is_untrusted():
    selector, llm = _selector({"content": "no tool"}, search_risk="untrusted")

    await selector.select("ani.mallya", "what's happening in the news", [], None)

    assert "search_web" not in {tool["function"]["name"] for tool in llm.tools}


@pytest.mark.asyncio
async def test_llm_failure_fails_closed_to_no_action():
    selector, _llm = _selector({}, llm=FailingLLM())

    action = await selector.select("ani.mallya", "anything", [], None)

    assert action is None


# The whole point of deriving the reply prompt's capability list from here: what
# conversation claims AniOS can do must be the same wording routing acts on. A
# paraphrase in the prompt is how the two silently disagreed before.
@pytest.mark.asyncio
async def test_every_described_capability_carries_the_offered_tools_own_wording():
    selector, llm = _selector({"content": "no tool"})

    await selector.select("ani.mallya", "anything", [], None)
    described = {item["description"] for item in selector.describe_capabilities()}

    # Every built-in actually offered this turn is described in its own words.
    # search_web is excluded: its offered description belongs to the live MCP
    # contract, so the capability sentence for it is AniOS's own by design.
    offered = {
        tool["function"]["description"]
        for tool in llm.tools
        if tool["function"]["name"]
        in {
            "generate_image",
            "edit_image",
            "create_diagram",
            "delegate_to_presentation_agent",
        }
    }
    assert offered
    assert offered <= described


# A capability that cannot fire must not still be advertised. Both halves are
# read from one list precisely so a disabled tool disappears from both at once.
@pytest.mark.asyncio
async def test_a_disabled_tool_is_neither_offered_nor_described():
    selector, llm = _selector(
        {"content": "no tool"}, diagram_enabled=False, presentation_enabled=False
    )

    await selector.select("ani.mallya", "anything", [], None)
    labels = {item["label"] for item in selector.describe_capabilities()}
    names = {tool["function"]["name"] for tool in llm.tools}

    assert "Diagrams" not in labels
    assert "Presentations" not in labels
    assert "create_diagram" not in names
    assert "delegate_to_presentation_agent" not in names
    # The tools that remained callable are still described.
    assert {"New images", "Image edits"} <= labels


# Search availability follows the same rule, from policy rather than a probe:
# an untrusted server means no search tool, so nothing should promise one.
@pytest.mark.asyncio
async def test_an_untrusted_search_server_is_not_described_as_a_capability():
    trusted, _llm = _selector({"content": "no tool"})
    untrusted, _untrusted_llm = _selector(
        {"content": "no tool"}, search_risk="untrusted"
    )

    assert "Web search" in {item["label"] for item in trusted.describe_capabilities()}
    assert "Web search" not in {
        item["label"] for item in untrusted.describe_capabilities()
    }


@pytest.mark.asyncio
async def test_recent_history_reaches_the_decision_prompt():
    selector, llm = _selector({"content": "no tool"})
    history = [{"query": "I'm in Raleigh, NC", "response": "Got it."}]

    await selector.select("ani.mallya", "any events tonight?", history, None)

    sent = llm.messages[-1]["content"]
    assert "I'm in Raleigh, NC" in sent
    assert "any events tonight?" in sent


# A bare "yes" with no conversation at all has nothing to accept, and the
# decision is made in code: the model is never asked. Asked, it chose a
# history search for the word "yes" once in four runs (a deploy gate,
# 2026-09-02). A message with content of its own is still routed normally.
@pytest.mark.asyncio
async def test_a_bare_yes_with_no_conversation_never_reaches_the_model():
    selector, _ = _selector(_tool_call("search_history", {"query": "yes"}), llm=FailingLLM())
    assert await selector.select("yes_user", "yes", [], None) is None
    assert await selector.select("yes_user", "Sure!", [], None) is None


@pytest.mark.asyncio
async def test_a_yes_with_its_own_instruction_and_no_conversation_is_still_routed():
    selector, llm = _selector(_tool_call("search_history", {"query": "parking near the venue"}))
    action = await selector.select("yes_user", "yes, and find parking too", [], None)
    assert action is not None and llm.messages, "the model decides a message with content of its own"


# The catalog path: with more tools than the threshold, the router is handed
# the most-used few plus find_tools and a one-line index; when it asks for
# something else, the catalog answers and the decision is made again with
# those definitions in hand. The shape of Anthropic's tool search, on our
# own model.
class SequencedLLM(FixedToolLLM):
    """Answers each call from a queue, recording the tools it was offered."""

    def __init__(self, messages: list[dict]) -> None:
        super().__init__(messages[0])
        self.queue = list(messages)
        self.rounds: list[list[dict]] = []
        self.prompts: list[str] = []

    def chat_with_tools(self, messages, tools, max_tokens=256):
        self.rounds.append(list(tools))
        self.prompts.append(str(messages[-1]["content"]))
        return self.queue.pop(0) if self.queue else {"content": "", "tool_calls": []}


def _catalogue_selector(monkeypatch, llm):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "ROUTING_TOOL_SEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTING_TOOL_SEARCH_THRESHOLD", 4)
    selector, _ = _selector({"content": "", "tool_calls": []}, llm=llm)
    return selector


@pytest.mark.asyncio
async def test_a_deferred_tool_is_found_through_the_catalogue_and_then_called(monkeypatch):
    from backend.tools.actions import GenerateImageAction
    from backend.tools.catalog import FIND_TOOLS

    llm = SequencedLLM(
        [
            _tool_call(FIND_TOOLS, {"names": ["generate_image"]}),
            _tool_call("generate_image", {"prompt": "a fox wearing a green hat"}),
        ]
    )
    action = await _catalogue_selector(monkeypatch, llm).select(
        "image_user", "make a picture of a fox wearing a green hat", [], None
    )
    assert isinstance(action, GenerateImageAction), action

    first, second = llm.rounds[0], llm.rounds[1]
    first_names = {tool["function"]["name"] for tool in first}
    second_names = {tool["function"]["name"] for tool in second}
    # The first round is small, carries find_tools, and does not carry the
    # deferred tool; the second carries the tool the search found.
    assert FIND_TOOLS in first_names and "generate_image" not in first_names
    assert "search_web" in first_names, first_names
    assert "generate_image" in second_names and FIND_TOOLS not in second_names
    assert len(second) < len(first) + 6, "only the tools it asked for"
    # The model is told what it can look for, and then what it was given.
    assert "generate_image" in llm.prompts[0] and FIND_TOOLS in llm.prompts[0]
    assert "now loaded" in llm.prompts[1]


@pytest.mark.asyncio
async def test_a_loaded_tool_is_called_without_any_search(monkeypatch):
    from backend.tools.actions import RecallHistoryAction

    llm = SequencedLLM([_tool_call("search_history", {"query": "the Amalfi trip"})])
    action = await _catalogue_selector(monkeypatch, llm).select(
        "history_user", "what did we say about the Amalfi trip?", [], None
    )
    assert isinstance(action, RecallHistoryAction)
    assert len(llm.rounds) == 1, "no catalogue round for a tool that was loaded"


@pytest.mark.asyncio
async def test_a_search_that_finds_nothing_still_answers(monkeypatch):
    from backend.tools.catalog import FIND_TOOLS

    llm = SequencedLLM(
        [
            _tool_call(FIND_TOOLS, {"needed": "xylophone porcupine"}),
            {"content": "", "tool_calls": []},
        ]
    )
    action = await _catalogue_selector(monkeypatch, llm).select(
        "quiet_user", "tell me a joke", [], None
    )
    assert action is None
    assert "no catalogued tool" in llm.prompts[1].lower()


@pytest.mark.asyncio
async def test_the_catalogue_is_not_used_for_a_restricted_later_step(monkeypatch):
    from backend.tools import AUTOMATION_TOOLS
    from backend.tools.catalog import FIND_TOOLS

    llm = SequencedLLM([{"content": "", "tool_calls": []}])
    await _catalogue_selector(monkeypatch, llm).select(
        "step_user", "and remind me at 6", [], None, only=AUTOMATION_TOOLS
    )
    names = {tool["function"]["name"] for tool in llm.rounds[0]}
    assert FIND_TOOLS not in names and names <= set(AUTOMATION_TOOLS)
