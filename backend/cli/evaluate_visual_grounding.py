"""Score the visual-search decision against its labelled set.

The functional test holds this decision to a floor that catches collapse. It
cannot referee a close call: two prompts nine points apart are inside the noise
of a twenty-sample run, so a gate tight enough to separate them fails honest
runs about as often as dishonest ones. This is where that comparison belongs,
at a repetition count chosen for the question being asked.

    python -m backend.cli.evaluate_visual_grounding --reps 6

Scores the decision only. `VisualSearchGrounding.decide` is deliberately
separable from `ground`, so a full pass costs one small model call per case and
no live search quota at all -- which is what makes running this before and after
a prompt change practical rather than aspirational.
"""

import argparse
import asyncio
from collections import defaultdict

from backend.config.settings import settings
from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_routing_llm_client,
)
from backend.services.visual_search_grounding import VisualSearchGrounding
from backend.vision.grounding_cases import (
    GROUNDING_CASES,
    RECALL_FLOOR,
    SPECIFICITY_FLOOR,
)


# Score every labelled case and report recall, specificity, and the weak cases.
async def evaluate(reps: int) -> int:
    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        print("Search server is not auto-invocable; cannot score the decision.")
        return 2
    grounding = VisualSearchGrounding(
        get_routing_llm_client(),
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        decision_max_tokens=settings.VISION_SEARCH_DECISION_MAX_TOKENS,
    )
    # Resolved once and reused: every case is the same contract, and a session
    # per case would dominate the runtime of the whole pass.
    tool = await grounding._tool_definition()
    if tool is None:
        print("Live search contract could not be resolved.")
        return 2

    print(f"model: {grounding.llm.base_url} {grounding.llm.model}")
    print(f"cases: {len(GROUNDING_CASES)}  reps: {reps}\n")

    positives = negatives = hits = correct_negatives = 0
    by_category: dict[str, list[int]] = defaultdict(list)
    weak: list[tuple[int, str, str]] = []
    for case in GROUNDING_CASES:
        correct = 0
        for _ in range(reps):
            searched = (
                await grounding.decide(case.question, case.observation, tool)
            ) is not None
            correct += int(searched == case.needs_search)
            if case.needs_search:
                positives += 1
                hits += int(searched)
            else:
                negatives += 1
                correct_negatives += int(not searched)
        by_category[case.category].append(correct)
        if correct < reps:
            weak.append((correct, case.category, case.question))

    recall = hits / positives if positives else 0.0
    specificity = correct_negatives / negatives if negatives else 0.0
    print(f"recall      {recall:.4f}  [{hits}/{positives}]  floor {RECALL_FLOOR}")
    print(
        f"specificity {specificity:.4f}  "
        f"[{correct_negatives}/{negatives}]  floor {SPECIFICITY_FLOOR}"
    )

    print("\nby category:")
    for category, results in sorted(by_category.items()):
        print(f"  {category:20s} {sum(results)}/{len(results) * reps}")

    if weak:
        print("\nweakest cases:")
        for correct, category, question in sorted(weak):
            print(f"  {correct}/{reps}  [{category}] {question}")

    passed = recall >= RECALL_FLOOR and specificity >= SPECIFICITY_FLOOR
    print(f"\n{'PASS' if passed else 'FAIL'} against the recorded floors")
    return 0 if passed else 1


# Parse arguments and run one evaluation pass.
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reps",
        type=int,
        default=6,
        help="passes per case; 6 or more to compare two prompts meaningfully",
    )
    arguments = parser.parse_args()
    return asyncio.run(evaluate(max(1, arguments.reps)))


if __name__ == "__main__":
    raise SystemExit(main())
