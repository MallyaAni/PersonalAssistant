"""Score whole turns against the real loop, not just the first tool.

    python -m backend.cli.evaluate_trajectories --reps 3

The first-tool matrix measures one decision. A turn that needs two tools in
sequence and stops after one, a step that failed and was still counted as
done, or a request that legitimately writes twice being cut to a single
write by the repeat guard - none of those are a first-tool cell. They are
properties of the whole path, and this is the harness that measures them.

Each labelled trajectory is walked against the real router and the real
`run_steps` (only what a step does is scripted), then scored on:

  * completion      - the required effect sequence happened, in order
  * argument carry  - the turn's own words survived into the required steps
  * unauthorized    - a forbidden tool fired anywhere in the path
  * duplicate       - more successful effects than the case allows
  * latency/cost    - wall time, decisions, and steps per trajectory

Runs are recorded versioned under `docs/evals/runs/trajectories/` so a later
change can answer "did that get better?" with `history()` and `compare()`.
Floors are reported but not enforced until a baseline has been measured: a
floor that has never been seen to hold is not a floor.

Use it after any change to the loop, the router, or the repeat guard. The
`two-reminders` case is expected to measure incomplete today - the live
guard allows one creation per turn - and its rate moving is the proof Phase 2
and Phase 3 of the execution-boundary repair are working.
"""

import argparse
import asyncio
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
    measure_once,
)

# A floor per category, one miss below what was measured on 2026-09-04 (the
# Phase 1 baseline run, recorded under docs/evals/runs/trajectories/). A
# floor that has never been seen to hold is not a floor, so the categories
# that measured at zero are set to zero until the repair moves them:
#   single_step     3/3  -> 0.67
#   reference       3/3  -> 0.67
#   partial_failure 3/3  -> 0.67
#   mixed_tools     1/6  -> 0.0   (the router does the first tool and stops)
#   multiple_writes 0/3  -> 0.0   (the repeat guard cuts two writes to one)
CATEGORY_COMPLETION_FLOORS: dict[str, float] = {
    "single_step": 0.67,
    "reference": 0.67,
    "partial_failure": 0.67,
    "mixed_tools": 0.0,
    "multiple_writes": 0.0,
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


# Print the per-category picture: completion, argument carrying, unauthorized
# actions, duplicates, and cost, then the trajectories that failed. Returns
# whether every measured rate holds its floor.
def report(observations: list[TrajectoryObservation], reps: int) -> bool:
    by_category: dict[str, list[TrajectoryObservation]] = defaultdict(list)
    for seen in observations:
        by_category[seen.case.category].append(seen)

    print(
        f"cases {len(TRAJECTORY_CASES)}  reps {reps}  "
        f"observations {len(observations)}\n"
    )

    breached: list[str] = []
    total_completed = 0
    for category, group in sorted(by_category.items()):
        completed = sum(1 for seen in group if seen.score.completed)
        carried = [
            seen for seen in group if seen.score.carried is not None
        ]
        carried_ok = sum(1 for seen in carried if seen.score.carried)
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
        if floor is not None and not held:
            breached.append(f"{category} {rate:.2f} < {floor:.2f}")

        print(f"[{category}]")
        floor_note = (
            f"  floor {floor:.2f}  {'ok' if held else 'BREACH'}"
            if floor is not None
            else ""
        )
        print(f"  completed      {completed}/{len(group)}{floor_note}")
        if carried:
            print(f"  carried        {carried_ok}/{len(carried)}")
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

    if breached:
        print("\nfloors breached: " + "; ".join(breached))

    # Every measurement is kept, so "did that get better" has an answer
    # without running both versions again.
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
            f"{len(TRAJECTORY_CASES)} labelled trajectories; "
            f"{len(failed)} did not complete"
        ),
        extra={
            "failures": [
                {
                    "name": seen.case.name,
                    "path": list(seen.score.path),
                    "stopped": seen.trajectory.stopped,
                }
                for seen in failed
            ],
            "floors_breached": breached,
        },
    )
    return not breached


# Build the selector against the configured routing model and walk the set.
async def evaluate(reps: int) -> int:
    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        print("Search server is not auto-invocable; the matrix would be incomplete.")
        return 2
    llm = get_routing_llm_client()
    print(f"model: {llm.base_url} {llm.model}\n")
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
    passed = report(observations, reps)
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
