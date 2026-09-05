"""The router says why a turn takes no action, and remembers a decision
against the whole offer.

Two findings of the 2026-09-04 review. First, `select` returned the same
None for "nothing further", "the model failed", "the model named a tool it
was never offered" and "the model chose a tool but could not fill it in", so
a loop reading None as its clean stop reported a failed router as a finished
turn; `decide` now tells them apart. Second, the decision cache keyed on tool
names alone, so a schema that changed, or a positional MCP alias that now
pointed at a different tool, replayed a decision made against the old offer.
"""

import json

import pytest

from backend.config.settings import settings
from backend.mcp.types import MCPTool
from backend.services.main_action_selector import (
    ScheduleTaskAction,
    SearchAction,
    _decision_key,
    clear_decision_cache,
)
from backend.services.turn_steps import Act, Done, NeedsInput, Unavailable
from backend.tests.test_main_action_selector import (
    SEARCH_TOOL,
    WEATHER_TOOL,
    FailingLLM,
    _selector,
    _tool_call,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_decision_cache()
    yield
    clear_decision_cache()


async def test_no_tool_call_is_the_clean_stop():
    selector, _ = _selector({"content": "just answer"})
    decision = await selector.decide("u", "hello there", [], None)
    assert isinstance(decision, Done)


async def test_a_failed_router_is_not_a_clean_stop():
    selector, _ = _selector({}, llm=FailingLLM())
    decision = await selector.decide("u", "search the web for x", [], None)
    assert isinstance(decision, Unavailable)
    # And the untyped caller still fails closed to no action.
    assert await selector.select("u", "search the web for x", [], None) is None


async def test_a_tool_never_offered_is_not_a_clean_stop():
    selector, _ = _selector(_tool_call("delete_everything", {}))
    decision = await selector.decide("u", "please do it", [], None)
    assert isinstance(decision, Unavailable)
    assert "delete_everything" in decision.reason


async def test_a_builtin_the_model_could_not_fill_in_needs_input():
    selector, _ = _selector(_tool_call("schedule_task", {"cadence": "once"}))
    decision = await selector.decide("u", "remind me", [], None, local_now="2026-09-05 10:00")
    assert decision == NeedsInput("schedule_task")


async def test_a_filled_in_builtin_is_an_action():
    selector, _ = _selector(
        _tool_call(
            "schedule_task",
            {"instruction": "call mum", "cadence": "once", "hour": 18, "minute": 0},
        )
    )
    decision = await selector.decide("u", "remind me at 6 to call mum", [], None)
    assert isinstance(decision, Act)
    assert isinstance(decision.action, ScheduleTaskAction)


# The same words, the same names, a different schema: a different offer.
async def test_the_cache_key_changes_when_a_tools_definition_changes():
    before = [{"type": "function", "function": {"name": "t", "parameters": {"a": 1}}}]
    after = [{"type": "function", "function": {"name": "t", "parameters": {"a": 2}}}]
    assert _decision_key("u", "body", before, None) != _decision_key("u", "body", after, None)
    assert _decision_key("u", "body", before, None) == _decision_key("u", "body", list(before), None)


# The same positional alias pointing at a different server's tool is a
# different offer, because the alias's definition carries the tool's own
# description and schema.
async def test_the_cache_key_sees_through_a_positional_mcp_alias():
    def alias(live: MCPTool) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "mcp_tool_0",
                    "description": f"MCP server {live.server_id}, tool {live.name}: {live.description}",
                    "parameters": live.input_schema,
                },
            }
        ]

    assert _decision_key("u", "body", alias(SEARCH_TOOL), None) != _decision_key(
        "u", "body", alias(WEATHER_TOOL), None
    )


# End to end: a remembered decision is not replayed once a schema has moved.
async def test_a_changed_schema_is_decided_again(monkeypatch):
    monkeypatch.setattr(settings, "ROUTING_DECISION_CACHE_SECONDS", 300.0)
    selector, llm = _selector(_tool_call("search_web", {"query": "x"}))
    first = await selector.select("u", "look up x", [], None)
    assert isinstance(first, SearchAction)
    asked = len(llm.messages)

    # The same question again is answered from memory.
    llm.message = {"content": "changed my mind"}
    again = await selector.select("u", "look up x", [], None)
    assert isinstance(again, SearchAction)

    # Now the search tool's schema changes under the same name.
    moved = MCPTool(
        server_id="internet",
        name="search_web",
        description="Research a minimized public query.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "region": {"type": "string"}},
            "required": ["query", "region"],
        },
    )
    selector.mcp_invocation.lister.tools["internet"] = [moved]
    decided = await selector.select("u", "look up x", [], None)
    assert decided is None, "the changed offer must be decided afresh, not replayed"
    assert len(llm.messages) >= asked


# A later step offered by contract sees the bookkeeping tools and the search,
# never the generating tools, and never what the caller excludes.
async def test_a_later_step_is_offered_what_the_contracts_allow():
    selector, llm = _selector({"content": "nothing further"})
    await selector.decide(
        "u",
        "cancel the gym reminder and set one for 6pm",
        [],
        None,
        later_step_seconds=45.0,
        excluding=frozenset({"search_history"}),
        steps_taken=["Scheduled tasks: cancel"],
    )
    offered = {tool["function"]["name"] for tool in llm.tools}
    assert {"schedule_task", "manage_tasks", "search_web"} <= offered
    assert "search_history" not in offered
    assert not ({"generate_image", "edit_image", "create_diagram", "create_document"} & offered)


# With little budget left, a slow search is not on the later-step menu.
async def test_a_slow_search_needs_budget_to_be_a_later_step():
    selector, llm = _selector({"content": "nothing further"})
    await selector.decide(
        "u", "do two things", [], None, later_step_seconds=5.0, steps_taken=["one"]
    )
    offered = {tool["function"]["name"] for tool in llm.tools}
    assert "search_web" not in offered
    assert "schedule_task" in offered


# A named restriction still means exactly the names, as every existing
# caller expects.
async def test_a_named_restriction_offers_exactly_the_names():
    selector, llm = _selector({"content": "nothing further"})
    await selector.decide(
        "u", "x", [], None, only=frozenset({"manage_tasks"}), steps_taken=["one"]
    )
    assert {tool["function"]["name"] for tool in llm.tools} == {"manage_tasks"}


async def test_tool_call_helper_shape():
    assert json.loads(_tool_call("a", {"b": 1})["tool_calls"][0]["function"]["arguments"]) == {"b": 1}
