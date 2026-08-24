"""Does the router actually choose search_history well?

The tool's description is a prompt, and per the completion rule a prompt is
untested until the real model's decisions are asserted on. Structural coverage
(test_history_recall.py) proves the wiring; this proves the judgement: a
reference to something said before selects the tool, and an ordinary question
does not start rummaging through the transcript.

Asserted on properties - which action came back - never on wording. Tool
selection decodes at temperature zero (chat_with_tools pins it), so red here
means the description or the model changed, not sampling luck.
"""

import pytest

from backend.services.main_action_selector import (
    MainActionSelector,
    RecallHistoryAction,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session")
def selector(llm):
    return MainActionSelector(
        llm,
        mcp_invocation=None,
        search_server_id="unused",
        search_tool_name="unused",
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


# References to something said before, phrased the ways people actually point
# backwards. Each must reach for the transcript rather than guessing.
@pytest.mark.parametrize(
    "asked",
    [
        "what was the name of that restaurant I told you about last month?",
        "when did we last talk about my resume?",
        "what did I say my sister's dog was called?",
        "remind me what we decided about the trip budget",
    ],
)
async def test_a_reference_to_the_past_searches_history(selector, asked):
    action = await selector.select("functional_test_user", asked, [], None)
    assert isinstance(action, RecallHistoryAction), (
        f"{asked!r} chose {type(action).__name__} instead of searching history"
    )
    # The query must carry the thing to look for, not be a copy of the whole
    # request or an empty string the parser would have rejected.
    assert action.query.strip()


# Questions the visible conversation or general knowledge already answers.
# Rummaging through the transcript for these would slow every ordinary turn
# and read as the assistant misunderstanding the question.
@pytest.mark.parametrize(
    "asked",
    [
        "what's a good pasta recipe for two?",
        "how do I politely decline a meeting invite?",
    ],
)
async def test_an_ordinary_question_stays_out_of_the_archive(selector, asked):
    action = await selector.select("functional_test_user", asked, [], None)
    assert not isinstance(action, RecallHistoryAction), (
        f"{asked!r} searched history for a question that never pointed at it"
    )


async def test_a_time_bounded_reference_still_searches(selector):
    # The window fields are optional and the model may omit them - selection
    # is what this asserts. When it does state a bound, it must be a date the
    # search can use, resolved against the clock it was given.
    action = await selector.select(
        "functional_test_user",
        "what was that restaurant I mentioned last week?",
        [],
        None,
        local_now="2026-08-24 21:00 (America/New_York)",
    )
    assert isinstance(action, RecallHistoryAction)
    from datetime import datetime

    for bound in (action.since, action.until):
        if bound:
            datetime.fromisoformat(bound)


async def test_a_followup_to_the_visible_conversation_does_not_dig(selector):
    # "It" here is on screen. The rule the action contract already states -
    # short replies continue the recent subject - must outrank the new tool.
    history = [
        {
            "query": "draft an email asking for Saturday off",
            "response": "Here's a draft: ...",
        }
    ]
    action = await selector.select(
        "functional_test_user", "make it more casual", history, None
    )
    assert not isinstance(action, RecallHistoryAction)
