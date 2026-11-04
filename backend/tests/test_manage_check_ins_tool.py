"""Check-ins on request, and off until asked: the tool parses into an action,
the automatic judgement is skipped for anyone who has not opted in, and the
apply step sets the preference, drops what is waiting on "off", and arms one
on "once" within the same limits as the judgement."""
import json
from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.conversation_service import ConversationService
from backend.tools import manage_check_ins
from backend.tools.actions import (
    ManageCheckInsAction,
    ManageTasksAction,
    ScheduleTaskAction,
    ScoutScheduleAction,
)
from backend.tools.registry import AUTOMATION_TOOLS, builtin_tools, parse_builtin


def test_the_tool_is_offered_parses_and_counts_as_automation():
    assert any(tool.name == "manage_check_ins" for tool in builtin_tools())
    assert "manage_check_ins" in AUTOMATION_TOOLS
    action = parse_builtin(
        "manage_check_ins",
        {"mode": "once", "subject": "the interview", "question": "How did the interview go?", "after_days": 2, "hour": 18},
        "check in with me on Friday about how the interview went",
    )
    assert action == ManageCheckInsAction(
        mode="once", subject="the interview", question="How did the interview go?", after_days=2, hour=18, kind="following_up"
    )


def test_a_statement_about_their_day_is_no_action_whatever_the_model_chose():
    # Routed to the tool 3/3 right after "from now on, check in on me…" on
    # the real router (2026-09-02); the words decide in code.
    assert parse_builtin("manage_check_ins", {"mode": "once", "subject": "the offer on the car"}, "I put an offer in on a car this morning") is None
    assert parse_builtin("manage_check_ins", {"mode": "on"}, "we're heading to National Harbor on Saturday") is None
    for asked in (
        "check in with me on Friday about how the interview went",
        "from now on, check in on me about the things I mention",
        "stop checking in on me",
        "can you follow up with me next week about how the move went?",
        "what check-ins do you have waiting for me?",
    ):
        assert parse_builtin("manage_check_ins", {"mode": "status"}, asked) is not None, asked


def test_a_bad_mode_or_an_empty_once_is_no_action_and_kinds_are_held_to_ours():
    assert manage_check_ins.parse({"mode": "sometimes"}) is None
    assert manage_check_ins.parse({"mode": "once"}) is None
    assert manage_check_ins.parse({"mode": "on"}) == ManageCheckInsAction(mode="on")
    assert manage_check_ins.parse({"mode": "once", "question": "How was it?", "kind": "nagging"}).kind == "following_up"
    assert manage_check_ins.parse({"mode": "once", "subject": "x", "after_days": "soon"}) is None


class _Profiles:
    def __init__(self, preferences: dict[str, Any] | None = None) -> None:
        self.preferences = dict(preferences or {})
        self.saved: list[dict[str, Any]] = []

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "name": None, "preferences": dict(self.preferences)}

    async def upsert_user_profile(self, user_id: str, name, preferences: dict[str, Any]) -> None:
        self.preferences = dict(preferences)
        self.saved.append(dict(preferences))

    async def update_preferences(self, user_id: str, patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if value is None:
                self.preferences.pop(key, None)
            else:
                self.preferences[key] = value
        self.saved.append(dict(patch))


class _Tasks:
    """Enough of the task repository for arming, standing down and undo."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.deleted: list[str] = []
        self.changes: list[dict[str, Any]] = []
        # The change log is a second commit after the write. Setting this
        # simulates a connection drop between the two.
        self.change_fails = False

    async def list_for_user(self, user_id: str, enabled_only: bool = True):
        return [dict(row) for row in self.rows if row.get("enabled", True) or not enabled_only]

    async def create(self, user_id, instruction, cadence, channel, kind=None, subject="", **_):
        row = {
            "id": f"t{len(self.rows) + 1}",
            "user_id": user_id,
            "instruction": instruction,
            "kind": kind,
            "subject": subject,
            "enabled": True,
            "next_run_at": None,
            "created_at": None,
        }
        self.rows.append(row)
        return row

    async def delete_owned(self, user_id, task_id):
        self.rows = [row for row in self.rows if row["id"] != task_id]
        self.deleted.append(task_id)
        return True

    async def record_change(self, user_id, kind, operation, before, after, task_id=None, conversation_id=None, turn_id=None):
        if self.change_fails:
            raise RuntimeError("the change log is unreachable")
        change = {
            "user_id": user_id,
            "kind": kind,
            "operation": operation,
            "before": before,
            "after": after,
            "task_id": task_id,
            "conversation_id": conversation_id,
        }
        self.changes.append(change)
        return change


def _service(profiles: _Profiles, tasks: _Tasks, timezone: str = "America/New_York") -> ConversationService:
    service = ConversationService.__new__(ConversationService)
    service.memory = profiles
    service.scheduled_tasks = tasks
    service.discovery_profile = object()
    service.check_in_llm = object()
    service.main_action_selector = None

    async def primary_timezone(user_id: str) -> str | None:
        return timezone or None

    service._primary_timezone = primary_timezone  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_the_judgement_is_skipped_until_the_person_opts_in(monkeypatch):
    profiles, tasks = _Profiles(), _Tasks()
    service = _service(profiles, tasks)
    judged: list[str] = []

    async def propose(*args, **kwargs):
        judged.append("judged")
        return None

    monkeypatch.setattr("backend.services.conversation_service.propose_check_in", propose)
    await service._arm_check_in("I put an offer in on a car this morning", "u-1", {"channel": "web"}, None, "America/New_York")
    assert judged == [], "off by default: the judgement must not even run"
    profiles.preferences["check_ins"] = True
    await service._arm_check_in("I put an offer in on a car this morning", "u-1", {"channel": "web"}, None, "America/New_York")
    assert judged == ["judged"]


@pytest.mark.asyncio
async def test_on_sets_the_preference_and_off_drops_what_is_waiting():
    profiles, tasks = _Profiles(), _Tasks()
    service = _service(profiles, tasks)
    outcome = await service._apply_check_ins("u-1", ManageCheckInsAction(mode="on"), {"channel": "web"})
    assert outcome["kind"] == "check_ins_on" and outcome["already"] is False
    assert profiles.preferences == {"check_ins": True}
    again = await service._apply_check_ins("u-1", ManageCheckInsAction(mode="on"), {"channel": "web"})
    assert again["already"] is True
    armed = await service._apply_check_ins(
        "u-1", ManageCheckInsAction(mode="once", subject="the interview", question="How did the interview go?", after_days=2), {"channel": "web"}
    )
    assert armed["kind"] == "check_in_armed" and armed["task"]["kind"] == "checkin:following_up"
    assert armed["task"]["instruction"] == "How did the interview go?"
    status = await service._apply_check_ins("u-1", ManageCheckInsAction(mode="status"), {"channel": "web"})
    assert status == {"kind": "check_ins_status", "enabled": True, "waiting": ["the interview"]}
    off = await service._apply_check_ins("u-1", ManageCheckInsAction(mode="off"), {"channel": "web"})
    assert off == {"kind": "check_ins_off", "dropped": 1}
    assert profiles.preferences == {"check_ins": False} and tasks.rows == []


@pytest.mark.asyncio
async def test_once_is_held_to_the_same_limits_and_needs_a_place():
    profiles, tasks = _Profiles(), _Tasks()
    service = _service(profiles, tasks, timezone="")
    outcome = await service._apply_check_ins("u-1", ManageCheckInsAction(mode="once", subject="the trip"), {"channel": "web"})
    assert outcome["kind"] == "needs_place"
    service = _service(profiles, tasks)
    for subject in ("the trip", "the dentist", "the offer on the car"):
        armed = await service._apply_check_ins("u-1", ManageCheckInsAction(mode="once", subject=subject, after_days=1), {"channel": "web"})
        assert armed["kind"] == "check_in_armed", subject
    fourth = await service._apply_check_ins("u-1", ManageCheckInsAction(mode="once", subject="the concert", after_days=1), {"channel": "web"})
    assert fourth["kind"] == "check_in_refused" and fourth["reason"] == "too_many_waiting"
    # How someone is doing is never asked in a room.
    room = await service._apply_check_ins(
        "group:abc", ManageCheckInsAction(mode="once", subject="the week", kind="wellbeing", after_days=3), {"channel": "imessage_group"}
    )
    assert room["kind"] == "check_in_refused" and room["reason"] == "sensitive_in_room"


# Pausing and resuming through manage_tasks can leave more than MAX_WAITING
# enabled. "Stop checking in on me" has to reach all of them, not the first
# three the judgement is shown.
@pytest.mark.asyncio
async def test_off_drops_every_enabled_check_in_past_the_cap():
    profiles, tasks = _Profiles({"check_ins": True}), _Tasks()
    for index in range(5):
        tasks.rows.append(
            {
                "id": f"t{index}",
                "user_id": "u-1",
                "instruction": f"ask about thing {index}",
                "kind": "checkin:following_up",
                "subject": f"thing {index}",
                "enabled": True,
                "next_run_at": None,
            }
        )
    service = _service(profiles, tasks)

    off = await service._apply_check_ins("u-1", ManageCheckInsAction(mode="off"), {"channel": "web"})

    assert off == {"kind": "check_ins_off", "dropped": 5}
    assert tasks.rows == []
    assert profiles.preferences == {"check_ins": False}


# Asking for a check-in is an explicit opt-in: arming one while check-ins
# are off turns them back on, so the fire-time gate cannot suppress the one
# the person just asked for.
@pytest.mark.asyncio
async def test_arming_while_off_turns_check_ins_on():
    profiles, tasks = _Profiles(), _Tasks()
    service = _service(profiles, tasks)

    armed = await service._apply_check_ins(
        "u-1",
        ManageCheckInsAction(mode="once", subject="the interview", after_days=1),
        {"channel": "web"},
    )

    assert armed["kind"] == "check_in_armed"
    assert armed["enabled_now"] is True
    assert profiles.preferences == {"check_ins": True}


# "Stop checking in on me" can land while the judgement is running. The
# preference is re-read before the create, so the question the person just
# refused is not armed after the stand-down.
@pytest.mark.asyncio
async def test_stop_during_the_judgement_stops_the_arm(monkeypatch):
    from backend.core.checkin import CheckIn, Judgement

    profiles, tasks = _Profiles({"check_ins": True}), _Tasks()
    service = _service(profiles, tasks)

    async def propose(*args, **kwargs):
        profiles.preferences["check_ins"] = False
        return Judgement(
            arm=CheckIn(
                kind="following_up",
                subject="the interview",
                question="How did the interview go?",
                after_days=1,
                hour=18,
            )
        )

    monkeypatch.setattr("backend.services.conversation_service.propose_check_in", propose)
    await service._arm_check_in(
        "the interview is on Friday",
        "u-1",
        {"channel": "web"},
        None,
        "America/New_York",
    )

    assert tasks.rows == []


# An armed check-in is an ordinary one-off task, and undo acts on the change
# log. Without this entry "check in with me Friday" then "undo that" either
# said there was nothing to undo or removed the previous unrelated change.
@pytest.mark.asyncio
async def test_an_armed_check_in_is_recorded_for_undo():
    profiles, tasks = _Profiles({"check_ins": True}), _Tasks()
    service = _service(profiles, tasks)

    armed = await service._apply_check_ins(
        "u-1",
        ManageCheckInsAction(mode="once", subject="the interview", after_days=1),
        {"channel": "web"},
    )

    assert armed["kind"] == "check_in_armed"
    assert len(tasks.changes) == 1
    change = tasks.changes[0]
    assert (change["kind"], change["operation"]) == ("scheduled", "create")
    assert change["task_id"] == armed["task"]["id"]
    assert change["after"] == armed["task"]


# The change log is a second commit after the write. A drop between the two
# must not deny a write that already happened: the reminder exists and will
# fire, and the cancel already landed. The lost entry costs the undo, not the
# change.
@pytest.mark.asyncio
async def test_a_failed_change_log_write_does_not_deny_the_armed_check_in():
    profiles, tasks = _Profiles({"check_ins": True}), _Tasks()
    tasks.change_fails = True
    service = _service(profiles, tasks)

    armed = await service._apply_check_ins(
        "u-1",
        ManageCheckInsAction(mode="once", subject="the interview", after_days=1),
        {"channel": "web"},
    )

    assert armed["kind"] == "check_in_armed"
    assert len(tasks.rows) == 1


@pytest.mark.asyncio
async def test_a_failed_change_log_write_does_not_deny_a_scheduled_reminder():
    profiles, tasks = _Profiles(), _Tasks()
    tasks.change_fails = True
    service = _service(profiles, tasks)

    outcome = await service._schedule_task(
        "u-1",
        ScheduleTaskAction(
            instruction="text me the weather", cadence="daily", hour=7, minute=0
        ),
        {"channel": "web"},
    )

    assert outcome["kind"] == "scheduled"
    assert [row["instruction"] for row in tasks.rows] == ["text me the weather"]


class _Picks:
    """The picker model, naming the task it was offered."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id

    def chat_with_tools(self, messages, tools, max_tokens=256):
        return {
            "tool_calls": [
                {
                    "function": {
                        "name": "pick_items",
                        "arguments": json.dumps({"item_ids": [self.task_id]}),
                    }
                }
            ]
        }


@pytest.mark.asyncio
async def test_a_failed_change_log_write_does_not_deny_a_cancelled_task():
    profiles = _Profiles()
    tasks = _Tasks(
        [
            {
                "id": "t1",
                "user_id": "u-1",
                "instruction": "stretch",
                "cadence": "daily",
                "hour": 9,
                "minute": 0,
                "enabled": True,
            }
        ]
    )
    tasks.change_fails = True
    service = _service(profiles, tasks)
    service.llm = _Picks("t1")

    outcome = await service._manage_tasks(
        "u-1", ManageTasksAction(operation="cancel", which="the stretching one")
    )

    assert outcome["kind"] == "cancelled"
    assert tasks.rows == []


class _Runs:
    """Enough of Scout's run repository to set and read the sweep's time."""

    def __init__(self) -> None:
        self.schedule: dict[str, Any] | None = None

    async def get_schedule(self, user_id: str) -> dict[str, Any] | None:
        return self.schedule

    async def upsert_schedule(self, user_id: str, cadence, enabled: bool = True):
        self.schedule = {
            "cadence": cadence.cadence,
            "hour": cadence.hour,
            "minute": cadence.minute,
            "weekday": cadence.weekday,
            "timezone": cadence.timezone,
            "enabled": enabled,
        }
        return self.schedule


@pytest.mark.asyncio
async def test_a_failed_change_log_write_does_not_deny_a_scout_schedule():
    profiles, tasks = _Profiles(), _Tasks()
    tasks.change_fails = True
    service = _service(profiles, tasks)
    service.discovery_runs = _Runs()

    outcome = await service._apply_scout_schedule(
        "u-1", ScoutScheduleAction(cadence="daily", hour=15, minute=0)
    )

    assert outcome["kind"] == "scheduled"
    assert service.discovery_runs.schedule["hour"] == 15
