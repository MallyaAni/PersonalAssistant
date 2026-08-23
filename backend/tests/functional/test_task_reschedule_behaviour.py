"""Rescheduling a task has to move it, against the real router and the real clock.

This file exists because of one turn on 2026-08-23. Asked to "change the tesla
reminder to remind me in 5 minutes", the assistant replied "now set for 5
minutes from now - I'll ping you then", and the row in `scheduled_tasks` was
untouched: same `next_run_at`, `updated_at` still the previous day. The reminder
never arrived, and nothing anywhere reported a failure.

There was no bug to find in the code that ran. `manage_tasks` offered only
list, cancel, pause and resume; its own description said changing a time meant
cancelling and scheduling again. That is two tool calls, and the selector makes
one decision per turn - so the request was not expressible, and the model
narrated a success instead of failing.

A structural test would have passed throughout: the router was called, a tool
was chosen, a reply came back. So these assert the thing that was actually
false - **the stored schedule moved** - and run the real selector against the
configured routing model rather than a stub, because the defect was in what the
model could express, not in how the application handled what it expressed.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.config.settings import settings
from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_routing_llm_client,
)
from backend.discovery.schedule import Cadence
from backend.services.main_action_selector import MainActionSelector
from backend.database.session import AsyncSessionLocal
from backend.tasks.repository import ScheduledTaskRepository
from backend.tools.actions import ManageTasksAction, ScheduleTaskAction

ZONE = "America/New_York"

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


def _selector() -> MainActionSelector:
    return MainActionSelector(
        get_routing_llm_client(),
        get_mcp_invocation_service(),
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


_TESLA_HISTORY = [
    {
        "role": "user",
        "content": "set a reminder for my tesla software update for tomorrow 12pm",
    },
    {"role": "assistant", "content": "Done - reminder set for tomorrow at 12:00 PM."},
]


async def test_moving_a_reminder_is_routed_as_a_reschedule() -> None:
    """The request the assistant could not express before.

    Asserting the operation and the resolved clock time, not merely that
    `manage_tasks` was chosen: choosing the tool and then listing - which is
    what happened when reschedule did not exist - would satisfy a weaker
    assertion while leaving the reminder exactly where it was.
    """
    local_now = datetime(2026, 8, 23, 10, 38, tzinfo=ZoneInfo(ZONE))
    action = await _selector().select(
        user_id="functional-tests",
        query="change the tesla reminder to remind me in 5 minutes",
        history=_TESLA_HISTORY,
        active_image_artifact_id=None,
        local_now=local_now.strftime("%Y-%m-%d %H:%M ") + ZONE,
    )

    assert isinstance(action, ManageTasksAction), f"routed to {type(action).__name__}"
    assert action.operation == "reschedule", f"operation was {action.operation!r}"
    assert action.which, "the task to move was not identified"
    # Five minutes after 10:38 is 10:43. Allowing a minute either side keeps
    # this about arithmetic rather than about tokenisation.
    minutes = action.hour * 60 + action.minute
    assert abs(minutes - (10 * 60 + 43)) <= 1, f"resolved to {action.hour}:{action.minute:02d}"


async def test_scheduling_a_new_thing_is_not_read_as_a_reschedule() -> None:
    """The opposite error, which the new operation makes newly possible.

    A `reschedule` chosen for a fresh request would move an unrelated task and
    silently drop the one being asked for.
    """
    action = await _selector().select(
        user_id="functional-tests",
        query="remind me to take the bins out at 7pm",
        history=[],
        active_image_artifact_id=None,
        local_now="2026-08-23 10:38 " + ZONE,
    )
    assert isinstance(action, ScheduleTaskAction), f"routed to {type(action).__name__}"
    assert action.hour == 19, f"hour was {action.hour}"


async def test_reschedule_moves_the_stored_row() -> None:
    """The assertion that was false while the reply said otherwise."""
    async with AsyncSessionLocal() as session:
        await _reschedule_moves_the_stored_row(ScheduledTaskRepository(session))


async def _reschedule_moves_the_stored_row(tasks) -> None:
    user = "functional-tests-reschedule"
    created = await tasks.create(
        user,
        "remind me to do my tesla software update",
        Cadence(
            cadence="once",
            hour=12,
            minute=0,
            weekday=0,
            timezone=ZONE,
            on_date=datetime.now(ZoneInfo(ZONE)).date() + timedelta(days=1),
        ),
        channel="imessage",
    )
    before = created["next_run_at"]

    target = datetime.now(ZoneInfo(ZONE)) + timedelta(minutes=5)
    moved = await tasks.reschedule_owned(
        user,
        created["id"],
        Cadence(
            cadence="once",
            hour=target.hour,
            minute=target.minute,
            weekday=0,
            timezone=ZONE,
            on_date=target.date(),
        ),
    )

    assert moved is not None, "reschedule reported no such task"
    assert moved["next_run_at"] != before, "next_run_at did not move"
    drift = abs((moved["next_run_at"] - target.astimezone(UTC)).total_seconds())
    assert drift < 90, f"armed {drift:.0f}s away from the requested moment"
    assert moved["enabled"] is True, "a rescheduled task must be armed"
    # Wording is carried over: only the time was asked to change.
    assert moved["instruction"] == created["instruction"]

    await tasks.delete_owned(user, created["id"])


async def test_reschedule_keeps_a_recurring_task_recurring() -> None:
    """"Move the stretch reminder to 7pm" must not end the series.

    The router leaves `cadence` out when only a time is changing, and reading
    that as "once" would convert a weekdays reminder into a single firing -
    with a reply that confirms the new time and says nothing about the change.
    """
    async with AsyncSessionLocal() as session:
        await _keeps_recurring(ScheduledTaskRepository(session))


async def _keeps_recurring(tasks) -> None:
    user = "functional-tests-recurring"
    created = await tasks.create(
        user,
        "remind me to stretch",
        Cadence(
            cadence="weekdays", hour=18, minute=0, weekday=0, timezone=ZONE, on_date=None
        ),
        channel="web",
    )

    # Exactly what `_reschedule_task` builds when the model sends no cadence.
    moved = await tasks.reschedule_owned(
        user,
        created["id"],
        Cadence(
            cadence=created["cadence"],
            hour=19,
            minute=0,
            weekday=created["weekday"],
            timezone=created["timezone"],
            on_date=None,
        ),
    )

    assert moved is not None
    assert moved["cadence"] == "weekdays", f"cadence became {moved['cadence']!r}"
    assert moved["hour"] == 19

    await tasks.delete_owned(user, created["id"])
