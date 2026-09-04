"""A step that failed is not a step that is done.

Inside a turn the router is asked again after each step, and it is shown
"Already done this turn" plus an instruction never to repeat anything listed.
The line used to describe what the step was *for* while the outcome beside it
- which already tells a cancelled reminder from one that was never found -
went only to the trace. So a step that failed was listed as done, under an
instruction not to try again, and the turn told the person it had happened.
"""
from backend.services.conversation_service import _step_line
from backend.tools.actions import ManageTasksAction, ScheduleTaskAction


def _schedule() -> ScheduleTaskAction:
    return ScheduleTaskAction(
        instruction="text Jen the address", cadence="once", hour=17, minute=0
    )


def test_a_step_that_worked_reads_as_it_always_did():
    line = _step_line(_schedule(), "task", {"kind": "scheduled"})
    assert "[" not in line.split(": ", 1)[-1] or "did not" not in line
    assert line == _step_line(_schedule(), "task", None)


def test_each_way_a_step_can_fail_says_which():
    said = {
        kind: _step_line(ManageTasksAction(operation="cancel", which="the 5pm one"), "task", {"kind": kind})
        for kind in ("failed", "invalid", "not_found", "none")
    }
    assert "did not succeed" in said["failed"]
    assert "refused" in said["invalid"]
    assert "found nothing to act on" in said["not_found"]
    assert "nothing to do" in said["none"]
    # Four distinct outcomes, four distinct lines: "the reminder was not
    # found" and "the cancel failed" call for different next steps.
    assert len(set(said.values())) == 4


def test_the_step_is_still_described_so_the_model_knows_what_failed():
    # What the step was is kept and the outcome is appended, never replacing
    # it: "[did not succeed]" alone would say something went wrong without
    # saying what, which is no better than saying nothing.
    line = _step_line(_schedule(), "task", {"kind": "failed"})
    assert line.startswith("Scheduled tasks: once at 17:00"), line
    assert line.endswith("[did not succeed]")


def test_an_unknown_outcome_kind_does_not_invent_a_failure():
    assert "[" not in _step_line(_schedule(), "task", {"kind": "something_new"})
    assert "[" not in _step_line(_schedule(), "task", {})
