"""Does a follow-up's search query stay on the conversation's subject?

The planner composes the outbound query "with the model that has to use
the answers" - and for one real user its history arrived as an empty
list, so "Yes please" gave it two words and no subject. It invented one:
a request for mystery books produced search rounds about iPads and then
electric cars, twice, live. This sends the real compose prompt with the
history it now receives and asserts the subject survives the follow-up.
"""

import pytest

from backend.services.search_planner import SearchPlanner

pytestmark = pytest.mark.asyncio

_HISTORY = [
    {
        "role": "user",
        "content": (
            "I really like mystery books. What are the best mystery books "
            "that came out this year?"
        ),
    },
    {
        "role": "assistant",
        "content": (
            "My training stops before this year - want me to run a web "
            "search for the best recent mystery books?"
        ),
    },
]


async def test_a_bare_affirmation_searches_the_conversations_subject(llm):
    composed = SearchPlanner(llm).compose("Yes please", _HISTORY)

    lowered = composed.casefold()
    assert "myster" in lowered or "book" in lowered, composed
    # The failure mode was topic invention; a query about consumer tech is
    # the recorded shape of it.
    for invented in ("ipad", "iphone", "electric car", "laptop"):
        assert invented not in lowered, composed


# A live "what's on" question whose place lives only in the conversation
# (2026-08-25: searched without the place, got mini PC reviews). The query
# must carry the place, the kind of thing, and the dates the days mean.
_CANGGU = [
    {"role": "user", "content": "what's on in canggu this week?"},
    {
        "role": "assistant",
        "content": (
            "From memory: Luigi's Hot Pizza and Miss Fish in Canggu both run "
            "weekly nights, but I can't verify this week's lineup."
        ),
    },
    {
        "role": "user",
        "content": (
            "This is too generic. Luigi's had a big party Monday, Miss Fish "
            "had a fashion thing Tuesday"
        ),
    },
    {"role": "assistant", "content": "Understood - those are the venues you mean."},
]


async def test_a_whats_on_question_searches_for_the_place_and_the_dates(llm):
    composed = SearchPlanner(llm).compose("what's going on Weds-Sunday?", _CANGGU)
    lowered = composed.casefold()
    assert "canggu" in lowered, composed
    assert any(word in lowered for word in ("event", "lineup", "party", "parties", "what's on", "nightlife", "club")), composed
    assert any(mark in lowered for mark in ("aug", "27", "28", "29", "30", "31", "weekend", "2026")), composed
