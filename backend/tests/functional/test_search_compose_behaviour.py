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
