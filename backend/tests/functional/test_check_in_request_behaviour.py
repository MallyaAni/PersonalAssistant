"""Check-ins on request, against the real models. The router must send the
ask to manage_check_ins with the mode the words mean - one thing by name,
the habit from now on, stopping - and leave a passing mention alone. Then
the reply side: told check-ins are on, or that one is set, the model says so
in a line and does not call it a task or an automation.

Structural tests prove the plumbing; these send the real prompts.
"""
import pytest

from backend.agents.graph import _build_system_prompt, _build_turn_context
from backend.services.main_action_selector import MainActionSelector
from backend.tests.functional.semantic import states
from backend.tools.actions import ManageCheckInsAction

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session")
def selector(llm):
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service

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


@pytest.mark.parametrize(
    ("asked", "mode"),
    [
        ("check in with me on Friday about how the interview went", "once"),
        ("from now on, check in on me about the things I mention", "on"),
        ("stop checking in on me", "off"),
    ],
)
async def test_the_ask_reaches_the_tool_with_the_mode_the_words_mean(selector, asked, mode):
    action = await selector.select("check_in_request_eval", asked, [], None)
    assert isinstance(action, ManageCheckInsAction), f"routed to {type(action).__name__} for {asked!r}"
    assert action.mode == mode, action
    if mode == "once":
        assert "interview" in f"{action.subject} {action.question}".lower(), action


async def test_a_passing_mention_is_not_a_request_for_a_check_in(selector):
    action = await selector.select("check_in_request_eval", "I put an offer in on a car this morning", [], None)
    assert not isinstance(action, ManageCheckInsAction), action


def _reply(llm, context: dict, asked: str) -> str:
    system = _build_system_prompt(context)
    turn_context = _build_turn_context(context, include_save_state=False)
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{turn_context}\n\n{asked}"},
        ],
        300,
        None,
        0.0,
    )
    return str(result["content"])


async def test_turning_them_on_is_confirmed_in_a_line_not_a_rulebook(llm):
    text = _reply(
        llm,
        {"channel": "imessage", "task_outcome": {"kind": "check_ins_on", "already": False, "waiting": []}},
        "from now on, check in on me about the things I mention",
    )
    assert states(text, "the reply says check-ins are now on, or that it will follow up on things from now on"), text
    assert not states(text, "the reply asks the person a question instead of confirming"), text
    assert not states(text, "the reply describes it as an automation, a task, or a scheduled job"), text


async def test_one_set_by_name_is_promised_in_their_words(llm):
    from datetime import UTC, datetime

    text = _reply(
        llm,
        {
            "channel": "imessage",
            "task_outcome": {
                "kind": "check_in_armed",
                "subject": "the interview",
                "task": {
                    "instruction": "How did the interview go?",
                    "cadence": "once",
                    "hour": 18,
                    "minute": 0,
                    "weekday": 0,
                    "timezone": "America/New_York",
                    "enabled": True,
                    "kind": "checkin:following_up",
                    "next_run_at": datetime(2026, 9, 4, 22, 0, tzinfo=UTC),
                },
            },
        },
        "check in with me on Friday about how the interview went",
    )
    assert states(text, "the reply says it will ask about the interview later, on Friday or in a few days"), text
    assert not states(text, "the reply calls it a task, a reminder, or an automation"), text


async def test_turning_them_off_is_reported_plainly(llm):
    text = _reply(
        llm,
        {"channel": "imessage", "task_outcome": {"kind": "check_ins_off", "dropped": 1}},
        "stop checking in on me",
    )
    assert states(text, "the reply says check-ins are off or that it will stop checking in"), text
    assert not states(text, "the reply argues, apologises at length, or asks whether they are sure"), text
