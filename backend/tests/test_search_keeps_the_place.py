"""A later search round keeps the place the first query carried. On
2026-09-02 the round after "events Arlington Virginia this week" searched
without Arlington and a New York page won an Arlington listing."""
from datetime import UTC, datetime

from backend.services.conversation_service import _hold_to_dates, _hold_to_place, _keep_the_place

WED = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)


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
# a Raleigh account: "local events this week 2026-09-03". For a question the
# judgement says is about here, every round's query is held to the person's
# place in code. Whether it is about here is the model's verdict (`bound`),
# measured in functional/test_place_bound_judgement_behaviour.py; these pin
# what the code does with the verdict.
def test_a_place_bound_query_without_the_place_gets_it():
    assert _hold_to_place("local events this week 2026-09-03", True, "Raleigh, NC") == "local events this week 2026-09-03 Raleigh NC"
    assert _hold_to_place("fun events Raleigh NC this week", True, "Raleigh, NC") == "fun events Raleigh NC this week"
    assert _hold_to_place("fun events happening this week Arlington Virginia Courthouse", True, "Courthouse, Virginia") == (
        "fun events happening this week Arlington Virginia Courthouse"
    )


def test_a_question_not_about_here_and_an_unknown_place_are_left_alone():
    # "what did the Fed decide this week?": not about here, whatever the time words.
    assert _hold_to_place("Federal Reserve meeting September 2026 decision", False, "Raleigh, NC") == "Federal Reserve meeting September 2026 decision"
    assert _hold_to_place("local events this week", True, "") == "local events this week"
    # An unjudged question - the model could not be asked - is left as composed.
    assert _hold_to_place("PS5 price 2026", None, "Raleigh, NC") == "PS5 price 2026"


# The days a question means, written out for the sources. Measured on the
# operator's profile: place alone returned four dated events and none inside
# the week asked; place with the dates returned five, all inside it.
def test_a_whats_on_query_gets_the_days_it_means():
    assert _hold_to_dates("fun events Arlington Virginia", "what's on this week?", WED, True) == (
        "fun events Arlington Virginia September 2-6 2026"
    )
    assert _hold_to_dates("things to do Arlington", "anything happening tonight?", WED, True) == (
        "things to do Arlington September 2 2026"
    )
    # A question with a window that the judgement says is not about here is
    # left alone: "what did the Fed decide this week?" is not given a date
    # range it never asked for.
    assert _hold_to_dates("Fed decision", "what did the Fed decide this week?", WED, False) == "Fed decision"


def test_a_query_that_already_names_days_and_a_question_with_no_window_are_left_alone():
    already = "Arlington events September 5-7 2026"
    assert _hold_to_dates(already, "what's on this weekend?", WED, True) == already
    assert _hold_to_dates("PS5 price", "what does a PS5 cost?", WED, False) == "PS5 price"
    assert _hold_to_dates("jazz nights Arlington", "what jazz nights are there?", WED, True) == "jazz nights Arlington"
