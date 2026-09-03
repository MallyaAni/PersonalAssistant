"""A later search round keeps the place the first query carried. On
2026-09-02 the round after "events Arlington Virginia this week" searched
without Arlington and a New York page won an Arlington listing."""
from backend.services.conversation_service import _hold_to_place, _keep_the_place


def test_a_second_round_that_dropped_the_city_gets_it_back():
    first = "fun events happening this week Arlington Virginia Courthouse September 2026"
    assert _keep_the_place("best things to do September 5-7 2026 weekend", first, "Arlington, Virginia") == (
        "best things to do September 5-7 2026 weekend Arlington Virginia"
    )


def test_a_round_that_kept_the_city_and_a_query_that_never_had_it_are_left_alone():
    first = "fun events this week Arlington Virginia"
    assert _keep_the_place("arlington va concerts September 2026", first, "Arlington, Virginia") == "arlington va concerts September 2026"
    assert _keep_the_place("DGX Spark VLM models 2026", "DGX Spark VLM inference models", "Arlington, Virginia") == "DGX Spark VLM models 2026"
    assert _keep_the_place("anything", first, "") == "anything"
    assert _keep_the_place("", first, "Arlington, Virginia") == ""



# The first query is the router's, and under load it left the place out for
# a Raleigh account: "local events this week 2026-09-03". For a question
# about here, every round's query is held to the person's place in code.
def test_a_place_bound_query_without_the_place_gets_it():
    question = "what are the most fun events happening in the area this week?"
    assert _hold_to_place("local events this week 2026-09-03", question, "Raleigh, NC") == "local events this week 2026-09-03 Raleigh NC"
    assert _hold_to_place("fun events Raleigh NC this week", question, "Raleigh, NC") == "fun events Raleigh NC this week"
    assert _hold_to_place("fun events happening this week Arlington Virginia Courthouse", question, "Courthouse, Virginia") == (
        "fun events happening this week Arlington Virginia Courthouse"
    )


def test_a_question_not_about_here_and_an_unknown_place_are_left_alone():
    assert _hold_to_place("Federal Reserve meeting September 2026 decision", "what did the Fed decide?", "Raleigh, NC") == "Federal Reserve meeting September 2026 decision"
    assert _hold_to_place("local events this week", "what's on this week?", "") == "local events this week"
    # Time words alone do not make a question about here.
    assert _hold_to_place("Federal Reserve policy meeting decision this week September 2026", "what did the Fed decide this week?", "Courthouse, Virginia") == (
        "Federal Reserve policy meeting decision this week September 2026"
    )
    assert _hold_to_place("PS5 price 2026", "what does a PS5 cost tonight?", "Raleigh, NC") == "PS5 price 2026"
