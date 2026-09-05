"""Whether a question depends on where the person is: the model's call.

This replaced a word list ("events", "near me", "brunch", "weather"...) that
decided it in code and missed every phrasing its author had not imagined.
The cases are real shapes of what people ask, deliberately without the words
the list keyed on, and the property under test is the verdict alone - the
holds that act on it are pinned in the unit suite. Each case is asked three
times; a judgement at temperature zero that flips is a judgement that is not
being made, and the floor is two of three so a single flake cannot refuse a
deploy for a prompt that works.

pinned prompt: search/place.
"""

import pytest

from backend.services.search_planner import SearchPlanner

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_PLACE = "Arlington, Virginia"

# (question, query as composed, expected verdict)
_CASES = [
    ("anything fun going on this weekend?", "fun things to do this weekend", True),
    ("where should the two of us go for dinner on friday?", "dinner ideas friday night", True),
    ("is it going to rain tomorrow", "weather forecast tomorrow", True),
    ("how long will it take me to get to dulles at 5", "drive time to Dulles airport 5pm", True),
    ("what did the fed decide this week?", "Federal Reserve decision this week", False),
    ("how much does a ps5 cost now", "PS5 price 2026", False),
    ("who is the prime minister of canada", "current prime minister of Canada", False),
    ("does only one person win at the end of surviving paradise?", "Surviving Paradise finale winner", False),
]


@pytest.mark.parametrize(("question", "query", "expected"), _CASES)
async def test_the_verdict_follows_the_question_not_its_words(llm, question, query, expected):
    planner = SearchPlanner(llm)
    verdicts = [planner.place_judgement(question, query, _PLACE).bound for _ in range(3)]
    agreed = sum(1 for verdict in verdicts if verdict is expected)
    assert agreed >= 2, (question, verdicts)


async def test_an_unknown_place_still_yields_a_verdict_and_names_nothing_foreign(llm):
    judgement = SearchPlanner(llm).place_judgement(
        "anything fun going on this weekend?", "fun things to do this weekend", ""
    )
    assert judgement.bound is True
    assert judgement.foreign == ()
