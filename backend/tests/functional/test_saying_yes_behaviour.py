"""Saying yes, in words, to something the assistant just offered.

This is the path a person actually uses. The operator put it plainly on
2026-08-29: "natural language is the right way to do this." A tapback is a
shortcut for it, never a replacement, and a shortcut that works while the
thing it shortcuts does not is worse than no shortcut at all.

So this measures the plain case against the real routing model: the assistant
offers to do one concrete thing, the person answers "yes", and the offered
work has to be what gets routed - with the subject intact, not a fresh guess.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


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


# Every way a person says yes to the same offer. If the shortcut is worth
# having, these have to work first.
_YESES = ["yes", "yes please", "do it", "go for it", "sure", "yeah go ahead", "please do"]

# The clock the router is always given in production. Passing it here is not a
# convenience: without it the model has no date, and a reschedule offer for
# "Friday" came back dated 2025-09-05 - a year in the past.
NOW_LINE = (
    "Saturday 2026-08-29 18:00 - they are in Arlington, Virginia "
    "(America/New_York); the weekend is today and tomorrow"
)

_SEARCH_OFFER = [
    {
        "query": "I'm trying to pick dinner for Friday.",
        "response": "Want me to find a few good Thai places near Dupont Circle?",
        "created_at": "2026-08-29T22:00:00+00:00",
    }
]


@pytest.mark.parametrize("said", _YESES)
async def test_saying_yes_to_a_search_offer_runs_that_search(selector, said):
    from backend.services.main_action_selector import SearchAction

    action = await selector.select(
        "yes_user", said, _SEARCH_OFFER, None, local_now=NOW_LINE
    )
    print(f"\n{said!r} -> {action!r}")
    assert isinstance(action, SearchAction), (said, action)
    query = action.query.casefold()
    assert "thai" in query, (said, action.query)
    assert "dupont" in query, (said, action.query)


async def test_saying_yes_to_a_reminder_offer_changes_the_reminder(selector):
    from backend.services.main_action_selector import ManageTasksAction

    history = [
        {
            "query": "that dentist reminder is at a bad time",
            "response": "I can move it to Friday at 10am if you want.",
            "created_at": "2026-08-29T22:00:00+00:00",
        }
    ]
    action = await selector.select(
        "yes_user", "yes please", history, None, local_now=NOW_LINE
    )
    print(f"\nreminder offer -> {action!r}")
    # Rescheduling an existing reminder, not creating a second one - the
    # distinction the whole manage-vs-schedule split exists for.
    assert isinstance(action, ManageTasksAction), action
    assert action.operation == "reschedule", action
    assert "dentist" in str(action.which or "").casefold(), action
    assert (action.hour, action.minute) == (10, 0), action
    # And the date it lands on is in the future, read from the clock it was
    # given rather than guessed.
    if action.on_date:
        assert action.on_date >= "2026-08-29", action


async def test_yes_after_no_offer_does_not_invent_work(selector):
    # The other half. "Yes" following a statement is agreement, not an
    # instruction, and it must not send the assistant off doing something.
    history = [
        {
            "query": "is it going to rain friday?",
            "response": "Friday should be sunny, with a high around 75.",
            "created_at": "2026-08-29T22:00:00+00:00",
        }
    ]
    action = await selector.select(
        "yes_user", "yes", history, None, local_now=NOW_LINE
    )
    print(f"\nyes after a plain answer -> {action!r}")
    assert action is None, action


# Every shape of previous message a bare "yes" can follow, and whether it may
# act. The ones that must NOT act are the point: agreeing with a statement is
# not an instruction.
_NOTHING_OFFERED = [
    # A plain answer. This is the measured failure: it routed a fresh weather
    # call for a person who was only agreeing.
    ("is it going to rain friday?", "Friday should be sunny, with a high around 75."),
    # A choice. "Yes" does not pick one, so acting means guessing.
    ("where should we eat?", "Which sounds better to you, Thai or pizza?"),
    # Already done. Acting again would do it twice.
    ("move my dentist reminder to friday", "Done — I moved it to Friday at 10:00 AM."),
    # A joke, and warmth generally.
    ("look at this tiny hat", "Haha, that really is a very small hat 😄"),
    # A clarifying question. "Yes" supplies nothing it asked for.
    ("edit that photo", "Which one did you mean, the jacket by the water or the one at night?"),
    # A finished listing. There is nothing left to accept.
    ("what's on this weekend?", "Here are three things on this weekend near you."),
]


@pytest.mark.parametrize(("asked", "answered"), _NOTHING_OFFERED)
async def test_yes_after_something_that_offered_nothing_takes_no_tool(selector, asked, answered):
    history = [{"query": asked, "response": answered, "created_at": "2026-08-29T22:00:00+00:00"}]
    action = await selector.select("yes_user", "yes", history, None, local_now=NOW_LINE)
    print(f"\nafter {answered[:48]!r} -> {action!r}")
    assert action is None, (answered, action)


async def test_a_bare_yes_with_no_conversation_at_all_takes_no_tool(selector):
    action = await selector.select("yes_user", "yes", [], None, local_now=NOW_LINE)
    print(f"\nyes with no history -> {action!r}")
    assert action is None, action


async def test_declining_an_offer_takes_no_tool(selector):
    # "No" is not assent, so the guard never sees it - the router has to get
    # this right on its own, and it is worth knowing that it does.
    action = await selector.select("yes_user", "no thanks", _SEARCH_OFFER, None, local_now=NOW_LINE)
    print(f"\nno thanks after an offer -> {action!r}")
    assert action is None, action


async def test_a_yes_carrying_its_own_instruction_is_never_withheld(selector):
    # The bound on the guard. This follows a message that offered nothing, so
    # the offer judgement is false - and it must still be acted on, because
    # the person asked for something in the same breath.
    from backend.services.main_action_selector import SearchAction

    history = [
        {
            "query": "is it going to rain friday?",
            "response": "Friday should be sunny, with a high around 75.",
            "created_at": "2026-08-29T22:00:00+00:00",
        }
    ]
    action = await selector.select(
        "yes_user",
        "yes, and find me a rooftop bar in Arlington for friday",
        history,
        None,
        local_now=NOW_LINE,
    )
    print(f"\nyes-plus-instruction -> {action!r}")
    assert isinstance(action, SearchAction), action
    assert "rooftop" in action.query.casefold(), action.query


async def test_the_offer_case_still_works_after_the_guard(selector):
    # The regression that would matter most: a guard that refuses too much
    # would break the thing the whole feature is for.
    from backend.services.main_action_selector import SearchAction

    for said in ("yes", "do it", "sounds good"):
        action = await selector.select("yes_user", said, _SEARCH_OFFER, None, local_now=NOW_LINE)
        assert isinstance(action, SearchAction), (said, action)
        assert "thai" in action.query.casefold(), (said, action.query)
