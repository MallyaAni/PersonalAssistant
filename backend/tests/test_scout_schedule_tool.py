"""scout_schedule: Scout's own sweep cadence as a named tool.

Its own row so the router chooses between two named things - the measured
fix for "change the schedule to 9:25pm" after talk of Scout being read as a
task reschedule (backend/tools/manage_tasks.py).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.agents.graph import _render_scout_schedule_outcome
from backend.tools import AUTOMATION_TOOLS, ScoutScheduleAction, describe_action, parse_builtin


def test_the_call_becomes_a_typed_action():
    assert parse_builtin("scout_schedule", {"cadence": "daily", "hour": 15}, "") == (
        ScoutScheduleAction(cadence="daily", hour=15, minute=0, weekday=0)
    )
    assert parse_builtin(
        "scout_schedule", {"cadence": "weekly", "hour": 9, "minute": 25, "weekday": 6}, ""
    ) == ScoutScheduleAction(cadence="weekly", hour=9, minute=25, weekday=6)


def test_a_missing_hour_or_a_task_cadence_is_no_call():
    assert parse_builtin("scout_schedule", {"cadence": "daily"}, "") is None
    assert parse_builtin("scout_schedule", {"cadence": "once", "hour": 9}, "") is None
    assert parse_builtin("scout_schedule", {"cadence": "daily", "hour": 24}, "") is None


def test_it_is_withheld_from_a_firing_and_labelled_for_the_person():
    assert "scout_schedule" in AUTOMATION_TOOLS
    assert describe_action(ScoutScheduleAction("daily", 15)) == ("Scout schedule", "daily at 15:00")


def test_the_outcome_tells_the_reply_it_is_the_sweep_not_a_reminder():
    text = _render_scout_schedule_outcome(
        {
            "kind": "scheduled",
            "schedule": {
                "cadence": "daily", "hour": 15, "minute": 0, "weekday": 0,
                "timezone": "America/New_York",
                "next_run_at": datetime(2026, 8, 27, 19, 0, tzinfo=UTC),
            },
        }
    )
    assert "every day at 3:00 PM (America/New_York)" in text
    assert "no saved task or reminder was changed" in text
    assert "Next sweep: Thursday 2026-08-27 at 3:00 PM" in text


def test_no_place_means_not_changed():
    text = _render_scout_schedule_outcome({"kind": "needs_place", "requested": "daily at 15:00"})
    assert "Not changed" in text and "which city" in text


@pytest.mark.asyncio
async def test_the_service_sets_the_sweep_in_the_persons_zone():
    from backend.services.conversation_service import ConversationService

    class _Runs:
        def __init__(self):
            self.calls = []

        async def upsert_schedule(self, user_id, cadence):
            self.calls.append((user_id, cadence))
            return {"cadence": cadence.cadence, "hour": cadence.hour, "minute": cadence.minute,
                    "weekday": cadence.weekday, "timezone": cadence.timezone, "next_run_at": None}

    service = ConversationService.__new__(ConversationService)
    service.discovery_runs = _Runs()
    service.discovery_profile = object()

    async def _zone(user_id):
        return "America/New_York"

    service._primary_timezone = _zone
    outcome = await service._apply_scout_schedule("ani", ScoutScheduleAction("daily", 15))
    assert outcome["kind"] == "scheduled"
    assert outcome["schedule"]["hour"] == 15
    user, cadence = service.discovery_runs.calls[0]
    assert user == "ani" and cadence.timezone == "America/New_York" and cadence.cadence == "daily"

    async def _none(user_id):
        return None

    service._primary_timezone = _none
    assert (await service._apply_scout_schedule("ani", ScoutScheduleAction("daily", 15)))["kind"] == "needs_place"
    assert service.discovery_runs.calls[0] and len(service.discovery_runs.calls) == 1
