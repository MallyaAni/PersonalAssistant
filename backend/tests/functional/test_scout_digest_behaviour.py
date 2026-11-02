"""Does "what did Scout send me?" reach the record, and does the reply report
it as history rather than as a fresh shortlist?

Scout is push-only: its digest goes to a phone and the chat never sees it, so
before scout_digest these questions were answered from conversation history -
which never contains a digest - or invented. The tool description is a prompt,
so this is a live test of the routing it produces, and of the reply context
built from what the repository returned.
"""

from __future__ import annotations

import pytest

from backend.agents.graph import _build_turn_context
from backend.tools import RecallHistoryAction, ScoutDigestAction

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
        llm,
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


async def test_asking_what_scout_sent_reaches_the_record(selector):
    for said in (
        "what did scout send me?",
        "did you ever send me that pottery thing?",
        "what did scout recommend last week?",
    ):
        action = await selector.select("functional_test_user", said, [], None)
        assert isinstance(action, ScoutDigestAction), (said, action)


async def test_a_named_period_is_resolved_into_the_tools_own_bounds(selector):
    action = await selector.select(
        "functional_test_user",
        "what was in yesterday's digest?",
        [],
        None,
        local_now=(
            "Saturday 2026-11-01 10:00 - they are in Arlington, Virginia "
            "(America/New_York)"
        ),
    )
    assert isinstance(action, ScoutDigestAction), action
    # The model resolves the word; the repository reads the dates it stated.
    assert action.since or action.until, action


async def test_what_they_said_is_recall_not_what_scout_sent(selector):
    # The near-miss pair. "Did you ever send me" is the digest record;
    # "did I ever tell you" is the transcript store, and routing it here would
    # answer a memory question with Scout's finds.
    action = await selector.select(
        "functional_test_user", "did I ever tell you about my trip to Lisbon?", [], None
    )
    assert isinstance(action, RecallHistoryAction), action


def test_the_reply_is_told_the_read_back_is_history_not_a_new_shortlist():
    context = _build_turn_context(
        {
            "digest_outcomes": [
                {
                    "kind": "digest",
                    "count": 2,
                    "items": [
                        {
                            "title": "A jazz trio plays",
                            "locality": "Arlington, Virginia",
                            "when": "2026-11-01",
                            "reaction": "liked",
                        },
                        {
                            "title": "A winery evening",
                            "locality": None,
                            "when": "2026-10-30",
                            "reaction": "disliked",
                        },
                    ],
                }
            ]
        }
    )
    assert '"A jazz trio plays" (Arlington, Virginia), sent 2026-11-01' in context
    assert "thumbs-up" in context
    assert "thumbs-down" in context
    assert "history, not new suggestions" in context
    # Nothing from the person's own past was invented to fill the block.
    assert "winery" in context
    assert "pottery" not in context
