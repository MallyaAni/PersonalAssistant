"""Continuing a draft is the reply, unless a file was asked for.

The failure this pins, three times over. Asked to change text the assistant
had just written - "make it more casual and ask them to reply by Thursday at
noon" after a drafted email - the router took a tool instead of rewriting:
edit_image on 2026-08-28, and after that was withheld, create_document and
edit_document on the post-deploy sweep of 2026-09-06. Each time the person
would have got a file, or a picture, in place of the two sentences they asked
for.

Widening the withhold list to the document tools would have closed it and
broken the neighbouring turn: "put that in a PDF" is a draft continuation too,
and that one really does want a file. So the router is told what a draft turn
implies and is measured on both halves here - the rewrite that must take no
tool, and the file request that must still get one. A structural test cannot
tell these apart; only the real router can.
"""

from __future__ import annotations

import pytest

from backend.tools import CreateDocumentAction

pytestmark = pytest.mark.asyncio


@pytest.fixture
def selector(llm):
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service
    from backend.services.main_action_selector import MainActionSelector

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip("internet MCP server is not configured as auto-invocable")
    return MainActionSelector(
        llm, invocation, settings.SEARCH_MCP_SERVER_ID, settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None, diagram_enabled=True, presentation_enabled=True,
    )


_EMAIL = [
    {
        "query": "draft a short email to my retail team asking for shift coverage this Saturday",
        "response": (
            "Subject: Shift coverage this Saturday\n\n"
            "Hi team - I need cover for Saturday, 8am to 7pm. If you can take a "
            "shift, let me know which hours work. Thanks, Ani"
        ),
    }
]
_PLAN = [
    {
        "query": "plan me a relaxed Saturday in Old Town Alexandria with rough times",
        "response": (
            "10:30 late breakfast at Table Talk. 12:00 walk the waterfront to "
            "Founders Park. 14:00 browse Old Town Books. 18:30 dinner at Hank's."
        ),
    }
]


@pytest.mark.parametrize(
    "said",
    [
        "make it more casual and ask them to reply by Thursday at noon",
        "More casual",
        "can you shorten it and drop the last line",
    ],
)
async def test_changing_the_wording_of_a_draft_takes_no_tool(selector, said) -> None:
    action = await selector.select("functional_test_user", said, _EMAIL, None)
    assert action is None, (said, action)


@pytest.mark.parametrize("said", ["put that in a PDF", "can I get that as a Word doc?"])
async def test_asking_for_the_draft_as_a_file_still_makes_one(selector, said) -> None:
    action = await selector.select("functional_test_user", said, _PLAN, None)
    assert isinstance(action, CreateDocumentAction), (said, action)
