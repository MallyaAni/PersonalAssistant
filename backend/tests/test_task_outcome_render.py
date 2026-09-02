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


def test_a_listed_task_says_when_it_next_fires():
    # A cadence alone does not say whether tonight's has already gone. On
    # 2026-08-29 a group was told an ice-cream run that had fired the previous
    # evening was happening "tonight"; the row knew better than the listing.
    text = _render_task_outcome(
        {
            "kind": "listed",
            "tasks": [
                {
                    "instruction": "grab ice cream",
                    "cadence": "daily",
                    "hour": 21,
                    "minute": 0,
                    "enabled": True,
                    "timezone": "America/New_York",
                    "next_run_at": datetime(2026, 8, 30, 1, 0, tzinfo=UTC),
                }
            ],
        }
    )
    assert '"grab ice cream" - every day at 9:00 PM' in text
    assert "next Saturday 2026-08-29 at 9:00 PM" in text


def test_a_listed_task_with_no_next_run_is_listed_without_one():
    text = _render_task_outcome(
        {
            "kind": "listed",
            "tasks": [
                {"instruction": "stretch", "cadence": "weekdays", "hour": 9, "minute": 0, "enabled": False}
            ],
        }
    )
    assert '"stretch" - every weekday at 9:00 AM (paused)' in text
    assert "next " not in text


def test_several_cancelled_tasks_are_all_named():
    # A set cancelled at once ("delete the paused ones") records every task it
    # touched; the reply needs each name, not a count.
    text = _render_task_outcome(
        {
            "kind": "cancelled",
            "tasks": [
                {
                    "instruction": "call the bank",
                    "cadence": "once",
                    "hour": 9,
                    "minute": 0,
                    "enabled": False,
                    "timezone": "America/New_York",
                    "on_date": "2026-09-03",
                },
                {
                    "instruction": "water the plants",
                    "cadence": "daily",
                    "hour": 8,
                    "minute": 0,
                    "enabled": False,
                    "timezone": "America/New_York",
                },
            ],
        }
    )
    assert '"call the bank"' in text
    assert '"water the plants"' in text
