"""The task-outcome block renders every record kind without raising.

The sweep's "undo a scout change" journey (2026-08-26) crashed the reply
graph: an undone Scout schedule was handed to the task renderer as a task,
and a schedule has no instruction.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.agents.graph import _render_task_outcome

_SCHEDULE = {
    "cadence": "daily", "hour": 15, "minute": 0, "weekday": 0,
    "timezone": "America/New_York", "enabled": True,
    "next_run_at": datetime(2026, 8, 27, 19, 0, tzinfo=UTC),
}


def test_an_undone_scout_change_renders_as_a_sweep_not_a_task():
    text = _render_task_outcome(
        {"kind": "undone", "change": {"kind": "scout_schedule", "operation": "schedule"}, "schedule": _SCHEDULE}
    )
    assert "Scout's sweep: every day at 3:00 PM (America/New_York)" in text
    assert "Next sweep: Thursday 2026-08-27 at 3:00 PM" in text
    assert "Undone: the last change (schedule of Scout's sweep schedule)" in text


def test_an_undone_scout_change_back_to_no_schedule_says_so():
    text = _render_task_outcome(
        {"kind": "undone", "change": {"kind": "scout_schedule", "operation": "schedule"}, "schedule": None}
    )
    assert "no schedule (it had none before the change)" in text


def test_a_schedule_dict_in_the_task_slot_never_raises():
    # Defensive: a record that puts a schedule where a task goes is rendered
    # without the task line rather than raising inside the reply graph.
    text = _render_task_outcome({"kind": "undone", "change": {"kind": "scout_schedule"}, "task": _SCHEDULE})
    assert "Task:" not in text and "Undone" in text


def test_nothing_to_undo_is_stated():
    assert "Nothing to undo" in _render_task_outcome({"kind": "nothing_to_undo"})
