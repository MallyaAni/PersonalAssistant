"""Labelled trajectories for measuring how a whole loop behaves, not just
which tool the first decision picks.

The first-tool matrix scores one decision: the tool chosen for one turn. It
cannot see a turn that needs two tools in sequence and stops after one, a
step that failed and was still reported as done, or a request that
legitimately writes twice being cut to one write by the repeat guard. Those
are properties of the whole path, and they are what this set measures.

Every case is a request the person could actually make, a scripted `world`
for what each step does (so a failure can be arranged and a step that touches
no database can be measured), and the shape the path must have for the turn
to count as done. Completion is stated as `required` effects - each an
allowed tool, an optional operation, argument words it must carry, and that
its outcome must be a success - matched in order `required_times` over, with
`covers` words that must appear somewhere across the matched steps and
`forbidden` tools that must never fire. A case whose goal the world made
unreachable sets `honest_failure`, so "done" means the failure was seen and
nothing was fabricated as a success.

`only` is the tool set the loop is offered. It defaults to the automation
set because that is what the live loop runs over. The `search-then-remind`
case offers every tool (`only=None`) and is therefore a *component*
measurement of router sequencing - the production path narrows later steps
to automation bookkeeping, which `test_a_later_step_cannot_reach_outside_
the_bookkeeping_tools` pins separately. Say "component evaluation" when
quoting it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.services.trajectory_harness import (
    RequiredEffect,
    World,
)


@dataclass(frozen=True, slots=True)
class TrajectoryCase:
    """One labelled trajectory: the ask, the scripted world, and the shape the
    path must have for the turn to count as done."""

    name: str
    ask: str
    category: str
    required: tuple[RequiredEffect, ...]
    required_times: int = 1
    # Words that must appear somewhere across the matched steps, so two
    # copies of the same reminder never satisfy a request for two different
    # ones.
    covers: tuple[str, ...] = ()
    # A case whose goal the scripted world makes unreachable: done means the
    # failure was seen and nothing was fabricated as a success.
    honest_failure: bool = False
    history: tuple[tuple[str, str], ...] = ()
    # None offers what production offers: every tool on the first decision
    # and, on a later one, the tools whose contracts allow a later step. A set
    # names the tools for a component measurement of one agent's loop.
    only: frozenset[str] | None = None
    # Scripted outcomes for the loop's steps; the last one repeats, and an
    # empty script means every step succeeds.
    world: tuple[dict[str, Any], ...] = ()
    world_kind: str = "task"
    forbidden: tuple[str, ...] = ()
    # How many successful creating effects this turn may legitimately write.
    allowed_creates: int = 1
    max_steps: int = 3
    local_now: str = "Tuesday 2026-09-03 14:00"
    user: str = "trajectory_eval"
    creates: Callable[[Any], bool] | None = None


def world_for(case: TrajectoryCase) -> World:
    return World(list(case.world) or [{"kind": "done"}], kind=case.world_kind)


def _creates_schedule(action: Any) -> bool:
    from backend.tools.actions import ScheduleTaskAction

    return isinstance(action, ScheduleTaskAction)


# The set. Four shapes, weighted to the failures the first-tool matrix cannot
# see: mixed tools, a failed step, a reference resolved across the loop, and
# two legitimate writes in one turn. `search-then-remind` is a component
# measurement (see the module note on `only`).
TRAJECTORY_CASES: tuple[TrajectoryCase, ...] = (
    # The easy middle, so a category rate always has a floor of one.
    TrajectoryCase(
        name="one-reminder",
        ask="remind me at 6pm to call mum",
        category="single_step",
        required=(RequiredEffect(tools="schedule_task", carries=("mum",)),),
    ),
    # Two different automation tools, in order: cancel then set, at 18:00.
    TrajectoryCase(
        name="cancel-and-reschedule",
        ask="cancel my 5pm reminder and set one for 6pm to call mum",
        category="mixed_tools",
        required=(
            RequiredEffect(tools="manage_tasks", operation="cancel"),
            RequiredEffect(tools="schedule_task", carries=("mum", "18")),
        ),
        forbidden=("edit_image", "generate_image"),
        max_steps=3,
    ),
    # A turn that needs search then schedule. Offered every tool, because the
    # live loop narrows later steps to automation bookkeeping; whether the
    # router can still sequence across the two is a component measurement of
    # the gap (production restriction pinned in test_turn_steps_behaviour).
    TrajectoryCase(
        name="search-then-remind",
        ask="what's on this weekend near me, and remind me about the pottery "
        "class on saturday",
        category="mixed_tools",
        required=(
            RequiredEffect(tools={"search_web", "search_credits", "get_weather"}),
            RequiredEffect(tools="schedule_task", carries=("pottery",)),
        ),
        only=None,
        world=({"kind": "done"}, {"kind": "scheduled"}),
        forbidden=("edit_image", "generate_image"),
        max_steps=3,
    ),
    # The first step fails (nothing to act on). Done means the loop saw the
    # failure and did not report the cancel that never happened as done.
    TrajectoryCase(
        name="cancel-nothing-found",
        ask="cancel my 5pm reminder",
        category="partial_failure",
        required=(RequiredEffect(tools="manage_tasks", operation="cancel"),),
        honest_failure=True,
        world=({"kind": "not_found", "tasks": []},),
        max_steps=2,
    ),
    # A reference resolved across the loop: the stretch reminder was set in
    # an earlier turn, and this turn must reschedule it - not list tasks, and
    # not create a second one.
    TrajectoryCase(
        name="move-the-stretch-reminder",
        ask="move the stretch reminder to 8pm",
        category="reference",
        required=(
            RequiredEffect(
                tools="manage_tasks", operation="reschedule", carries=("stretch",)
            ),
        ),
        history=(
            (
                "set a reminder for 7pm to do the stretch routine",
                "Done - reminder set for 7pm.",
            ),
        ),
        forbidden=("schedule_task",),
        max_steps=2,
    ),
    # Two legitimate writes in one turn, and they must be two *different*
    # reminders. The live repeat guard allows one creation, so this is
    # expected to measure incomplete today; Phase 2/3 repair it, and the rate
    # moving is the proof.
    TrajectoryCase(
        name="two-reminders",
        ask="set reminders for 6pm to call mum and 8pm for the gym",
        category="multiple_writes",
        required=(RequiredEffect(tools="schedule_task"),),
        required_times=2,
        covers=("mum", "gym"),
        allowed_creates=2,
        creates=_creates_schedule,
        max_steps=3,
    ),
)


def case_by_name(name: str) -> TrajectoryCase | None:
    return next((case for case in TRAJECTORY_CASES if case.name == name), None)
