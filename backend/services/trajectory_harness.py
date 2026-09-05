"""A harness for driving agentic loops: the path, not just the destination.

The existing loop test asserts on the rows left behind at the end. That is
the right final check and it cannot see any of the ways a loop goes wrong on
the way there - a step repeated, a step skipped, a failed step counted as
done, four steps spent where two would do. As more agents start looping, the
path is where their bugs will live.

Three things this gives a caller that a bare call does not:

  * **The trajectory.** Every step in order, the line the model was shown
    before each decision, and why the loop stopped. `run_steps` has six
    separate stopping rules and returns the one that actually fired, so a
    caller never has to guess between a decline and a spent budget.
  * **Fault injection.** Make the second step fail and assert the loop
    recovers. Nothing could do this until step outcomes reached the model,
    and it is the case that matters most: a loop that cannot see a failure
    reports success.
  * **A rate, not a coin flip.** Loops compound. Three steps at ninety
    percent each is seventy-three percent end to end, and a single pass
    cannot see that. `repeat` runs a trajectory several times and returns
    how often the claim held, for gating below a measured floor.

The deciding is the real router and the looping is the real `run_steps`.
Only `apply` is stood in for, because `apply` is where a step touches the
world. That makes this a **component evaluation**: it measures how the router
sequences decisions in a simulated world, not whether the production path can
execute a particular sequence (production narrows later steps to automation
bookkeeping, and this harness can offer any set - `test_a_later_step_cannot_
reach_outside_the_bookkeeping_tools` in `test_turn_steps_behaviour.py` pins
the production restriction). Say "component evaluation" when quoting a number
from here.

`score_trajectory` turns one trajectory into the metrics the trajectory
evaluation is built on. Completion is not "the right tools fired": a required
effect matches only when the step used an allowed tool, carried the right
operation and arguments, and its outcome was a success - so a failed reminder
for the wrong task at the wrong time never counts as done, and a case that
asks for two distinct reminders is only done when two distinct ones exist.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from backend.services.main_action_selector import (
    MainActionSelector,
    clear_decision_cache,
)
from backend.services.turn_steps import (
    DECLINED,
    Step,
    run_steps,
)
from backend.tools.registry import AUTOMATION_TOOLS


@dataclass(frozen=True, slots=True)
class Trajectory:
    """What a loop actually did, in order, and why it stopped."""

    steps: tuple[Step, ...]
    stopped: str
    shown: tuple[tuple[str, ...], ...] = ()

    # The kind of action taken at each step, in order. The shape of the path.
    @property
    def path(self) -> tuple[str, ...]:
        return tuple(type(step.action).__name__ for step in self.steps)

    # The line each step contributed to what the model read next.
    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(step.line for step in self.steps)

    # The steps whose outcome says they did not do what they were asked.
    @property
    def failed(self) -> tuple[Step, ...]:
        return tuple(
            step
            for step in self.steps
            if str((step.outcome or {}).get("kind") or "")
            in {"failed", "invalid", "not_found", "none"}
        )

    def __len__(self) -> int:
        return len(self.steps)


@dataclass
class World:
    """What each step does, scripted, so a failure can be arranged.

    `outcomes` is consumed in order and the last one repeats, so a two-entry
    script covers "the first step works, everything after it fails". `kind`
    is the step kind `run_steps` groups by.
    """

    outcomes: Sequence[dict[str, Any]] = field(
        default_factory=lambda: [{"kind": "done"}]
    )
    kind: str = "task"
    seen: list[Any] = field(default_factory=list)

    # Carry out one step, recording it, and hand back the scripted outcome.
    async def apply(self, action: Any) -> tuple[str, dict[str, Any]] | None:
        index = min(len(self.seen), len(self.outcomes) - 1)
        self.seen.append(action)
        return self.kind, dict(self.outcomes[index])


# Run one loop against the real router and return the whole path.
#
# `only` defaults to the automation tools because that is the set the live
# loop runs over; a caller testing a different agent's loop passes its own,
# and `None` offers every tool so a mixed-tool trajectory can be measured as
# a component. `stopped` is the actual reason `run_steps` returned, never an
# inference made here.
async def walk(
    selector: MainActionSelector,
    *,
    ask: str,
    world: World | None = None,
    user: str = "loop_harness",
    history: list[dict[str, Any]] | None = None,
    local_now: str = "Tuesday 2026-09-03 14:00",
    max_steps: int = 3,
    only: frozenset[str] | None = AUTOMATION_TOOLS,
    budget_seconds: float = 60.0,
    creates: Callable[[Any], bool] = lambda _: False,
) -> Trajectory:
    # Each pass must be the model's own answer rather than the previous
    # pass's, or repeating a trajectory measures nothing.
    clear_decision_cache()
    stage = world or World()
    shown: list[tuple[str, ...]] = []

    async def decide(lines: list[str]) -> Any:
        shown.append(tuple(lines))
        return await selector.select(
            user, ask, history or [], None,
            local_now=local_now, only=only, steps_taken=lines,
        )

    first = await selector.select(
        user, ask, history or [], None, local_now=local_now, only=only
    )
    if first is None:
        return Trajectory((), DECLINED, ())

    from backend.services.conversation_service import _step_line

    result = await run_steps(
        first,
        apply=stage.apply,
        decide=decide,
        describe=_step_line,
        creates=creates,
        max_steps=max_steps,
        budget_seconds=budget_seconds,
    )
    return Trajectory(result.steps, result.stopped, tuple(shown))


# Name the tool one decision resolved to, including the decision to use none.
# The same mapping the first-tool matrix uses, so a trajectory's path and the
# matrix's cells call the same thing by the same name. Kept here rather than
# imported from the CLI so a services module does not depend on a reporting
# module; `test_the_tool_names_agree_with_the_matrix` keeps the two in step.
_ACTION_TOOL = {
    "SearchAction": "search_web",
    "GenerateImageAction": "generate_image",
    "EditImageAction": "edit_image",
    "ShowImageAction": "show_image",
    "CreateDiagramAction": "create_diagram",
    "CreateDocumentAction": "create_document",
    "EditDocumentAction": "edit_document",
    "DelegateAction": "delegate_to_presentation_agent",
    "DiscussImageAction": "discuss_image",
    "ToolboxAction": "mcp_tool",
    "ScheduleTaskAction": "schedule_task",
    "ManageTasksAction": "manage_tasks",
    "ManageCheckInsAction": "manage_check_ins",
    "ScoutScheduleAction": "scout_schedule",
    "SaveSkillAction": "save_skill",
    "ManageSkillsAction": "manage_skills",
    "RecallHistoryAction": "search_history",
}
_SEARCH_CREDITS_TOOL = "search_credits"
_WEATHER_TOOL = "get_weather"


def tool_name(action: object) -> str:
    # The search meter is a toolbox action by mechanism (it lives on the
    # internet MCP server) and its own tool by measurement.
    if type(action).__name__ == "ToolboxAction":
        plan = getattr(action, "plan", None)
        name = getattr(plan, "tool_name", "")
        if name == _SEARCH_CREDITS_TOOL:
            return "search_credits"
        # A weather question answered by the forecast tool is the live-data
        # decision made better, not a miss.
        if name == _WEATHER_TOOL:
            return "search_web"
        return name
    return _ACTION_TOOL.get(type(action).__name__, "none")


# Everything the model wrote for this action as one searchable string. The
# actions are frozen dataclasses of scalars, so their own fields are the
# arguments - no per-tool list here that a new tool could fall off.
def _arguments(action: object) -> str:
    if action is None:
        return ""
    if type(action).__name__ == "ToolboxAction":
        plan = getattr(action, "plan", None)
        return " ".join(str(value) for value in getattr(plan, "arguments", {}).values())
    fields = getattr(action, "__dataclass_fields__", None)
    if not fields:
        return ""
    return " ".join(str(getattr(action, name, "")) for name in fields)


# Whether a step is a successful effect: applied, and its outcome does not say
# it failed to do what it was asked. A not-found cancel is not an effect.
def _is_effect(step: Step) -> bool:
    kind = str((step.outcome or {}).get("kind") or "")
    return kind not in {"", "failed", "invalid", "not_found", "none"}


# The tools that create something new in the world, so a repeat of one is the
# double-write the duplicate measure exists for. A cancel or a reschedule is
# not a creation and cannot duplicate itself this way.
_CREATING_TOOLS = frozenset({"schedule_task", "scout_schedule"})


@dataclass(frozen=True, slots=True)
class RequiredEffect:
    """One effect the turn must successfully produce to count as done.

    `tools` is the tool name or set of names that satisfy it, `operation` a
    value the action's `operation` field must equal when the tool has one,
    `carries` words the action's arguments must contain, and `succeeds`
    whether the step's outcome must be a success. Stated this way, completion
    cannot pass on tool name alone: a failed reminder for the wrong task at
    the wrong time matches nothing.
    """

    tools: frozenset[str] | str
    operation: str | None = None
    carries: tuple[str, ...] = ()
    succeeds: bool = True

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset({self.tools}) if isinstance(self.tools, str) else self.tools


# Whether one step satisfies one required effect, tool, operation, arguments
# and outcome all together.
def _matches(effect: RequiredEffect, step: Step) -> bool:
    if tool_name(step.action) not in effect.allowed:
        return False
    if (
        effect.operation is not None
        and getattr(step.action, "operation", None) != effect.operation
    ):
        return False
    if effect.carries:
        written = _arguments(step.action).casefold()
        if not all(word.casefold() in written for word in effect.carries):
            return False
    return not (effect.succeeds and not _is_effect(step))


@dataclass(frozen=True, slots=True)
class TrajectoryScore:
    """One trajectory, measured. `completed`, `unauthorized` and
    `duplicate_effects` are the gates; the rest are recorded so a change can
    be compared, not floored by habit."""

    path: tuple[str, ...]
    steps: int
    decisions: int
    latency_ms: float
    completed: bool
    carried: bool | None
    unauthorized: tuple[str, ...]
    duplicate_effects: int
    failed_steps: int


# Whether the trajectory achieved its required effects: the sequence matched
# in order `required_times` over (each step satisfying its effect - tool,
# operation, arguments, success), and the cover words present somewhere
# across the matched steps so two copies of one reminder never satisfy a
# request for two different ones. Returns the passes and the matched steps.
def _required_passes(
    case: Any, steps: tuple[Step, ...]
) -> tuple[int, list[Step]]:
    matched_steps: list[Step] = []
    passes = 0
    pos = 0
    for step in steps:
        if pos < len(case.required) and _matches(case.required[pos], step):
            matched_steps.append(step)
            pos += 1
            if pos == len(case.required):
                passes += 1
                pos = 0
                if passes >= case.required_times:
                    break
    return passes, matched_steps


# The argument half of completion, reported separately so a failure can name
# whether it lost on tools or on words. None when a case asks nothing of
# arguments, so silence never flatters the number. Independent of success and
# operation on purpose: this says whether the turn's own words got into the
# right steps' arguments at all, and a right-words-wrong-tool turn and a
# right-tool-wrong-words turn want different work.
def _arg_carrying(case: Any, trajectory: Trajectory) -> bool | None:
    if case.honest_failure or not (
        any(effect.carries for effect in case.required) or case.covers
    ):
        return None
    carried = True
    for effect in case.required:
        if not effect.carries:
            continue
        held_anywhere = any(
            tool_name(step.action) in effect.allowed
            and all(
                word.casefold() in _arguments(step.action).casefold()
                for word in effect.carries
            )
            for step in trajectory.steps
        )
        if not held_anywhere:
            carried = False
    if carried and case.covers:
        cover_steps = [
            step
            for step in trajectory.steps
            if any(
                tool_name(step.action) in effect.allowed
                for effect in case.required
            )
        ]
        union = " ".join(
            _arguments(step.action) for step in cover_steps
        ).casefold()
        carried = all(word.casefold() in union for word in case.covers)
    return carried


# Creating effects beyond the case's allowance, or identical to an earlier
# one, are duplicates. Two different reminders requested and two copies of
# the same one written are distinguished: the copies are identical, so the
# second is flagged even though the count never exceeds the allowance.
def _duplicates(case: Any, trajectory: Trajectory) -> int:
    creates: list[str] = []
    for step in trajectory.steps:
        if tool_name(step.action) in _CREATING_TOOLS and _is_effect(step):
            creates.append(_arguments(step.action))
    duplicate_effects = 0
    for index, args in enumerate(creates):
        if index >= case.allowed_creates or args in creates[:index]:
            duplicate_effects += 1
    return duplicate_effects


# Measure one trajectory against one case. Pure: given the steps, this is
# deterministic, which is why a unit test can pin it without a model.
def score_trajectory(
    case: Any, trajectory: Trajectory, latency_ms: float
) -> TrajectoryScore:
    path = tuple(tool_name(step.action) for step in trajectory.steps)

    if case.honest_failure:
        # The world scripted the goal as unreachable, so "done" means the
        # failure was seen and nothing was fabricated as a success: at least
        # one step failed, no required effect succeeded, and nothing was
        # created. A loop that reported the not-found cancel as done fails.
        completed = (
            len(trajectory.failed) >= 1
            and not any(
                _matches(effect, step)
                for effect in case.required
                for step in trajectory.steps
            )
            and not any(
                tool_name(step.action) in _CREATING_TOOLS and _is_effect(step)
                for step in trajectory.steps
            )
        )
    else:
        passes, matched_steps = _required_passes(case, trajectory.steps)
        completed = passes >= case.required_times
        if completed and case.covers:
            union = " ".join(
                _arguments(step.action) for step in matched_steps
            ).casefold()
            completed = all(word.casefold() in union for word in case.covers)

    unauthorized = tuple(
        tool for tool in path if tool in set(case.forbidden)
    )

    return TrajectoryScore(
        path=path,
        steps=len(trajectory.steps),
        decisions=len(trajectory.shown) + 1,
        latency_ms=latency_ms,
        completed=completed,
        carried=_arg_carrying(case, trajectory),
        unauthorized=unauthorized,
        duplicate_effects=_duplicates(case, trajectory),
        failed_steps=len(trajectory.failed),
    )


# Walk a case once, timed, and return its measured score.
async def measure_once(
    selector: MainActionSelector, case: Any
) -> tuple[Trajectory, TrajectoryScore]:
    from backend.services.trajectory_cases import world_for

    started = perf_counter()
    trip = await walk(
        selector,
        ask=case.ask,
        world=world_for(case),
        user=case.user,
        history=[
            {"query": query, "response": response}
            for query, response in case.history
        ],
        local_now=case.local_now,
        max_steps=case.max_steps,
        only=case.only,
        creates=case.creates or (lambda _: False),
    )
    elapsed_ms = (perf_counter() - started) * 1000.0
    return trip, score_trajectory(case, trip, elapsed_ms)


@dataclass(frozen=True, slots=True)
class Rate:
    """How often a claim about a loop held, over several passes."""

    held: int
    of: int
    trajectories: tuple[Trajectory, ...] = ()

    @property
    def rate(self) -> float:
        return self.held / self.of if self.of else 0.0

    def __str__(self) -> str:
        paths = [
            " -> ".join(trajectory.path) or "(none)"
            for trajectory in self.trajectories
        ]
        return f"{self.held}/{self.of} " + " | ".join(paths)


# Walk the same loop several times and count how often the claim held.
#
# A single pass cannot tell a behaviour from a coin flip, and a loop's errors
# compound with its length, so this is how a loop assertion should be written:
# gate on the rate, below a floor that was measured, never on one pass.
async def repeat(
    once: Callable[[], Awaitable[Trajectory]],
    holds: Callable[[Trajectory], bool],
    reps: int = 5,
) -> Rate:
    walked: list[Trajectory] = []
    for _ in range(reps):
        walked.append(await once())
    return Rate(sum(1 for item in walked if holds(item)), reps, tuple(walked))
