"""Which sentences of the router prompt carry weight, and which fight each other.

Every rule in prompts/routing/select_action.md is pinned alone by a case or a
functional test; nothing measured them together. This drops one sentence at
a time from the sent part of the prompt and re-scores the labelled cases, so
a sentence whose removal costs nothing is dead weight and one whose removal
*improves* a category is fighting another rule.

    docker compose run --rm --no-deps -v $PWD/backend:/app/backend:ro -v $PWD/prompts:/app/prompts:ro \\
        functional-tests python -m backend.cli.ablate_prompt_rules --reps 1 --categories agent_config,writing_followup

One rep of every case per sentence: with ~40 sentences and ~90 cases that is
~3,600 routing calls, an hour on the Spark. Narrow with --categories or
--sentences. Written 2026-08-27; measure, never read.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import defaultdict

from backend.cli import evaluate_tool_selection as evaluation
from backend.core.prompts import load
from backend.services import main_action_selector as selector_module
from backend.services.tool_selection_cases import SELECTION_CASES

_PROMPT = "routing/select_action"


# The sent prompt as sentences, keeping paragraph boundaries so a removal
# never joins two paragraphs.
def sentences(text: str) -> list[str]:
    parts: list[str] = []
    for paragraph in text.split("\n\n"):
        parts.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", paragraph) if s.strip())
    return parts


def without(text: str, sentence: str) -> str:
    return text.replace(sentence, "", 1)


async def score(selector, reps: int, categories: set[str]) -> dict[str, tuple[int, int]]:
    # Only the chosen categories are routed at all: scoring everything and
    # filtering afterwards made a two-category smoke test take ten minutes.
    cases = tuple(c for c in SELECTION_CASES if not categories or c.category in categories)
    observations = await evaluation.collect(selector, reps, cases)
    by_category: dict[str, list[bool]] = defaultdict(list)
    for expected, chosen, category in observations:
        by_category[category].append(expected == chosen)
    return {cat: (sum(hits), len(hits)) for cat, hits in by_category.items()}


async def main_async(args: argparse.Namespace) -> int:
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service, get_routing_llm_client
    from backend.services.main_action_selector import MainActionSelector

    categories = set(c for c in args.categories.split(",") if c) if args.categories else set()
    baseline_prompt = load(_PROMPT)
    all_sentences = sentences(baseline_prompt)
    chosen = all_sentences[: args.sentences] if args.sentences else all_sentences
    scored_cases = sum(1 for c in SELECTION_CASES if not categories or c.category in categories)
    print(f"{len(chosen)} sentences to ablate; cases scored: {scored_cases}; categories: {sorted(categories) or 'all'}", flush=True)

    def build() -> MainActionSelector:
        return MainActionSelector(
            get_routing_llm_client(), get_mcp_invocation_service(),
            settings.SEARCH_MCP_SERVER_ID, settings.SEARCH_MCP_TOOL_NAME,
            tool_orchestration=None, diagram_enabled=True, presentation_enabled=True,
        )

    selector_module._SYSTEM = baseline_prompt
    base = await score(build(), args.reps, categories)
    total_base = sum(h for h, _ in base.values()), sum(n for _, n in base.values())
    print(f"baseline: {total_base[0]}/{total_base[1]}  " + "  ".join(f"{c}={h}/{n}" for c, (h, n) in sorted(base.items())), flush=True)

    findings: list[tuple[int, str, dict[str, tuple[int, int]]]] = []
    for index, sentence in enumerate(chosen, start=1):
        selector_module._SYSTEM = without(baseline_prompt, sentence)
        result = await score(build(), args.reps, categories)
        total = sum(h for h, _ in result.values())
        delta = total - total_base[0]
        moved = {c: (result[c][0] - base.get(c, (0, 0))[0]) for c in result if result[c][0] != base.get(c, (0, 0))[0]}
        print(f"[{index:02d}] {delta:+d}  {sentence[:90]!r}  " + (" ".join(f"{c}{d:+d}" for c, d in sorted(moved.items())) or "no change"), flush=True)
        findings.append((delta, sentence, result))
    selector_module._SYSTEM = baseline_prompt

    print("\nsentences whose removal helps (fighting another rule):", flush=True)
    for delta, sentence, _ in sorted(findings, reverse=True):
        if delta > 0:
            print(f"  {delta:+d}  {sentence[:120]!r}")
    print("sentences whose removal costs nothing (dead weight at this sample):", flush=True)
    for delta, sentence, _ in findings:
        if delta == 0:
            print(f"   0  {sentence[:120]!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--categories", default="", help="comma-separated case categories to score; default all")
    parser.add_argument("--sentences", type=int, default=0, help="ablate only the first N sentences")
    args = parser.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
