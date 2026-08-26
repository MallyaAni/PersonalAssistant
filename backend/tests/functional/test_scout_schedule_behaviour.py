"""Does "adjust this to daily at 3pm" go to Scout after Scout, and to the
reminder after a reminder? And does the reply then say the right thing?

2026-08-26: with only manage_tasks to choose, the router sent the Scout
continuation there and a stretch reminder moved. scout_schedule is the
named alternative; these are the two shapes of the same words.
"""

from __future__ import annotations

import pytest

from backend.agents.graph import _build_system_prompt, _build_turn_context
from backend.tests.functional.semantic import states
from backend.tools import ManageTasksAction, ScoutScheduleAction

pytestmark = pytest.mark.asyncio


@pytest.fixture
def selector(llm):
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service
    from backend.services.main_action_selector import MainActionSelector

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip("internet MCP server is not configured as auto-invocable")
    return MainActionSelector(
        llm,
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


_AFTER_SCOUT = [
    {"query": "when does scout run its sweep?",
     "response": "Scout isn't on a schedule yet - it only sweeps when asked, and it needs an interest to follow before it can find anything. Want me to set a time?"},
]
_AFTER_REMINDER = [
    {"query": "send me a don tito reminder tonight at 7",
     "response": "Done - I've set a reminder about Don Tito's for tonight at 7:00 PM."},
]


async def test_this_after_scout_sets_the_sweep(selector):
    action = await selector.select("functional_test_user", "adjust this to daily at 3pm", _AFTER_SCOUT, None)
    assert isinstance(action, ScoutScheduleAction), action
    assert (action.cadence, action.hour) == ("daily", 15), action


async def test_this_after_a_reminder_moves_that_reminder(selector):
    action = await selector.select("functional_test_user", "adjust this to daily at 3pm", _AFTER_REMINDER, None)
    assert isinstance(action, ManageTasksAction), action
    assert action.operation == "reschedule", action


async def test_a_named_sweep_change_needs_no_history(selector):
    action = await selector.select("functional_test_user", "run scout every day at 3pm", [], None)
    assert isinstance(action, ScoutScheduleAction), action


async def test_the_reply_reports_the_sweep_not_a_reminder(llm):
    from datetime import UTC, datetime

    context = {
        "channel": "imessage",
        "scout_schedule_outcome": {
            "kind": "scheduled",
            "schedule": {
                "cadence": "daily", "hour": 15, "minute": 0, "weekday": 0,
                "timezone": "America/New_York",
                "next_run_at": datetime(2026, 8, 27, 19, 0, tzinfo=UTC),
            },
        },
    }
    system = _build_system_prompt(context)
    turn_context = _build_turn_context(context, include_save_state=False)
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{turn_context}\n\nadjust this to daily at 3pm"},
        ],
        300,
        None,
        0.0,
    )
    text = str(result["content"])
    assert states(text, "The reply says Scout's sweep or check now runs daily at 3 PM."), text
    assert not states(text, "The reply says a reminder was moved, rescheduled, or changed."), text
