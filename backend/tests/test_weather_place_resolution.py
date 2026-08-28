"""The weather tool resolves the places people write, and words a day plainly."""

from __future__ import annotations

from backend.mcp.servers.internet import choose_match, describe_day, place_candidates


def test_dc_and_its_spellings_resolve_to_washington_in_the_district():
    for written in ("DC", "Washington, DC", "Washington DC", "washington d.c.", "the District", "DMV area", "the DMV"):
        assert place_candidates(written)[0] == ("Washington", "District of Columbia"), written


def test_a_city_with_a_state_keeps_the_state_for_choosing():
    assert place_candidates("Arlington, VA") == [("Arlington, VA", None), ("Arlington", "Virginia")]
    assert place_candidates("Arlington TX")[-1] == ("Arlington", "Texas")
    assert place_candidates("20024") == [("20024", None)]


def test_the_match_in_the_named_state_wins_over_the_geocoders_first():
    matches = [{"name": "Arlington", "admin1": "Texas"}, {"name": "Arlington", "admin1": "Virginia"}]
    assert choose_match(matches, "Virginia")["admin1"] == "Virginia"
    assert choose_match(matches, None)["admin1"] == "Texas"
    assert choose_match([], "Virginia") is None


def test_a_low_chance_of_rain_is_a_chance_not_a_violent_shower():
    assert describe_day(82, 29) == "chance of showers (29%)"
    assert describe_day(95, 20) == "chance of storms (20%)"
    assert describe_day(82, 80) == "heavy showers"
    assert describe_day(3, 10) == "overcast"



def test_words_that_point_without_naming_are_not_places():
    from backend.mcp.servers.internet import not_a_place

    for word in ("here", "Here", "my location", " my current location ", "outside", "near me", "", "home", "N/A"):
        assert not_a_place(word), word
    for word in ("Arlington, Virginia", "DC", "Here, Somalia", "Paris", "22201", "Nearby, Ontario"):
        assert not not_a_place(word), word


def test_the_forecast_refuses_a_place_that_is_not_a_place():
    import asyncio
    import json

    from backend.mcp.servers.internet import get_weather

    # No network: the refusal happens before the geocoder is asked. "here"
    # geocoded to Here, Togdheer, Somalia and its weather was reported to a
    # group in Virginia as its own (2026-08-28).
    payload = json.loads(asyncio.run(get_weather("here", 1)))
    assert payload["error"] == "no_place"
    assert "ask where they are" in payload["message"]
