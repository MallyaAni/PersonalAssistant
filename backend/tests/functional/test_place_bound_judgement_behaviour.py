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


# A query that drifted must not be able to veto its own correction.
#
# 2026-09-07, live: asked "whats going on in the area tomorrow?" from
# Courthouse, Virginia, compose sampled "tomorrow events Napa Valley
# September 7" - a town in nobody's memory, history, interests or locality.
# Shown that query, this judgement answered place_bound false, which is
# defensible read narrowly: the query WAS bound to Napa rather than to the
# asker's home. But false switches off every hold the caller applies,
# including the one that strips foreign places, so the invented town disabled
# the guard that exists to remove it. The turn then ran eight searches around
# Napa Valley and listed Calistoga as being near Courthouse.
#
# Both halves are asserted here, because either alone leaves the hole open:
# the verdict stays true, AND the drifted town is named foreign so the caller
# has something to strip.
_DRIFTED = [
    ("whats going on in the area tomorrow?", "tomorrow events Napa Valley September 7", "napa"),
    ("what's on this weekend?", "Portland Oregon events this weekend", "portland"),
    ("where should we eat tonight?", "best dinner Austin Texas tonight", "austin"),
]


@pytest.mark.parametrize(("question", "drifted", "town"), _DRIFTED)
async def test_a_drifted_query_keeps_the_verdict_and_names_the_town(llm, question, drifted, town):
    planner = SearchPlanner(llm)
    verdicts = [planner.place_judgement(question, drifted, _PLACE) for _ in range(3)]
    bound = sum(1 for verdict in verdicts if verdict.bound is True)
    assert bound >= 2, (question, drifted, [verdict.bound for verdict in verdicts])
    named = sum(
        1
        for verdict in verdicts
        if any(town in place.casefold() for place in verdict.foreign)
    )
    assert named >= 2, (question, drifted, [verdict.foreign for verdict in verdicts])


# The city that contains where they are is where they are.
#
# 2026-09-07: told the person is in "Courthouse, Virginia" - which is what the
# deployment passes, label and region joined - the judgement named "Arlington"
# foreign on "events Arlington Virginia tomorrow". Arlington is the city
# Courthouse is a neighbourhood of. The caller strips whatever is named, so a
# correct local query lost its own city and searched the whole state: the
# guard that exists to keep a search local was making it less local. Measured
# 3/3 foreign before the prompt said containing places are not foreign, 0/3
# after.
_NEIGHBOURHOOD = "Courthouse, Virginia"


async def test_the_city_that_contains_their_neighbourhood_is_not_foreign(llm):
    planner = SearchPlanner(llm)
    named = [
        any("arlington" in place.casefold() for place in
            planner.place_judgement(
                "whats going on in the area tomorrow?",
                "events Arlington Virginia tomorrow",
                _NEIGHBOURHOOD,
            ).foreign)
        for _ in range(3)
    ]
    assert sum(named) == 0, named


async def test_a_genuinely_distant_place_is_still_foreign_from_a_neighbourhood(llm):
    # The other half: the exemption must not swallow real drift.
    planner = SearchPlanner(llm)
    named = [
        any("napa" in place.casefold() for place in
            planner.place_judgement(
                "whats going on in the area tomorrow?",
                "tomorrow events Napa Valley September 7",
                _NEIGHBOURHOOD,
            ).foreign)
        for _ in range(3)
    ]
    assert sum(named) >= 2, named
