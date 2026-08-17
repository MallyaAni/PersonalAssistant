"""Which tool the router picks, across every tool at once.

The suites beside this one each hold a single tool to a floor over a set chosen
for it. None of them can say what a wrong turn became, and that is the part
that decides the fix: a request scattering across three unrelated tools is a
model with no right answer available, while one landing on the same wrong tool
every time is usually a sentence in a prompt. Both read as "accuracy dropped".

This is the gate, not the comparison. It fails when selection collapses. Use
`python -m backend.cli.evaluate_tool_selection` to see the matrix itself and to
weigh two candidate models against each other, because the cells matter more
than the total: a stray `search_web` costs a second, a stray `edit_image`
mutates an artifact, and a search that should have fired and did not returns a
confident wrong answer with nothing to signal it.
"""

import asyncio

import pytest

from backend.config.settings import settings
from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_routing_llm_client,
)
from backend.services.main_action_selector import MainActionSelector
from backend.services.tool_selection_cases import (
    ACCURACY_FLOOR,
    EDIT_IMAGE,
    NO_TOOL,
    SELECTION_CASES,
)

pytestmark = pytest.mark.asyncio

# One pass over the whole set. The floor catches collapse rather than a close
# call, so repetition buys accuracy this gate does not spend.
_REPS = 1


# Score every labelled turn once against the real routing model.
@pytest.fixture(scope="module")
def scored():
    from backend.cli.evaluate_tool_selection import collect, tool_of  # noqa: F401

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip("internet MCP server is not configured as auto-invocable")

    async def _run():
        selector = MainActionSelector(
            get_routing_llm_client(),
            invocation,
            settings.SEARCH_MCP_SERVER_ID,
            settings.SEARCH_MCP_TOOL_NAME,
            tool_orchestration=None,
            diagram_enabled=True,
            presentation_enabled=True,
        )
        return await collect(selector, _REPS)

    return asyncio.run(_run())


# The gate: selection as a whole must not collapse.
async def test_tool_selection_accuracy_holds(scored):
    correct = sum(1 for expected, chosen, _ in scored if expected == chosen)
    accuracy = correct / len(scored)

    assert accuracy >= ACCURACY_FLOOR, (
        f"{correct}/{len(scored)}",
        sorted(
            {(e, c) for e, c, _ in scored if e != c},
        ),
    )


# The expensive cell, called out separately because the aggregate hides it: an
# unwanted edit mutates an owned artifact and spends a real generation, so it
# is not interchangeable with an unwanted search.
async def test_nothing_is_mistaken_for_an_image_edit(scored):
    stray = [
        (expected, category)
        for expected, chosen, category in scored
        if chosen == EDIT_IMAGE and expected != EDIT_IMAGE
    ]

    assert not stray, stray


# Answering directly is the commonest correct decision and the one a router
# under pressure abandons first, reaching for whichever tool is nearest.
async def test_turns_needing_no_tool_do_not_reach_for_one(scored):
    observed = [
        (expected, chosen) for expected, chosen, _ in scored if expected == NO_TOOL
    ]
    kept = sum(1 for _, chosen in observed if chosen == NO_TOOL)

    assert observed, "the set must contain no-tool cases"
    assert kept / len(observed) >= 0.85, (kept, len(observed))


def test_every_case_is_labelled_with_a_tool_that_exists():
    from backend.services.tool_selection_cases import TOOL_NAMES

    assert SELECTION_CASES
    for case in SELECTION_CASES:
        assert case.expected in TOOL_NAMES, case
