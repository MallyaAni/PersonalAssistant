"""A positive tapback that passes the offer judgement routes the offered work.

The bridge and worker tests prove that only the exact targeted Scout bubble is
carried here. This pins the remaining model boundary: the explicit acceptance
the worker creates must cause the router to do the offered thing, not merely
answer "sure" or choose an unrelated tool.
"""

from __future__ import annotations

import pytest

from backend.services.main_action_selector import MainActionSelector, SearchAction
from backend.workers.imessage_chat import _tapback_acceptance

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


# Build the production selector against the real routing model and tool roster.
@pytest.fixture
def selector(llm):
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip("internet MCP server is not configured as auto-invocable")
    return MainActionSelector(
        llm,
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


# Accepting Scout's concrete search offer routes a search with its subject and
# place intact; a generic acknowledgement would fail this property.
async def test_accepting_a_search_offer_routes_the_offered_search(selector):
    offer = "Want me to find a few good Thai places near Dupont Circle?"
    history = [
        {
            "query": "I'm trying to pick dinner for Friday.",
            "response": offer,
        }
    ]

    action = await selector.select(
        "functional_test_user",
        _tapback_acceptance(offer),
        history,
        None,
    )

    assert isinstance(action, SearchAction), action
    query = action.query.casefold()
    assert "thai" in query, action.query
    assert "dupont" in query, action.query
