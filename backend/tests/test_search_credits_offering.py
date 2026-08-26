"""The search meter is offered to the operator and to nobody else."""

from __future__ import annotations

import pytest

from backend.search.budgeted import SearchIdentity, current_search_identity
from backend.services.main_action_selector import MainActionSelector
from backend.services.mcp_invocation_service import MCPInvocationService
from backend.services.mcp_tool_orchestration_service import MCPToolOrchestrationService
from backend.tests.test_main_action_selector import (
    SEARCH_TOOL,
    MCPServerConfig,
    MCPTool,
    DescriptorMemory,
    FixedToolLLM,
    LiveLister,
    RecordingInvoker,
    _tool_call,
)
from backend.tools.actions import ToolboxAction

CREDITS_TOOL = MCPTool(
    server_id="internet",
    name="search_credits",
    description="Report the web-search credits left on the shared key.",
    input_schema={"type": "object", "properties": {}, "required": []},
)


def _selector(message: dict) -> tuple[MainActionSelector, FixedToolLLM]:
    llm = FixedToolLLM(message)
    invocation = MCPInvocationService(
        RecordingInvoker(),  # type: ignore[arg-type]
        LiveLister({"internet": [SEARCH_TOOL, CREDITS_TOOL]}),  # type: ignore[arg-type]
        (MCPServerConfig(server_id="internet", command="noop", risk_classification="read_only"),),
    )
    orchestration = MCPToolOrchestrationService(DescriptorMemory([]), invocation, llm)  # type: ignore[arg-type]
    selector = MainActionSelector(
        llm, invocation, "internet", "search_web", orchestration,
        diagram_enabled=False, presentation_enabled=False,
    )
    return selector, llm


async def _offered_to(is_operator: bool) -> tuple[set[str], object, list[dict]]:
    selector, llm = _selector(_tool_call("search_credits", {}))
    token = current_search_identity.set(SearchIdentity(user_id="who", is_operator=is_operator))
    try:
        action = await selector.select("who", "how many search credits do we have left?", [], None)
        capabilities = selector.describe_capabilities()
    finally:
        current_search_identity.reset(token)
    return {tool["function"]["name"] for tool in llm.tools}, action, capabilities


@pytest.mark.asyncio
async def test_the_operator_is_offered_the_meter_and_may_choose_it() -> None:
    names, action, capabilities = await _offered_to(True)
    assert "search_credits" in names
    assert isinstance(action, ToolboxAction) and action.plan.tool_name == "search_credits"
    assert any(item["label"] == "Search credits" for item in capabilities)


@pytest.mark.asyncio
async def test_a_guest_is_neither_offered_nor_told_about_the_meter() -> None:
    names, action, capabilities = await _offered_to(False)
    assert "search_credits" not in names
    # The model "chose" it anyway in this fixture; a name never offered is refused.
    assert not isinstance(action, ToolboxAction)
    assert not any(item["label"] == "Search credits" for item in capabilities)


@pytest.mark.asyncio
async def test_search_stays_on_the_menu_while_an_allowance_is_used_up() -> None:
    # The router's choice is what tells a turn that wanted a search apart from
    # one that did not; the budget refuses the chosen search, locally.
    from datetime import UTC, datetime

    from backend.search.budgeted import SearchLimit, current_search_limit

    selector, llm = _selector(_tool_call("search_web", {"query": "events this weekend"}))
    token = current_search_limit.set(SearchLimit("today", datetime(2026, 8, 26, tzinfo=UTC)))
    try:
        action = await selector.select("guest", "what's on in Arlington this weekend?", [], None)
    finally:
        current_search_limit.reset(token)
    assert "search_web" in {tool["function"]["name"] for tool in llm.tools}
    assert action is not None


@pytest.mark.asyncio
async def test_a_firing_is_not_offered_shipped_packs() -> None:
    selector, llm = _selector(_tool_call("search_web", {"query": "x"}))
    skills = [
        {"id": "s1", "slug": "morning-brief", "name": "morning brief", "description": "d", "instruction": "i", "source": "user"},
        {"id": "pack:quick-brief", "slug": "quick-brief", "name": "Quick brief", "description": "d", "instruction": "i", "source": "pack"},
    ]
    await selector.select("who", "Remind me to stretch", [], None, skills=skills, unattended=True)
    names = {tool["function"]["name"] for tool in llm.tools}
    assert any("morning" in name for name in names), names
    assert not any("quick" in name for name in names), names
    await selector.select("who", "give me a quick brief on x", [], None, skills=skills, unattended=False)
    assert any("quick" in name for name in {tool["function"]["name"] for tool in llm.tools})
