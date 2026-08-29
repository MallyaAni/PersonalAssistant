"""Typed events: what a model claims, and what the results actually said.

The listing that went to a real phone on 2026-08-29 carried "Time: Sundays,
4 PM - 10 PM" as an event's start. It was The Lawn's opening hours, sitting in
a snippet under a venue name. No rule was broken, because there was no rule -
the model wrote the whole listing as prose and nothing compared any of it to
the pages it came from.

These tests hold the rule that replaced it: every field is a quotation, code
checks the quotation is really in the result it names, and code - never the
model - decides the date, the clock time and every link.
"""

from datetime import UTC, datetime, time

from backend.core.event_extraction import Extraction, build_extraction

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)  # a Saturday

RESULTS = [
    {
        "title": "The Lawn Canggu - Sunday Sessions",
        "url": "https://www.thelawncanggu.com/whats-on",
        "content": "Sunday Sessions at The Lawn, Batu Bolong. Every Sunday from 4pm with DJ Dea. Free before 6pm.",
    },
    {
        "title": "La Brisa Bali",
        "url": "https://labrisabali.com/events",
        "content": "La Brisa, Echo Beach. Open daily 11am until late, kitchen until 10pm.",
    },
    {
        "title": "Potato Head Beach Club",
        "url": "https://potatohead.co/events",
        "content": "Sunset session on Saturday 5 September 2026, doors 6pm. Entry IDR 250k.",
    },
]


def _record(**overrides):
    base = {
        "source": 1,
        "name": "Sunday Sessions",
        "venue": "The Lawn",
        "area": "Batu Bolong",
        "artist": "DJ Dea",
        "when_text": "Every Sunday from 4pm",
        "when_kind": "recurring_weekday",
        "price_text": "Free before 6pm",
        "what": "Deep house on the grass.",
    }
    base.update(overrides)
    return base


def test_a_quoted_night_survives_with_its_day_and_time_worked_out_by_code():
    found = build_extraction([_record()], RESULTS, NOW)
    (event,) = found.events
    assert event.name == "Sunday Sessions" and event.venue == "The Lawn"
    # 29 August 2026 is a Saturday, so the next Sunday is the 30th - a fact
    # about the calendar, not a guess about the event.
    assert event.starts_at == datetime(2026, 8, 30, 16, 0, tzinfo=UTC)
    assert event.start_time == time(16, 0) and event.recurring is True
    assert event.price_text == "Free before 6pm"
    assert event.source_url == "https://www.thelawncanggu.com/whats-on"
    assert found.dropped == 0


def test_the_arsalon_failure_opening_hours_are_not_a_start_time():
    # The exact shape that reached a phone: a venue's hours read as an event.
    record = _record(
        source=2, name="La Brisa", venue="La Brisa", area="Echo Beach", artist="",
        when_text="Open daily 11am until late", when_kind="opening_hours",
        price_text="", what="Beach club.",
    )
    found = build_extraction([record], RESULTS, NOW)
    assert found.events == ()
    assert found.opening_hours == 1 and found.undated == 0


def test_a_time_the_result_never_stated_is_refused_however_plausible():
    # The model returns a phrase that is not in the page. It reads perfectly.
    record = _record(when_text="Every Sunday from 9pm")
    found = build_extraction([record], RESULTS, NOW)
    assert found.events == () and found.undated == 1


def test_a_record_pointing_at_no_result_is_dropped():
    for bad in (0, 99, None, "", "two"):
        found = build_extraction([_record(source=bad)], RESULTS, NOW)
        assert found.events == () and found.unsourced == 1, bad


def test_fields_the_named_result_does_not_carry_are_dropped_not_kept():
    # The venue and the name must be in that result; area, artist and price
    # are optional, so an invented one becomes empty rather than sinking the
    # whole record.
    found = build_extraction(
        [_record(area="Seminyak", artist="DJ Nobody", price_text="IDR 500k")], RESULTS, NOW
    )
    (event,) = found.events
    assert event.area == "" and event.artist == "" and event.price_text == ""

    invented_venue = build_extraction([_record(venue="Sky Garden")], RESULTS, NOW)
    assert invented_venue.events == () and invented_venue.unsourced == 1


def test_an_explicit_date_is_read_from_the_phrase_not_invented():
    record = _record(
        source=3, name="Sunset session", venue="Potato Head", area="", artist="",
        when_text="Saturday 5 September 2026, doors 6pm", when_kind="one_off_date",
        price_text="Entry IDR 250k", what="Sunset by the pool.",
    )
    (event,) = build_extraction([record], RESULTS, NOW).events
    assert event.starts_at == datetime(2026, 9, 5, 18, 0, tzinfo=UTC)
    assert event.recurring is False and event.price_text == "Entry IDR 250k"


def test_a_day_with_no_clock_time_keeps_the_day_and_claims_no_hour():
    results = [{"title": "Market", "url": "https://x.test/m", "content": "Canggu night market every Friday."}]
    record = _record(
        source=1, name="Canggu night market", venue="Canggu", area="", artist="",
        when_text="every Friday", when_kind="recurring_weekday", price_text="", what="A market.",
    )
    (event,) = build_extraction([record], results, NOW).events
    assert event.start_time is None
    assert event.starts_at == datetime(2026, 9, 4, 0, 0, tzinfo=UTC)


def test_an_address_cannot_ride_in_on_the_one_free_text_field():
    # `what` is the only field the model writes in its own words, so it is the
    # only place an invented link could hide.
    record = _record(what="Deep house on the grass, see https://maps.app.goo.gl/xyz")
    (event,) = build_extraction([record], RESULTS, NOW).events
    assert "goo.gl" not in event.what and "http" not in event.what
    # And the clause that only existed to carry the link goes with it: a
    # sentence trailing off as "..., see" is a visible defect where a missing
    # link is not.
    assert event.what == "Deep house on the grass"


def test_a_clean_description_is_left_exactly_as_written():
    (event,) = build_extraction([_record(what="Deep house on the grass.")], RESULTS, NOW).events
    assert event.what == "Deep house on the grass."


def test_the_same_night_listed_by_two_pages_appears_once():
    twice = [_record(), _record()]
    assert len(build_extraction(twice, RESULTS, NOW).events) == 1


def test_events_come_back_in_the_order_they_happen():
    later = _record(
        source=3, name="Sunset session", venue="Potato Head", area="", artist="",
        when_text="Saturday 5 September 2026, doors 6pm", when_kind="one_off_date",
        price_text="", what="Sunset.",
    )
    found = build_extraction([later, _record()], RESULTS, NOW)
    assert [event.name for event in found.events] == ["Sunday Sessions", "Sunset session"]


def test_nothing_in_nothing_out():
    empty = build_extraction([], RESULTS, NOW)
    assert empty == Extraction() and empty.dropped == 0


# The date and the door time are often two sentences apart: "Sunset Session on
# Saturday 5 September 2026 at Potato Head, Seminyak. Doors 6pm, entry IDR
# 250k." Measured on the real model 2026-08-29, it quotes the date and drops
# the time, and "time not listed" then throws away something the page said.
_TWO_SENTENCES = [
    {
        "title": "Potato Head - Sunset Session",
        "url": "https://potatohead.co/events",
        "content": "Sunset Session on Saturday 5 September 2026 at Potato Head, Seminyak. Doors 6pm, entry IDR 250k.",
    },
    {
        "title": "The Lawn",
        "url": "https://x.test/lawn",
        "content": "Sunday Sessions on Saturday 5 September 2026 at The Lawn. The bar is open until 11pm every night.",
    },
    {
        "title": "Canggu night market",
        "url": "https://x.test/market",
        "content": "Night market on Saturday 5 September 2026 at Berawa. Kitchen until 10pm.",
    },
]


def _dated(source: int, name: str, venue: str):
    return _record(
        source=source, name=name, venue=venue, area="", artist="",
        when_text="Saturday 5 September 2026", when_kind="one_off_date",
        price_text="", what="A night.",
    )


def test_a_door_time_beside_the_date_is_read():
    (event,) = build_extraction(
        [_dated(1, "Sunset Session", "Potato Head")], _TWO_SENTENCES, NOW
    ).events
    assert event.start_time == time(18, 0)
    assert event.starts_at == datetime(2026, 9, 5, 18, 0, tzinfo=UTC)


def test_a_closing_time_beside_the_date_is_not():
    # This is the failure the whole module exists to end, in its subtlest
    # form: a clock near the date that is not a start. "Open until 11pm" and
    # "kitchen until 10pm" must leave the event with no time at all.
    for index, name, venue in ((2, "Sunday Sessions", "The Lawn"), (3, "Night market", "Berawa")):
        (event,) = build_extraction([_dated(index, name, venue)], _TWO_SENTENCES, NOW).events
        assert event.start_time is None, (name, event)


def test_a_clock_far_from_the_date_is_never_borrowed():
    far = [
        {
            "title": "Venue",
            "url": "https://x.test/v",
            "content": (
                "Something on Saturday 5 September 2026 at the venue. "
                + "Filler about the neighbourhood and its history. " * 4
                + "Doors 8pm for an unrelated night."
            ),
        }
    ]
    (event,) = build_extraction([_dated(1, "Something", "venue")], far, NOW).events
    assert event.start_time is None, event
