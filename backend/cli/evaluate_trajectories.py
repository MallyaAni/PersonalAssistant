"""Score whole turns against the real loop, not just the first tool.

    python -m backend.cli.evaluate_trajectories --reps 3

The first-tool matrix measures one decision. A turn that needs two tools in
sequence and stops after one, a step that failed and was still counted as
done, or a request that legitimately writes twice being cut to a single
write by the repeat guard - none of those are a first-tool cell. They are
properties of the whole path, and this is the harness that measures them.

Each labelled trajectory is walked against the real router and the real
`run_steps` (only what a step does is scripted), then scored on:

  * completion      - the required effects happened, each with the right
                      tool, operation, arguments and a successful outcome
  * argument carry  - the turn's own words survived into the required steps
  * unauthorized    - a forbidden tool fired anywhere in the path
  * duplicate       - a creating effect beyond the case's allowance, or
                      identical to one already written
  * latency/cost    - wall time, decisions, and steps per trajectory

This is a **component evaluation**: it measures how the router sequences
decisions in a scripted world. Production narrows later steps to automation
bookkeeping and real dispatch has real side effects; both are out of scope
here and pinned separately (`test_a_later_step_cannot_reach_outside_the_
bookkeeping_tools`). Say "component evaluation" when quoting a number.

Runs are recorded versioned under `docs/evals/runs/trajectories/` with the
full per-observation evidence and the model and case-set fingerprints, so a
later change can answer "did that get better?" with `history()` and
`compare()` without running both versions again. Completion floors are set
one miss below what was measured; unauthorized actions and duplicates are
enforced acceptance criteria, not numbers to eyeball.

Use it after any change to the loop, the router, or the repeat guard. The
`two-reminders` case is expected to measure incomplete today - the live
guard allows one creation per turn - and its rate moving is the proof Phase 2
and Phase 3 of the execution-boundary repair are working.
"""

import argparse
import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass

from backend.config.settings import settings
from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_routing_llm_client,
)
from backend.core.evaluation_log import record
from backend.services.main_action_selector import MainActionSelector
from backend.services.trajectory_cases import TRAJECTORY_CASES, TrajectoryCase
from backend.services.trajectory_harness import (
    Trajectory,
    TrajectoryScore,
    _arguments,
    measure_once,
    tool_name,
)

# Completion floor per category, one miss below what was measured (recorded
# under docs/evals/runs/trajectories/). A floor that has never been seen to
# hold is not a floor.
#
# 2026-09-05, corrected scorer, before the repair: single_step 3/3,
# reference 3/3, partial_failure 3/3, mixed_tools 1/6, multiple_writes 0/3.
# 2026-09-05, after Phase 2 (effect contracts, key-based repeats, a creation
# allowance, and the step line carrying the instruction): mixed_tools 3/6
# (cancel-and-reschedule 3/3 by the accepted reschedule path;
# search-then-remind 0/3, the router choosing past-conversation search for
# "what's on this weekend near me"), multiple_writes 3/3. Floors one miss
# below those:
#   single_step     3/3  -> 0.66
#   reference       3/3  -> 0.66
#   partial_failure 3/3  -> 0.66
#   mixed_tools     3/6  -> 0.33
#   multiple_writes 3/3  -> 0.66
# Written as 0.66, not 0.67: 2/3 is 0.667, so a floor of 0.67 tolerated no
# miss at all and refused a run on one flake (opencode's run at 2fc6610 on
# 2026-09-05: reference 2/3 read as a breach). One miss below three is 0.66.
CATEGORY_COMPLETION_FLOORS: dict[str, float] = {
    "single_step": 0.66,
    "reference": 0.66,
    "partial_failure": 0.66,
    "mixed_tools": 0.33,
    "multiple_writes": 0.66,
}

# Argument-carrying floor per category, one miss below what was measured.
# 2026-09-05 after Phase 2: single_step 3/3, reference 3/3, multiple_writes
# 3/3; mixed_tools measured 0/6 before the carried gate learned about a
# case's alternative paths and is re-measured from zero. Carrying is a
# separate gate from completion so "right tools, wrong words" cannot hide
# behind a tool-count win.
CATEGORY_CARRIED_FLOORS: dict[str, float] = {
    "single_step": 0.66,
    "reference": 0.66,
    "mixed_tools": 0.0,
    "multiple_writes": 0.66,
}


@dataclass(frozen=True, slots=True)
class TrajectoryObservation:
    """One pass of one trajectory case, measured."""

    case: TrajectoryCase
    trajectory: Trajectory
    score: TrajectoryScore


# Walk every case `reps` times and measure each pass.
async def collect(
    selector: MainActionSelector, reps: int
) -> list[TrajectoryObservation]:
    observations: list[TrajectoryObservation] = []
    for case in TRAJECTORY_CASES:
        for _ in range(reps):
            trajectory, score = await measure_once(selector, case)
            observations.append(
                TrajectoryObservation(case, trajectory, score)
            )
    return observations


# A stable fingerprint of the case set, so a run can say which cases produced
# it without shipping the case texts inside every JSON.
def _case_fingerprint() -> str:
    material = "\x1f".join(
        f"{case.name}:{case.category}:{case.ask}" for case in TRAJECTORY_CASES
    )
    return hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:16]


# Every step of one trajectory, as evidence a later comparison can read:
# which tool, what outcome, and what the model actually wrote.
def _step_evidence(trajectory: Trajectory) -> list[dict[str, object]]:
    return [
        {
            "tool": tool_name(step.action),
            "kind": step.kind,
            "outcome": step.outcome,
            "arguments": _arguments(step.action)[:160],
            "line": step.line[:200],
        }
        for step in trajectory.steps
    ]


# Whether the measured set meets every acceptance criterion: completion floors
# per category, carried floors per category, zero unauthorized actions, and
# zero duplicate effects. Pure, so a test can pin it without running the
# report. Returns the list of breaches; empty means the set is accepted.
def acceptance(observations: list[TrajectoryObservation]) -> list[str]:
    by_category: dict[str, list[TrajectoryObservation]] = defaultdict(list)
    for seen in observations:
        by_category[seen.case.category].append(seen)

    breaches: list[str] = []
    for category, group in sorted(by_category.items()):
        completed = sum(1 for seen in group if seen.score.completed)
        rate = completed / len(group)
        floor = CATEGORY_COMPLETION_FLOORS.get(category)
        if floor is not None and rate < floor:
            breaches.append(f"{category} completion {rate:.2f} < {floor:.2f}")

        judged = [seen for seen in group if seen.score.carried is not None]
        carried_floor = CATEGORY_CARRIED_FLOORS.get(category)
        if carried_floor is not None and judged:
            carried_rate = (
                sum(1 for seen in judged if seen.score.carried) / len(judged)
            )
            if carried_rate < carried_floor:
                breaches.append(
                    f"{category} carried {carried_rate:.2f} < {carried_floor:.2f}"
                )

        unauthorized = [
            seen for seen in group if seen.score.unauthorized
        ]
        if unauthorized:
            names = ", ".join(
                ",".join(seen.score.unauthorized) for seen in unauthorized
            )
            breaches.append(f"{category} unauthorized x{len(unauthorized)}: {names}")
        duplicated = [
            seen for seen in group if seen.score.duplicate_effects > 0
        ]
        if duplicated:
            breaches.append(f"{category} duplicates x{len(duplicated)}")
    return breaches


# Print the per-category picture and enforce the acceptance criteria:
# completion floors, carried floors, zero unauthorized actions, and zero
# duplicates. Any breach fails the gate; the numbers alone cannot.
def report(
    observations: list[TrajectoryObservation], reps: int, model: str = ""
) -> bool:
    by_category: dict[str, list[TrajectoryObservation]] = defaultdict(list)
    for seen in observations:
        by_category[seen.case.category].append(seen)

    print(
        f"cases {len(TRAJECTORY_CASES)}  reps {reps}  "
        f"observations {len(observations)}  model {model}\n"
    )

    total_completed = 0
    for category, group in sorted(by_category.items()):
        completed = sum(1 for seen in group if seen.score.completed)
        judged = [seen for seen in group if seen.score.carried is not None]
        carried_ok = sum(1 for seen in judged if seen.score.carried)
        unauthorized = [
            seen for seen in group if seen.score.unauthorized
        ]
        duplicated = [
            seen for seen in group if seen.score.duplicate_effects > 0
        ]
        latency = sum(seen.score.latency_ms for seen in group) / len(group)
        decisions = sum(seen.score.decisions for seen in group) / len(group)
        steps = sum(seen.score.steps for seen in group) / len(group)
        total_completed += completed

        rate = completed / len(group)
        floor = CATEGORY_COMPLETION_FLOORS.get(category)
        held = floor is None or rate >= floor

        carried_rate = (
            carried_ok / len(judged) if judged else None
        )
        carried_floor = CATEGORY_CARRIED_FLOORS.get(category)
        carried_held = (
            carried_floor is None
            or carried_rate is None
            or carried_rate >= carried_floor
        )

        print(f"[{category}]")
        floor_note = (
            f"  floor {floor:.2f}  {'ok' if held else 'BREACH'}"
            if floor is not None
            else ""
        )
        print(f"  completed      {completed}/{len(group)}{floor_note}")
        if judged:
            carry_note = ""
            if carried_floor is not None:
                carry_note = (
                    f"  floor {carried_floor:.2f}  "
                    f"{'ok' if carried_held else 'BREACH'}"
                )
            print(f"  carried        {carried_ok}/{len(judged)}{carry_note}")
        if unauthorized:
            names = ", ".join(
                ",".join(seen.score.unauthorized) for seen in unauthorized
            )
            print(f"  unauthorized   {len(unauthorized)}: {names}")
        if duplicated:
            print(
                f"  duplicates     {len(duplicated)}: "
                + "; ".join(
                    f"{seen.case.name} x{seen.score.duplicate_effects}"
                    for seen in duplicated
                )
            )
        print(
            f"  cost           {steps:.2f} steps, {decisions:.2f} decisions, "
            f"{latency:.0f} ms/rep"
        )

    overall = total_completed / len(observations) if observations else 0.0
    print(f"\noverall completion {overall:.3f} [{total_completed}/{len(observations)}]")

    # The point of a trajectory report, like the matrix: which request failed,
    # and what its path actually became. A path of one tool where two were
    # required and a path of the right tools in the wrong order want different
    # work.
    failed = [
        seen for seen in observations if not seen.score.completed
    ]
    print(f"\ntrajectories that did not complete ({len(failed)}):")
    for seen in failed:
        print(
            f"  [{seen.case.name}] {seen.case.ask[:80]}\n"
            f"      path: {' -> '.join(seen.score.path) or '(none)'}"
            f"  ({seen.trajectory.stopped})"
        )
    if not failed:
        print("  (none)")

    breaches = acceptance(observations)
    if breaches:
        print("\nacceptance breached: " + "; ".join(breaches))

    # Every measurement is kept - the scores, the failures, and the evidence
    # each pass produced - so "did that get better" has an answer without
    # running both versions again.
    record(
        "trajectories",
        total_completed,
        len(observations),
        reps=reps,
        floor=None,
        scores={
            category: (
                sum(1 for seen in group if seen.score.completed),
                len(group),
            )
            for category, group in sorted(by_category.items())
        },
        notes=(
            f"{len(TRAJECTORY_CASES)} labelled trajectories (component "
            f"evaluation); {len(failed)} did not complete; "
            f"{len(breaches)} acceptance breach(es)"
        ),
        extra={
            "model": model,
            "case_fingerprint": _case_fingerprint(),
            "environment": "component evaluation: real router + run_steps, "
            "scripted apply; production dispatch out of scope",
            "floors_breached": breaches,
            "observations": [
                {
                    "name": seen.case.name,
                    "category": seen.case.category,
                    "path": list(seen.score.path),
                    "stopped": seen.trajectory.stopped,
                    "steps": seen.score.steps,
                    "decisions": seen.score.decisions,
                    "latency_ms": round(seen.score.latency_ms, 1),
                    "completed": seen.score.completed,
                    "carried": seen.score.carried,
                    "unauthorized": list(seen.score.unauthorized),
                    "duplicate_effects": seen.score.duplicate_effects,
                    "failed_steps": seen.score.failed_steps,
                    "evidence": _step_evidence(seen.trajectory),
                }
                for seen in observations
            ],
        },
    )
    return not breaches


# Build the selector against the configured routing model and walk the set.
async def evaluate(reps: int) -> int:
    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        print("Search server is not auto-invocable; the matrix would be incomplete.")
        return 2
    llm = get_routing_llm_client()
    model = f"{llm.base_url} {llm.model}"
    print(f"model: {model}\n")
    selector = MainActionSelector(
        llm,
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )
    observations = await collect(selector, reps)
    passed = report(observations, reps, model)
    print(f"\n{'PASS' if passed else 'FAIL'} against the recorded floors")
    return 0 if passed else 1


# Parse arguments and run one evaluation pass.
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reps",
        type=int,
        default=3,
        help="passes per case; 3 or more to separate a bias from noise",
    )
    arguments = parser.parse_args()
    return asyncio.run(evaluate(max(1, arguments.reps)))


if __name__ == "__main__":
    raise SystemExit(main())
