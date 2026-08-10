"""Score the discovery pipeline against digests it actually produced.

    python -m backend.cli.evaluate_discovery_ranking
    python -m backend.cli.evaluate_discovery_ranking --with-model

Without `--with-model` this is deterministic, needs no runtime, and scores only
the filtering half — which is what the test suite runs. With it, the local model
and the cross-encoder also score attribution, which needs both to be up.
"""

import argparse
import asyncio
import json
from collections.abc import Sequence

from backend.discovery.evaluation import (
    load_cases,
    score_attribution,
    score_filtering,
    score_geography,
)
from backend.discovery.geography import contradicts_locality
from backend.discovery.listing_filter import looks_like_a_directory

# What the current pipeline is expected to hold, so a regression fails rather
# than being noticed later by a person reading a digest.
#
# Retention is the harder floor on purpose. Admitting a listing wastes a slot;
# rejecting a real happening removes something the user would have wanted and
# leaves no trace that it ever existed.
FLOORS = {
    "listing_recall": 0.45,
    "happening_retention": 1.0,
    "attribution_accuracy": 0.60,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score discovery filtering and attribution against labelled "
        "items from real digests.",
    )
    parser.add_argument(
        "--with-model",
        action="store_true",
        help="Also score interest attribution, which needs the local model and "
        "the cross-encoder.",
    )
    parser.add_argument("--min-listing-recall", type=float, default=None)
    parser.add_argument("--min-attribution", type=float, default=None)
    return parser


# Name the interest the pipeline would give each labelled happening, using the
# same two stages a sweep uses: the aimed profile as the query, the
# cross-encoder as the scorer.
async def _attribute(cases: tuple) -> dict[str, str | None]:
    from backend.core.dependencies import get_cross_encoder, get_llm_client
    from backend.discovery.aiming import AimPlanner
    from backend.discovery.personal_context import PersonalContext
    from backend.discovery.precision import MIN_ATTRIBUTION_MARGIN

    planner = AimPlanner(get_llm_client())
    encoder = get_cross_encoder()
    named: dict[str, str | None] = {}
    # One plan per distinct interest set, because that is once per user rather
    # than once per find.
    plans: dict[tuple[str, ...], dict[str, str]] = {}
    for case in cases:
        if case.is_listing:
            continue
        if case.interests not in plans:
            aim = await planner.plan(case.interests, PersonalContext(), case.locality)
            plans[case.interests] = aim.vector_texts()
        vectors = plans[case.interests]
        document = f"{case.title} — {case.locality} — {case.summary}"
        pairs = [(vectors.get(label, label), document) for label in case.interests]
        scores = sorted(
            zip(
                case.interests,
                await asyncio.to_thread(encoder.score, pairs),
                strict=True,
            ),
            key=lambda item: -item[1],
        )
        best, runner_up = scores[0], scores[1] if len(scores) > 1 else ("", 0.0)
        named[case.title] = (
            best[0] if best[1] - runner_up[1] >= MIN_ATTRIBUTION_MARGIN else None
        )
    return named


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = load_cases()

    filtering = score_filtering(cases, looks_like_a_directory)
    geography = score_geography(cases, contradicts_locality)
    result: dict[str, object] = {
        "cases": len(cases),
        "filtering": filtering.as_dict(),
        # `listing_recall` here reads as "elsewhere caught" and
        # `happening_retention` as "local kept"; the shape is shared.
        "geography": geography.as_dict(),
    }

    failures: list[str] = []
    floor = args.min_listing_recall
    if floor is None:
        floor = FLOORS["listing_recall"]
    if filtering.listing_recall < floor:
        failures.append(f"listing_recall {filtering.listing_recall:.2f} < {floor:.2f}")
    if geography.happening_retention < 1.0:
        failures.append(
            "geographic rejection removed a local find: "
            + ", ".join(geography.wrongly_rejected)
        )
    if filtering.happening_retention < FLOORS["happening_retention"]:
        failures.append(
            f"happening_retention {filtering.happening_retention:.2f} < "
            f"{FLOORS['happening_retention']:.2f}: "
            + ", ".join(filtering.wrongly_rejected)
        )

    if args.with_model:
        attribution = score_attribution(cases, asyncio.run(_attribute(cases)))
        result["attribution"] = attribution.as_dict()
        floor = args.min_attribution
        if floor is None:
            floor = FLOORS["attribution_accuracy"]
        if attribution.accuracy < floor:
            failures.append(f"attribution {attribution.accuracy:.2f} < {floor:.2f}")

    print(json.dumps(result, indent=2))
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
