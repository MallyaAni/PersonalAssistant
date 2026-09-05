"""A case may accept more than one path to the same effects, and the step
line the router reads carries what was done.

Two findings from the first Phase 2 measurement (2026-09-05). "Cancel my 5pm
reminder and set one for 6pm to call mum" was answered by one reschedule,
which is the reminder moved - the effects asked for, by another path - and
the case scored it incomplete. And the router wrote "call mum" twice, at both
times, because the line it read back said "Scheduled tasks: once at 18:00"
and nothing about which reminder that was.
"""

from backend.services.conversation_service import _step_line
from backend.services.trajectory_cases import case_by_name
from backend.services.trajectory_harness import (
    RequiredEffect,
    Trajectory,
    score_trajectory,
)
from backend.services.turn_steps import DECLINED, Step
from backend.tools.actions import ManageTasksAction, ScheduleTaskAction


def _step(action, kind="task", outcome=None) -> Step:
    return Step(action, kind, outcome or {"kind": "done"}, _step_line(action, kind, outcome))


def test_a_reschedule_completes_the_cancel_and_set_case():
    case = case_by_name("cancel-and-reschedule")
    moved = ManageTasksAction(
        "reschedule", "the 5pm reminder", instruction="call mum", cadence="once", hour=18
    )
    score = score_trajectory(case, Trajectory((_step(moved),), DECLINED), 1.0)
    assert score.completed is True

    # The stated path still completes too.
    cancelled = ManageTasksAction("cancel", "the 5pm reminder")
    set_new = ScheduleTaskAction("call mum", "once", 18)
    both = Trajectory((_step(cancelled), _step(set_new, outcome={"kind": "scheduled"})), DECLINED)
    assert score_trajectory(case, both, 1.0).completed is True

    # And a reschedule to the wrong hour is neither.
    wrong = ManageTasksAction("reschedule", "the 5pm reminder", cadence="once", hour=19)
    assert score_trajectory(case, Trajectory((_step(wrong),), DECLINED), 1.0).completed is False


def test_an_alternative_is_not_a_second_required_sequence():
    # `required` alone must still be sufficient; alternatives only add paths.
    for case in (case_by_name("one-reminder"), case_by_name("two-reminders")):
        assert case.alternatives == ()


def test_the_step_line_names_the_reminder_and_the_time():
    line = _step_line(ScheduleTaskAction("remind me to call mum", "once", 18, 0), "task", {"kind": "scheduled"})
    assert "18:00" in line
    assert "call mum" in line

    moved = _step_line(
        ManageTasksAction("reschedule", "the stretch reminder", cadence="daily", hour=20),
        "task",
        {"kind": "rescheduled"},
    )
    assert "reschedule" in moved
    assert "stretch" in moved
    assert "20:00" in moved

    cancelled = _step_line(ManageTasksAction("cancel", "the tesla one"), "task", {"kind": "cancelled"})
    assert "tesla" in cancelled


def test_a_read_that_found_things_says_how_many():
    from backend.tools.actions import SearchAction

    line = _step_line(SearchAction("salsa nights"), "search", {"kind": "found", "count": 5})
    assert "5 results" in line
    nothing = _step_line(SearchAction("salsa nights"), "search", {"kind": "nothing"})
    assert "found nothing" in nothing


def test_required_effect_allows_a_set_of_tools():
    effect = RequiredEffect(tools={"search_web", "get_weather"})
    assert effect.allowed == frozenset({"search_web", "get_weather"})
