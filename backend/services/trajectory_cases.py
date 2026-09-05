"""Labelled trajectories for measuring how a whole loop behaves, not just
which tool the first decision picks.

The first-tool matrix scores one decision: the tool chosen for one turn. It
cannot see a turn that needs two tools in sequence and stops after one, a
step that failed and was still reported as done, or a request that
legitimately writes twice being cut to one write by the repeat guard. Those
are properties of the whole path, and they are what this set measures.

Every case is a request the person could actually make, a scripted `world`
for what each step does (so a failure can be arranged and a step that touches
no database can be measured), and the shape the path must have: `required` is
a list of predicates matched against the steps in order, `required_times` how
many full passes through that sequence count as done, `carries` what the
arguments of the required steps must keep of the turn's own words, and
`forbidden` tools that must never fire. `allowed_effects` is how many
successful effects of `effect_kind` are legitimate; more than that is a
duplicate, fewer is an incomplete write.

`only` is the tool set the loop is offered. It defaults to the automation
set because that is what the live loop runs over; a case with `only=None`
offers every tool, which is how the mixed-tool sequencing gap - the loop
today narrows later steps to automation bookkeeping - is measured rather than
assumed. A rate below the floor here is the measurement Phase 2 and Phase 3
repair.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.services.trajectory_harness import Step, World, tool_name
from backend.tools.registry import AUTOMATION_TOOLS


# One step's tool, by the name the matrix uses.
def _tool(step: Step) -> str:
    return tool_name(step.action)


def is_search(step: Step) -> bool:
    return _tool(step) in {"search_web", "search_credits", "get_weather"}


def is_manage(step: Step) -> bool:
    return _tool(step) == "manage_tasks"


def is_schedule(step: Step) -> bool:
    return _tool(step) == "schedule_task"


@dataclass(frozen=True, slots=True)
class TrajectoryCase:
    """One labelled trajectory: the ask, the scripted world, and the shape the
    path must have for the turn to count as done."""

    name: str
    ask: str
    category: str
    required: tuple[Callable[[Step], bool], ...]
    history: tuple[tuple[str, str], ...] = ()
    # None offers every tool; the automation set is what the live loop runs.
    only: frozenset[str] | None = AUTOMATION_TOOLS
    # Scripted outcomes for the loop's steps; the last one repeats, and an
    # empty script means every step succeeds.
    world: tuple[dict[str, Any], ...] = ()
    world_kind: str = "task"
    required_times: int = 1
    carries: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    allowed_effects: int = 1
    max_steps: int = 3
    local_now: str = "Tuesday 2026-09-03 14:00"
    user: str = "trajectory_eval"
    creates: Callable[[Any], bool] | None = None


def world_for(case: TrajectoryCase) -> World:
    return World(list(case.world) or [{"kind": "done"}], kind=case.world_kind)


def _creates_schedule(action: Any) -> bool:
    from backend.tools.actions import ScheduleTaskAction

    return isinstance(action, ScheduleTaskAction)


def _no_create(_: Any) -> bool:
    return False


# The set. Four shapes, weighted to the failures the first-tool matrix cannot
# see: mixed tools, a failed step, a reference resolved across the loop, and
# two legitimate writes in one turn.
TRAJECTORY_CASES: tuple[TrajectoryCase, ...] = (
    # The easy middle, so a category rate always has a floor of one.
    TrajectoryCase(
        name="one-reminder",
        ask="remind me at 6pm to call mum",
        category="single_step",
        required=(is_schedule,),
        carries=("mum",),
    ),
    # Two different automation tools, in order: cancel then set.
    TrajectoryCase(
        name="cancel-and-reschedule",
        ask="cancel my 5pm reminder and set one for 6pm to call mum",
        category="mixed_tools",
        required=(is_manage, is_schedule),
        carries=("mum",),
        forbidden=("edit_image", "generate_image"),
        max_steps=3,
    ),
    # A turn that needs search then schedule. Offered every tool, because the
    # live loop narrows later steps to automation bookkeeping; whether the
    # router can still sequence across the two is the gap this measures.
    TrajectoryCase(
        name="search-then-remind",
        ask="what's on this weekend near me, and remind me about the pottery "
        "class on saturday",
        category="mixed_tools",
        required=(is_search, is_schedule),
        only=None,
        world=({"kind": "done"}, {"kind": "scheduled"}),
        carries=("pottery",),
        forbidden=("edit_image", "generate_image"),
        max_steps=3,
    ),
    # The first step fails (nothing to act on) and the loop must see it rather
    # than reporting a cancel that never happened.
    TrajectoryCase(
        name="cancel-nothing-found",
        ask="cancel my 5pm reminder",
        category="partial_failure",
        required=(is_manage,),
        world=({"kind": "not_found", "tasks": []},),
        max_steps=2,
    ),
    # A reference resolved across the loop: the stretch reminder was set in an
    # earlier turn, and this turn must act on it, not create a second one.
    TrajectoryCase(
        name="move-the-stretch-reminder",
        ask="move the stretch reminder to 8pm",
        category="reference",
        history=(
            (
                "set a reminder for 7pm to do the stretch routine",
                "Done - reminder set for 7pm.",
            ),
        ),
        required=(is_manage,),
        carries=("stretch",),
        forbidden=("schedule_task",),
        max_steps=2,
    ),
    # Two legitimate writes in one turn. The live repeat guard allows one
    # creation, so this is expected to measure incomplete today; Phase 2/3
    # repair it, and the rate moving is the proof.
    TrajectoryCase(
        name="two-reminders",
        ask="set reminders for 6pm to call mum and 8pm for the gym",
        category="multiple_writes",
        required=(is_schedule,),
        required_times=2,
        allowed_effects=2,
        creates=_creates_schedule,
        max_steps=3,
    ),
)


def case_by_name(name: str) -> TrajectoryCase | None:
    return next((case for case in TRAJECTORY_CASES if case.name == name), None)
