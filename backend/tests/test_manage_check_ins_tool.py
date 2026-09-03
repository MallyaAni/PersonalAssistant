"""Check-ins on request, and off until asked: the tool parses into an action,
the automatic judgement is skipped for anyone who has not opted in, and the
apply step sets the preference, drops what is waiting on "off", and arms one
on "once" within the same limits as the judgement."""
from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.conversation_service import ConversationService
from backend.tools import manage_check_ins
from backend.tools.actions import ManageCheckInsAction
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


class _Tasks:
    """Enough of the task repository for arming and standing down."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.deleted: list[str] = []

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


def _service(profiles: _Profiles, tasks: _Tasks, timezone: str = "America/New_York") -> ConversationService:
    service = ConversationService.__new__(ConversationService)
    service.memory = profiles
    service.scheduled_tasks = tasks
    service.discovery_profile = object()
    service.check_in_llm = object()

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
