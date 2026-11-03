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


async def test_a_shared_interest_is_recall_not_the_digest_record(selector):
    # "What do we both like?" is memory, not what the sweep sent. Naming Scout
    # must not turn it into a digest read-back; the live sweep journey caught
    # this route on 2026-11-03.
    action = await selector.select(
        "functional_test_user", "Scout, what do we both like?", [], None
    )
    assert not isinstance(action, ScoutDigestAction), action
    assert action is None or isinstance(action, RecallHistoryAction), action


async def test_room_chatter_does_not_turn_a_shared_interest_into_a_digest(selector):
    # The failing journey is a group whose room has just settled on Thai for
    # Friday. That chatter is what the router sees beside the question, and
    # the same question with it in history must not become a digest read-back.
    history = [
        {
            "query": "ok so we all settled on thai for friday dinner, 7pm",
            "response": "Thai, Friday at 7pm. Want me to put it in the calendar?",
        },
    ]
    action = await selector.select(
        "functional_test_user", "Scout, what do we both like?", history, None
    )
    assert not isinstance(action, ScoutDigestAction), action
    assert action is None or isinstance(action, RecallHistoryAction), action


async def test_the_live_group_clock_does_not_turn_a_shared_interest_into_a_digest(
    selector,
):
    # A group has no timezone, so the router sees the UTC unknown-zone clock.
    # That is the prompt the live sweep sampled when it reported route=What
    # Scout sent on 2026-11-03, and the same question with that clock in view
    # must still be memory, not a digest read-back. Fresh user ids keep the
    # decision cache from answering all three samples with the first one.
    clock = (
        "Tuesday 2026-11-03 19:31 UTC (their time zone is not known); "
        "this weekend is Sat 2026-11-07 to Sun 2026-11-08"
    )
    for sample in range(3):
        action = await selector.select(
            f"functional_test_user_{sample}",
            "Scout, what do we both like?",
            [],
            None,
            local_now=clock,
            zone="",
            skills=[],
        )
        assert not isinstance(action, ScoutDigestAction), action
        assert action is None or isinstance(action, RecallHistoryAction), action


async def test_the_scout_record_judgement_reads_the_message(llm):
    # The guard is a judgement with a schema, not a pattern: it has to tell a
    # question about people from a question about what Scout sent or when it
    # runs, in the words the router is likely to see.
    from backend.services.scout_route import judge_scout_record

    assert await judge_scout_record(llm, "Scout, what do we both like?") is False
    assert await judge_scout_record(llm, "what do we have in common?") is False
    assert await judge_scout_record(llm, "what did scout send me?") is True
    assert await judge_scout_record(llm, "when does scout run?") is True


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
