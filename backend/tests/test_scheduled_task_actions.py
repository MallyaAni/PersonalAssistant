"""Parsing the task tools, wording a task, and picking one by meaning."""

import json
import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.tasks.describe import describe_task, schedule_phrase
from backend.tasks.picker import pick_task
from backend.tools import (
    ManageTasksAction,
    ScheduleTaskAction,
    parse_builtin,
)


def test_schedule_task_call_becomes_a_typed_action():
    action = parse_builtin(
        "schedule_task",
        {
            "instruction": "text me the weather for Arlington",
            "cadence": "weekdays",
            "hour": 7,
            "minute": 0,
        },
        "",
    )
    assert action == ScheduleTaskAction(
        instruction="text me the weather for Arlington",
        cadence="weekdays",
        hour=7,
        minute=0,
        weekday=0,
        on_date=None,
    )


def test_schedule_task_without_an_instruction_or_with_a_bad_cadence_is_no_call():
    assert parse_builtin("schedule_task", {"cadence": "daily", "hour": 7}, "") is None
    assert (
        parse_builtin(
            "schedule_task", {"instruction": "x", "cadence": "hourly", "hour": 7}, ""
        )
        is None
    )


def test_once_carries_its_date():
    action = parse_builtin(
        "schedule_task",
        {
            "instruction": "call mom",
            "cadence": "once",
            "hour": 17,
            "minute": 30,
            "on_date": "2026-08-23",
        },
        "",
    )
    assert action.on_date == "2026-08-23"
    assert action.hour == 17


# The router once dated "today" two years in the past, from its training
# era, and the task fired at the next poll. A stated date that is already
# gone is discarded and the time decides today or tomorrow.
def test_a_once_date_in_the_past_is_repaired_from_the_time():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from backend.services.conversation_service import _once_date

    zone = "America/New_York"
    now = datetime.now(ZoneInfo(zone))
    ahead = now + timedelta(minutes=30)
    behind = now - timedelta(minutes=30)
    stale = ScheduleTaskAction(
        "hello", "once", ahead.hour, ahead.minute, on_date="2024-05-22"
    )
    assert _once_date(stale, zone) == ahead.date()
    past_time = ScheduleTaskAction(
        "hello", "once", behind.hour, behind.minute, on_date="2024-05-22"
    )
    assert _once_date(past_time, zone) == behind.date() + timedelta(days=1)
    future = ScheduleTaskAction("hello", "once", 9, 0, on_date="2031-01-02")
    assert _once_date(future, zone).isoformat() == "2031-01-02"
    assert _once_date(ScheduleTaskAction("x", "daily", 9, 0), zone) is None


def test_manage_tasks_call_becomes_a_typed_action():
    assert parse_builtin("manage_tasks", {"operation": "list"}, "") == (
        ManageTasksAction(operation="list", which="")
    )
    assert parse_builtin(
        "manage_tasks", {"operation": "cancel", "which": " the weather one "}, ""
    ) == ManageTasksAction(operation="cancel", which="the weather one")
    assert parse_builtin("manage_tasks", {"operation": "delete"}, "") is None


def test_schedule_phrases_read_as_a_person_would_say_them():
    assert schedule_phrase({"cadence": "daily", "hour": 7, "minute": 0}) == (
        "every day at 7:00 AM"
    )
    assert (
        schedule_phrase({"cadence": "weekly", "hour": 18, "minute": 30, "weekday": 4})
        == "every Friday at 6:30 PM"
    )
    assert (
        schedule_phrase(
            {"cadence": "once", "hour": 0, "minute": 5, "on_date": "2026-08-23"}
        )
        == "once on 2026-08-23 at 12:05 AM"
    )
    assert (
        describe_task(
            {
                "instruction": "stretch",
                "cadence": "weekdays",
                "hour": 9,
                "minute": 0,
                "enabled": False,
            }
        )
        == '"stretch" - every weekday at 9:00 AM (paused)'
    )


class _PickingLLM:
    def __init__(self, task_id: str | None):
        self.task_id = task_id
        self.calls: list = []

    def chat_with_tools(self, messages, tools, max_tokens=256):
        self.calls.append((messages, tools))
        if self.task_id is None:
            return {"content": "none of these"}
        return {
            "tool_calls": [
                {
                    "function": {
                        "name": "pick_item",
                        "arguments": json.dumps({"item_id": self.task_id}),
                    }
                }
            ]
        }


_TASKS = [
    {
        "id": "t1",
        "instruction": "text me the weather",
        "cadence": "daily",
        "hour": 7,
        "minute": 0,
    },
    {
        "id": "t2",
        "instruction": "remind me to stretch",
        "cadence": "weekdays",
        "hour": 9,
        "minute": 0,
    },
]


@pytest.mark.asyncio
async def test_single_task_is_picked_without_asking_the_model():
    llm = _PickingLLM("t2")
    assert await pick_task(llm, "the weather one", _TASKS[:1]) == "t1"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_model_picks_among_several_and_only_offered_ids_count():
    llm = _PickingLLM("t2")
    assert await pick_task(llm, "the stretching one", _TASKS) == "t2"
    offered = llm.calls[0][1][0]["function"]["parameters"]["properties"]["item_id"]
    assert offered["enum"] == ["t1", "t2"]
    assert await pick_task(_PickingLLM("t9"), "something", _TASKS) is None
    assert await pick_task(_PickingLLM(None), "something", _TASKS) is None
