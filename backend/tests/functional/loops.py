"""A harness for testing agentic loops: the path, not just the destination.

The existing loop test asserts on the rows left behind at the end. That is
the right final check and it cannot see any of the ways a loop goes wrong on
the way there - a step repeated, a step skipped, a failed step counted as
done, four steps spent where two would do. As more agents start looping, the
path is where their bugs will live.

Three things this gives a test that a bare call does not:

  * **The trajectory.** Every step in order, the line the model was shown
    before each decision, and why the loop stopped. `run_steps` has five
    separate stopping rules and a test that cannot tell them apart cannot
    tell a healthy stop from a ceiling being hit.
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
world, and a test that reimplemented the loop would prove the
reimplementation rather than the code that runs.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.services.main_action_selector import MainActionSelector, clear_decision_cache
from backend.services.turn_steps import Step, run_steps
from backend.tools.registry import AUTOMATION_TOOLS

# Why a loop stopped. Named, because `run_steps` has five stopping rules and
# "it stopped" is not a result: a turn that ended because the router had
# nothing left to do and a turn that ended against the ceiling look identical
# from the outside and mean opposite things.
DECLINED = "the router named no further tool"
CEILING = "the step ceiling was reached"
REPEATED = "the router repeated a step"
UNAPPLIED = "the action was not one this loop carries out"


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

    outcomes: Sequence[dict[str, Any]] = field(default_factory=lambda: [{"kind": "done"}])
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
# loop runs over; a caller testing a different agent's loop passes its own.
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
    declined = False

    async def decide(lines: list[str]) -> Any:
        nonlocal declined
        shown.append(tuple(lines))
        action = await selector.select(
            user, ask, history or [], None,
            local_now=local_now, only=only, steps_taken=lines,
        )
        declined = action is None
        return action

    first = await selector.select(
        user, ask, history or [], None, local_now=local_now, only=only
    )
    if first is None:
        return Trajectory((), DECLINED, ())

    from backend.services.conversation_service import _step_line

    steps = await run_steps(
        first,
        apply=stage.apply,
        decide=decide,
        describe=_step_line,
        creates=creates,
        max_steps=max_steps,
        budget_seconds=budget_seconds,
    )
    if not steps:
        stopped = UNAPPLIED
    elif len(steps) >= max_steps:
        stopped = CEILING
    elif declined:
        stopped = DECLINED
    else:
        stopped = REPEATED
    return Trajectory(tuple(steps), stopped, tuple(shown))


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
        paths = [" -> ".join(trajectory.path) or "(none)" for trajectory in self.trajectories]
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
