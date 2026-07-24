import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from backend.config.settings import settings
from backend.core.dependencies import get_classifier_llm
from backend.search.cascade import CascadingSearchRouter
from backend.search.classifier import LMStudioFreshnessClassifier
from backend.search.routing import SearchRoutingPolicy
from backend.services.search_routing_evaluator import SearchRoutingEvaluator


# Define command-line options for the search-routing benchmark.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate whether web-search routing sends the right turns out.",
    )
    parser.add_argument(
        "--patterns-only",
        action="store_true",
        help="Skip the classifier so the run is deterministic and needs no model.",
    )
    # Left unset so the floor can follow the mode: patterns alone cannot reach
    # the cascade's recall, and holding them to it would fail every run.
    parser.add_argument("--min-recall", type=float, default=None)
    parser.add_argument("--min-specificity", type=float, default=None)
    return parser


# Thresholds each mode is expected to hold. Recall is weighted above
# specificity on purpose: a missed search returns a confident stale answer,
# while an unnecessary one costs about a second.
_FLOORS = {
    # Deterministic and offline. Patterns catch volatile phrasing, not volatile
    # meaning, so recall is expected to be the weaker half here.
    "patterns": {"recall": 0.75, "specificity": 0.95},
    # The configuration that actually runs, with the classifier judging what the
    # patterns did not match.
    "cascade": {"recall": 0.90, "specificity": 0.80},
}


# Assemble the router under test and score it against the labelled set.
async def _run(patterns_only: bool) -> dict[str, Any]:
    classifier = (
        None
        if patterns_only
        else LMStudioFreshnessClassifier(
            get_classifier_llm(),
            max_tokens=settings.SEARCH_CLASSIFIER_MAX_TOKENS,
        )
    )
    router = CascadingSearchRouter(
        patterns=SearchRoutingPolicy(current_year=datetime.now(UTC).year),
        classifier=classifier,
    )
    report = await SearchRoutingEvaluator(router).evaluate()
    return {"mode": "patterns" if patterns_only else "cascade", **report.to_dict()}


# Report routing quality and fail when it drops below the required thresholds.
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(_run(args.patterns_only))
    print(json.dumps(result, indent=2))

    floors = _FLOORS[result["mode"]]
    min_recall = args.min_recall if args.min_recall is not None else floors["recall"]
    min_specificity = (
        args.min_specificity
        if args.min_specificity is not None
        else floors["specificity"]
    )

    failures = []
    if result["recall"] < min_recall:
        failures.append(f"recall {result['recall']:.3f} < {min_recall}")
    if result["specificity"] < min_specificity:
        failures.append(f"specificity {result['specificity']:.3f} < {min_specificity}")
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
