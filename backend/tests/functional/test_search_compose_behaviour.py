"""Does a follow-up's search query stay on the conversation's subject?

The planner composes the outbound query "with the model that has to use
the answers" - and for one real user its history arrived as an empty
list, so "Yes please" gave it two words and no subject. It invented one:
a request for mystery books produced search rounds about iPads and then
electric cars, twice, live. This sends the real compose prompt with the
history it now receives and asserts the subject survives the follow-up.
"""

import asyncio

import pytest

from backend.services.search_planner import SearchPlanner, strip_phrases

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


# A trip's second round is the return leg from the airport people use, back
# home - not a flight between the two foreign places (2026-08-26: "Rome to
# Amalfi" fares, for a route that does not exist, reached the operator).
_TRIP = (
    "i took off work from October 2 to 16. planning one way trip to rome and "
    "then back from amalfi coast. cheapest non stop option ironically?"
)
_FIRST_ROUND = [
    {"title": "Cheap Flights from Washington to Rome (IAD - FCO) | Skyscanner", "url": "https://www.skyscanner.com/routes/iad/fco/", "content": "Nonstop flights from Washington Dulles to Rome Fiumicino from $412 one way in October."},
    {"title": "United nonstop Washington Dulles to Rome | United Airlines", "url": "https://www.united.com/en/us/fly/flights-from-washington-to-rome.html", "content": "United flies nonstop IAD to FCO daily."},
]
_TRIED = ["cheapest nonstop flights Washington DC to Rome October 2026 one way"]


async def test_the_next_round_of_a_trip_is_the_return_leg_from_the_airport_people_use(llm):
    planner = SearchPlanner(llm)
    proposed = planner.another_angle(_TRIP, _FIRST_ROUND, _TRIED) or planner.refine(_TRIP, _FIRST_ROUND, _TRIED)
    lowered = proposed.casefold()
    assert proposed, "no second round proposed"
    # The missing leg is either the return from Naples home or the hop from
    # Rome down to Naples - both real flights. What must never appear is a
    # flight to Amalfi, which has no airport.
    assert "naples" in lowered or "salerno" in lowered, proposed
    assert "to amalfi" not in lowered and "rome-amalfi" not in lowered, proposed


# What the person likes belongs in a search for things to do, and nowhere
# else. Live on 2026-09-03 a generic "fun events in the area this week"
# returned a civic meeting and a paddle two hours away, while the same
# question in a conversation that had mentioned salsa produced "DC events
# this weekend salsa bachata karaoke board games" - the day's one targeted
# query. These send the real prompt to the real model.
LIKES = ("salsa dancing", "live music", "board games", "trivia nights", "hiking")


async def test_a_things_to_do_query_carries_what_they_like(llm):
    composed = SearchPlanner(llm).compose(
        "what are the most fun events happening in the area this week?", [], LIKES
    )
    lowered = composed.lower()
    assert any(
        word in lowered
        for word in ("salsa", "live music", "music", "board game", "trivia", "hiking")
    ), composed


async def test_an_unrelated_question_is_searched_as_asked(llm):
    for question in (
        "how much does a PS5 cost right now?",
        "is it safe to take ibuprofen with coffee?",
    ):
        composed = SearchPlanner(llm).compose(question, [], LIKES)
        lowered = composed.lower()
        assert not any(
            word in lowered for word in ("salsa", "board game", "trivia", "hiking")
        ), (question, composed)


# Whether a request depends on who is asking, and which of the person's own
# tastes belong in the search for it. This is the judgement that was a prompt
# suggestion until 2026-09-04, when it declined to use any of an account's
# twenty interests and answered "fun things to do in the area" with four
# listings from a town two hours away.
_LIKES = (
    "line dancing", "vintage shops/thrifting", "hiking", "dancing",
    "unique local events", "farmers markets", "live music", "traveling",
    "exploring new places", "east coast swing", "salsa", "west coast swing",
    "chess", "swing dancing", "bachata", "board games", "karaoke",
    "wineries", "breweries",
)


@pytest.mark.parametrize(
    "question,personal",
    [
        ("what's are some fun things to do in the area this week?", True),
        ("any good places to eat around here tonight?", True),
        ("what should I do this weekend?", True),
        # A taste for dancing does not change what a console costs.
        ("how much does a PS5 cost now", False),
        ("who is the prime minister of Canada", False),
        ("how long to drive to Dulles at 5pm", False),
    ],
)
async def test_the_search_is_personalised_only_where_that_is_the_answer(
    llm, question, personal
):
    import asyncio as _asyncio

    planner = SearchPlanner(llm)

    # Three passes: a judgement that holds once is not a judgement yet.
    for _ in range(3):
        fitting = await _asyncio.to_thread(planner.relevant_interests, question, _LIKES)
        terms, preferences = fitting
        if personal:
            # A judgement that nothing fits is still a judgement; what must
            # hold is that anything named comes from the person's own list,
            # never invented. The two lists are used in two places, so each is
            # bounded by the list it was chosen from.
            assert terms or preferences, (question, fitting)
            assert set(terms) <= set(_LIKES), (question, fitting)
            assert set(preferences) <= set(_LIKES), (question, fitting)
        else:
            # Nothing of theirs belongs in a query that has one right answer
            # for everyone.
            assert fitting == ((), ()), (question, fitting)


# A follow-up re-asking a place-bound question copied the previous answer's
# town into the query: "try again" after a listing of Colonial Heights events
# searched "Colonial Heights ... Courthouse Virginia" for a person whose own
# place is Courthouse (2026-09-04), so the retry came back from the wrong
# town. The place judgement must name the foreign town, keep the person's own,
# and the strip must take the town out of the query that goes out. Real
# prompt, real model, three passes.
_COLONIAL_HEIGHTS_ANSWER = (
    "Sat 5 Sep\n"
    "• Africa Fest\n"
    "  White Bank Park, 400 White Bank Road, Colonial Heights\n"
    "  A lively family reunion-style celebration of African culture — vibrant "
    "music, dancing, and mouthwatering cuisine.\n"
    "  11am–6pm · price not listed\n"
    "\n"
    "• Paddle In Your Park\n"
    "  Lakeview Park, 503 Lake Avenue, Colonial Heights\n"
    "  A relaxed, free paddle on the lake — all ages and skill levels welcome, "
    "with gear provided.\n"
    "  11am · free\n"
    "\n"
    "Not listed: 3 too far from you to be worth the trip; 10 more that never "
    "said when."
)

_WRONG_PLACE_HISTORY = [
    {
        "role": "user",
        "content": "what's are some fun things to do in the area this week?",
    },
    {"role": "assistant", "content": _COLONIAL_HEIGHTS_ANSWER},
]


async def test_the_place_judgement_names_a_previous_answers_town(llm):
    planner = SearchPlanner(llm)
    query = (
        "line dancing hiking live music events Colonial Heights this weekend "
        "unique local events farmers markets vintage shops Courthouse Virginia"
    )
    for _ in range(3):
        foreign = await asyncio.to_thread(
            planner.foreign_places, query, "Courthouse, Virginia"
        )
        named = " ".join(foreign).casefold()
        # The previous answer's town is a different location and must go.
        assert "colonial heights" in named, (foreign,)
        # The person's own place is not foreign, whatever the model names.
        assert "courthouse" not in named, (foreign,)
        assert "virginia" not in named, (foreign,)
        stripped = strip_phrases(query, foreign)
        assert "colonial heights" not in stripped.casefold(), (foreign, stripped)
        assert "courthouse" in stripped.casefold(), stripped


async def test_a_followup_query_drops_the_previous_answers_town(llm):
    from backend.services.conversation_service import _drop_foreign_places, _hold_to_place

    planner = SearchPlanner(llm)
    composed = planner.compose("try again", _WRONG_PLACE_HISTORY)
    # The caller that actually sends the query (`_research`) holds the person's
    # place in first, then drops what the judgement names and re-holds it - so
    # the query that goes out carries their place and not the previous answer's
    # town, whether compose wrote the wrong town, the right one, or none.
    question = "what's are some fun things to do in the area this week?"
    final = _hold_to_place(composed, question, "Courthouse, Virginia")
    final = await _drop_foreign_places(
        planner, final, question, "Courthouse, Virginia"
    )
    lowered = final.casefold()
    assert "colonial heights" not in lowered, (composed, final)
    assert "courthouse" in lowered, (composed, final)
