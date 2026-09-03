"""A later search round keeps the place the first query carried. On
2026-09-02 the round after "events Arlington Virginia this week" searched
without Arlington and a New York page won an Arlington listing."""
from backend.services.conversation_service import _keep_the_place


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
