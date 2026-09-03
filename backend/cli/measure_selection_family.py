"""Measure the router on one family of selection cases, several passes each.

    python -m backend.cli.measure_selection_family --category check_ins --reps 3

The whole suite (evaluate_tool_selection) is the gate; this is the tool for
setting a floor when cases are added: run the family alone, read the rate per
case, and pin the floor below the measured minimum (a judgement is not
deterministic; see docs/ML_SYSTEM_DESIGN.md).
"""
import argparse
import asyncio
from collections import Counter

from backend.cli.evaluate_tool_selection import collect
from backend.config.settings import settings
from backend.core.dependencies import get_mcp_invocation_service, get_routing_llm_client
from backend.services.main_action_selector import MainActionSelector
from backend.services.tool_selection_cases import SELECTION_CASES


# The same selector the gate builds: the routing model, the search server.
def _selector() -> MainActionSelector:
    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        raise SystemExit("the internet MCP server is not configured as auto-invocable here")
    return MainActionSelector(
        get_routing_llm_client(),
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


# One pass over the family, then the rate per case and per expected tool.
async def measure(category: str, reps: int) -> int:
    cases = tuple(case for case in SELECTION_CASES if case.category == category)
    if not cases:
        print(f"no cases in category {category!r}")
        return 2
    observations = await collect(_selector(), reps, cases)
    # The collector keeps (expected, chosen, category), not the query, so the
    # rate is per expected tool within the family.
    by_expected: dict[str, Counter] = {}
    for expected, chosen, _category in observations:
        by_expected.setdefault(expected, Counter())[chosen] += 1
    worst = 1.0
    for expected, counts in by_expected.items():
        rate = counts[expected] / max(1, sum(counts.values()))
        worst = min(worst, rate)
        print(f"{rate:.2f}  expected {expected}  chosen {dict(counts)}")
    print(f"minimum {worst:.2f} over {len(cases)} cases x {reps}")
    return 0 if worst > 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", required=True)
    parser.add_argument("--reps", type=int, default=3)
    arguments = parser.parse_args()
    return asyncio.run(measure(arguments.category, max(1, arguments.reps)))


if __name__ == "__main__":
    raise SystemExit(main())
