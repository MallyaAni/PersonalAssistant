"""Does the model actually schedule from plain words, and report it right?

"Remind me every weekday at 7 to check the temps" must become a typed
schedule_task decision with the cadence and hour the person said, and a
question about the weather right now must not. Then the two reply blocks:
a task firing must be carried out rather than confirmed, and a confirmation
must state the saved schedule rather than offer to set one up. Structural
tests prove the plumbing; these send the real prompts to the real models.
"""

import pytest

from backend.agents.graph import _build_system_prompt, _build_turn_context
from backend.services.main_action_selector import (
    MainActionSelector,
    ManageTasksAction,
    ScheduleTaskAction,
)
from backend.tests.functional.semantic import states

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


async def test_a_recurring_reminder_becomes_a_schedule_task_decision(selector):
    action = await selector.select(
        "functional_test_user",
        "remind me every weekday at 7am to check the spark temps",
        [],
        None,
    )
    assert isinstance(action, ScheduleTaskAction), action
    assert action.cadence == "weekdays", action
    assert (action.hour, action.minute) == (7, 0), action
    assert "temp" in action.instruction.lower(), action


async def test_a_daily_message_request_carries_its_hour(selector):
    action = await selector.select(
        "functional_test_user",
        "text me the weather for Arlington every morning at 8",
        [],
        None,
    )
    assert isinstance(action, ScheduleTaskAction), action
    assert action.cadence == "daily", action
    assert action.hour == 8, action
    assert "arlington" in action.instruction.lower(), action


async def test_asking_what_is_scheduled_is_a_list_not_a_new_task(selector):
    action = await selector.select(
        "functional_test_user", "what do I have scheduled?", [], None
    )
    assert isinstance(action, ManageTasksAction), action
    assert action.operation == "list", action


async def test_cancelling_names_the_task_in_the_persons_words(selector):
    action = await selector.select(
        "functional_test_user", "cancel the weather texts", [], None
    )
    assert isinstance(action, ManageTasksAction), action
    assert action.operation == "cancel", action
    assert "weather" in action.which.lower(), action


# "Tomorrow" is resolved against the clock the router is handed, not the
# model's idea of when it is - which put "today" two years in the past.
async def test_tomorrow_resolves_against_the_persons_clock(selector):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/New_York"))
    action = await selector.select(
        "functional_test_user",
        "tomorrow at 9am remind me to renew the car registration",
        [],
        None,
        local_now=f"{now:%A %Y-%m-%d %H:%M} (America/New_York)",
    )
    assert isinstance(action, ScheduleTaskAction), action
    assert action.cadence == "once", action
    assert action.hour == 9, action
    assert action.on_date == (now + timedelta(days=1)).date().isoformat(), action


# A question for right now is not a task, however much it mentions time.
async def test_a_question_for_right_now_is_not_scheduled(selector):
    for query in (
        "what's the weather today in Arlington VA?",
        "what time is it in Tokyo right now?",
    ):
        action = await selector.select("functional_test_user", query, [], None)
        assert not isinstance(action, ScheduleTaskAction | ManageTasksAction), (
            query,
            action,
        )


# The firing: the person is not in the conversation, so the instruction is
# carried out, not confirmed or offered.
async def test_a_firing_task_is_carried_out_not_confirmed(llm):
    system = _build_system_prompt({"channel": "imessage", "scheduled_task": True})
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "send me one short motivational quote to start the day",
            },
        ],
        300,
        None,
        0.0,
    )
    text = str(result["content"])
    assert text.strip()
    assert states(text, "the reply contains a motivational quote"), text
    assert not states(
        text,
        "the reply asks whether to set this up, asks for confirmation, or "
        "asks what time to send it",
    ), text


# The confirmation: the reply states the saved schedule and never offers to
# set up what the record says is already set.
async def test_a_confirmation_states_the_saved_schedule(llm):
    from datetime import UTC, datetime

    context = {
        "channel": "imessage",
        "task_outcome": {
            "kind": "scheduled",
            "task": {
                "instruction": "check the spark temps and tell me",
                "cadence": "weekdays",
                "hour": 7,
                "minute": 0,
                "weekday": 0,
                "timezone": "America/New_York",
                "enabled": True,
                "next_run_at": datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
            },
        },
    }
    system = _build_system_prompt(context)
    turn_context = _build_turn_context(context, include_save_state=False)
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"{turn_context}\n\nremind me every weekday at 7am to check "
                    "the spark temps"
                ),
            },
        ],
        300,
        None,
        0.0,
    )
    text = str(result["content"])
    assert states(
        text, "the reply confirms something is now scheduled for 7:00 AM on weekdays"
    ), text
    assert not states(
        text,
        "the reply asks the person a question - whether to go ahead, what time "
        "they want, or for any other detail - instead of reporting it as done",
    ), text


async def test_a_needed_place_is_asked_for_not_guessed(llm):
    context = {
        "channel": "imessage",
        "task_outcome": {
            "kind": "needs_place",
            "requested": "text me the weather (daily at 08:00)",
        },
    }
    system = _build_system_prompt(context)
    turn_context = _build_turn_context(context, include_save_state=False)
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"{turn_context}\n\ntext me the weather every morning at 8",
            },
        ],
        300,
        None,
        0.0,
    )
    text = str(result["content"])
    assert states(text, "the reply asks where the person is or for their city"), text
    assert not states(text, "the reply says the schedule is already set up"), text


# The live defect: "remind me in five minutes to turn off the stove" was
# saved as "turn off the stove", and the firing answered that the assistant
# cannot control a stove. The reminding is the task and must be kept.
async def test_a_reminder_keeps_the_reminding_as_the_instruction(selector):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/New_York"))
    action = await selector.select(
        "functional_test_user",
        "remind me in 5 minutes to turn off the stove",
        [],
        None,
        local_now=f"{now:%A %Y-%m-%d %H:%M} (America/New_York)",
    )
    assert isinstance(action, ScheduleTaskAction), action
    assert "remind" in action.instruction.lower(), action
    assert "stove" in action.instruction.lower(), action


# And however the instruction was worded, a firing that names something
# the person must do is delivered as a reminder, not refused as an action.
async def test_a_firing_reminder_tells_them_it_is_time(llm):
    system = _build_system_prompt({"channel": "imessage", "scheduled_task": True})
    for instruction in ("remind me to turn off the stove", "turn off the stove"):
        result = llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": instruction},
            ],
            200,
            None,
            0.0,
        )
        text = str(result["content"])
        assert states(text, "the reply tells the person to turn off the stove now"), (
            instruction,
            text,
        )
        assert not states(
            text,
            "the reply says it cannot turn off or control the stove, or offers "
            "to set up a reminder",
        ), (instruction, text)


# The second live family, found by a battery of sixteen realistic
# instructions: when the instruction leans on context the firing turn does
# not have, the model answered "I don't have any record of that. Want to
# tell me?" - which lands as a text at 7am with nobody there to answer.
# A firing never reports its own missing context as the message.
async def test_a_firing_never_makes_its_missing_context_the_message(llm):
    system = _build_system_prompt({"channel": "imessage", "scheduled_task": True})
    for instruction, says in (
        (
            "give me a two-line summary of what I should focus on today",
            "the text talks about what to focus on today",
        ),
        (
            "follow up on the emails I was supposed to send",
            "the text tells the reader to deal with the emails",
        ),
        (
            "remind me to review what we talked about yesterday",
            "the text tells the reader to look back over yesterday",
        ),
    ):
        result = llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": instruction},
            ],
            220,
            None,
            0.0,
        )
        text = str(result["content"])
        assert not states(
            text,
            "the reply says it has no record of the thing, cannot see it, or "
            "asks the person to supply what it was missing",
        ), (instruction, text)
        assert states(text, says), (instruction, text)


# An instruction that asks the assistant to ask something must still ask it.
async def test_an_instruction_to_ask_still_asks(llm):
    system = _build_system_prompt({"channel": "imessage", "scheduled_task": True})
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": "ask me how the gym went"},
        ],
        200,
        None,
        0.0,
    )
    text = str(result["content"])
    assert states(text, "the text asks the reader how the gym went"), text
