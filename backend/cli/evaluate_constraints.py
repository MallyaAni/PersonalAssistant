"""Measure the paired-profile property of the result ranker and record it.

    python -m backend.cli.evaluate_constraints --reps 3

Two profiles, the same question, different appropriate answers; and the same
two profiles on a factual question, the same answer. That is D7's acceptance
in the platform plan (docs/AGENT_PLATFORM_PLAN.md, Phase 4), and until now it
lived only in a functional test that passes or fails. This runs the same
cases `reps` times against the real ranking model, prints the rate per
category, and records the run under `docs/evals/runs/constraint-ranking/` so
the next change to `prompts/search/rank.md` can be compared against it.

Categories, each a rate over `reps` passes:

- allergy_violation: with "allergic to shellfish", the oyster bar and only
  the oyster bar is named under violates.
- unconstrained_clean: with no constraint, nothing is named.
- vegetarian_filters: with a vegetarian constraint, the oyster bar and the
  ramen are named and the vegetarian cafe is not.
- factual_same_top: on a factual question, the vegetarian and the
  unconstrained profile agree on the top result and name no violation.

The floor is one miss below what was measured, as every floor here is, and
is written into the record once a measurement exists (`--floor`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

from backend.core.dependencies import get_routing_llm_client
from backend.core.evaluation_log import record
from backend.core.result_ranking import judge_results

NAME = "constraint-ranking"

DINNER = [
    {
        "title": "Island Creek Oyster Bar - Kenmore Square",
        "url": "https://islandcreekoysterbar.example/",
        "content": "Raw bar with a dozen oyster varieties, lobster rolls, clam chowder and a whole fried fish. Open till 11.",
    },
    {
        "title": "Yume Wo Katare - Davis Square",
        "url": "https://yumewokatare.example/",
        "content": "Jiro-style pork ramen, one bowl, expect a line. Cash only. Somerville, MA.",
    },
    {
        "title": "Life Alive Organic Cafe - Central Square",
        "url": "https://lifealive.example/",
        "content": "Vegetarian and vegan bowls, wraps and smoothies. Cambridge, MA.",
    },
    {
        "title": "Sarma - Somerville",
        "url": "https://sarma.example/",
        "content": "Eastern Mediterranean small plates: lamb, halloumi, fried chicken, vegetable mezze. Somerville, MA.",
    },
]
DINNER_QUESTION = "where should I have dinner near Somerville tonight?"
FACT = [
    {"title": "Somerville, Massachusetts - Wikipedia", "url": "https://en.wikipedia.example/Somerville", "content": "Somerville was first settled in 1630 as part of Charlestown and incorporated as a town in 1842."},
    {"title": "History of Somerville | City of Somerville", "url": "https://somervillema.example/history", "content": "Somerville separated from Charlestown and was incorporated in 1842; it became a city in 1872."},
    {"title": "Best brunch in Somerville 2026", "url": "https://eater.example/somerville-brunch", "content": "Our picks for weekend brunch across Somerville."},
]
FACT_QUESTION = "when was Somerville incorporated as a town?"
NOW = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)
VEGETARIAN = ("vegetarian - eats no meat or fish",)
ALLERGY = ("allergic to shellfish",)


# One ranking with the given constraints.
async def _judge(llm: Any, constraints: tuple[str, ...], results: list[dict[str, Any]], question: str):
    return await judge_results(llm, question, "Somerville, MA", [dict(r) for r in results], now=NOW, constraints=constraints)


# The top result's index, or None when the order could not be read.
def _top(ranking) -> int | None:
    if ranking.scores is None:
        return None
    return max(range(len(ranking.scores)), key=lambda i: ranking.scores[i])


# One pass over the four categories: which held.
async def one_pass(llm: Any) -> dict[str, bool]:
    allergy = await _judge(llm, ALLERGY, DINNER, DINNER_QUESTION)
    nobody = await _judge(llm, (), DINNER, DINNER_QUESTION)
    vegetarian = await _judge(llm, VEGETARIAN, DINNER, DINNER_QUESTION)
    fact_vegetarian = await _judge(llm, VEGETARIAN, FACT, FACT_QUESTION)
    fact_nobody = await _judge(llm, (), FACT, FACT_QUESTION)
    return {
        "allergy_violation": allergy.violates == (1,),
        "unconstrained_clean": nobody.violates == (),
        "vegetarian_filters": 1 in vegetarian.violates and 2 in vegetarian.violates and 3 not in vegetarian.violates,
        "factual_same_top": (
            fact_vegetarian.violates == ()
            and fact_nobody.violates == ()
            and _top(fact_vegetarian) is not None
            and _top(fact_vegetarian) == _top(fact_nobody)
        ),
    }


async def run(reps: int, floor: float | None) -> int:
    llm = get_routing_llm_client()
    tally: dict[str, int] = {}
    for _ in range(max(1, reps)):
        held = await one_pass(llm)
        for category, ok in held.items():
            tally[category] = tally.get(category, 0) + (1 if ok else 0)
    right = sum(tally.values())
    total = len(tally) * reps
    print(f"{NAME}: {right}/{total} over {reps} pass(es)")
    breaches = []
    for category, hits in sorted(tally.items()):
        rate = hits / reps
        note = ""
        if floor is not None:
            note = f"  floor {floor:.2f}  {'ok' if rate >= floor else 'BREACH'}"
            if rate < floor:
                breaches.append(category)
        print(f"  {category:22} {hits}/{reps}{note}")
    path = record(
        NAME, right, total, reps=reps, floor=floor,
        scores={category: (hits, reps) for category, hits in tally.items()},
        notes="paired profiles over the planted dinner and history results",
    )
    print(f"recorded: {path}")
    return 1 if breaches else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reps", type=int, default=3)
    # One miss below the measured rate: 12/12 over three passes on 2026-09-05
    # (docs/evals/runs/constraint-ranking/), so 2/3 holds and 1/3 breaches.
    parser.add_argument("--floor", type=float, default=0.66, help="per-category floor; a breach exits 1")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.reps, args.floor))


if __name__ == "__main__":
    sys.exit(main())
