"""The listing code writes, and the two ways it must not mislead.

One: an address it did not build itself. Two - subtler, and the one an empty
answer hides - a short list that reads as "that is everything", when really
four things turned up and none of them said when.
"""

from datetime import UTC, datetime, time

from backend.core.event_extraction import Extraction, ListedEvent
from backend.core.events_listing import render_listing, render_nothing_found
from backend.core.links import URL_IN_TEXT, template_is_grounded

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
EVIDENCE = (
    "Sunday Sessions at The Lawn, Batu Bolong, every Sunday from 4pm with DJ Dea. "
    "Sunset session at Potato Head on Saturday 5 September 2026."
)


def _lawn(**overrides):
    base = dict(
        name="Sunday Sessions", venue="The Lawn", area="Batu Bolong", artist="DJ Dea",
        what="Deep house on the grass.", when_text="every Sunday from 4pm", recurring=True,
        starts_at=datetime(2026, 8, 30, 16, 0, tzinfo=UTC), start_time=time(16, 0),
        price_text="free before 6pm", source_url="https://www.thelawncanggu.com/whats-on",
        source_title="The Lawn",
    )
    base.update(overrides)
    return ListedEvent(**base)


def _potato(**overrides):
    base = dict(
        name="Sunset session", venue="Potato Head", area="", artist="",
        what="Sunset by the pool.", when_text="Saturday 5 September 2026", recurring=False,
        starts_at=datetime(2026, 9, 5, 18, 0, tzinfo=UTC), start_time=time(18, 0),
        price_text="", source_url="https://potatohead.co/events", source_title="Potato Head",
    )
    base.update(overrides)
    return ListedEvent(**base)


def test_every_address_in_the_listing_is_one_code_could_build_or_a_source_gave():
    text = render_listing(Extraction((_lawn(), _potato())), NOW)
    sources = {"https://www.thelawncanggu.com/whats-on", "https://potatohead.co/events"}
    for url in URL_IN_TEXT.findall(text):
        cleaned = url.rstrip(".,;:!?)]}\"'")
        assert cleaned in sources or template_is_grounded(cleaned, EVIDENCE), cleaned


def test_a_dropped_count_is_said_out_loud():
    # "Nothing is on" and "four turned up and none said when" are different
    # answers. A listing that shows two and stays quiet about four is the
    # second answer disguised as the first.
    text = render_listing(Extraction((_lawn(),), undated=3, opening_hours=1), NOW)
    assert "3 more that never said when" in text
    assert "opening hours" in text


def test_every_event_carries_a_one_tap_calendar_link():
    # The listing used to end by asking "want any of these in your calendar?"
    # and then have no way to do it. An offer an assistant cannot fulfil is
    # worse than no offer.
    text = render_listing(Extraction((_lawn(),)), NOW)
    assert "Add: https://calendar.google.com/calendar/render?action=TEMPLATE" in text
    assert "text=Sunday+Sessions" in text
    assert "dates=20260830T160000Z" in text
    assert "location=The+Lawn+Batu+Bolong" in text
    # And it is grounded, so the link fence keeps it.
    assert template_is_grounded(
        [
            url
            for url in URL_IN_TEXT.findall(text)
            if "calendar.google.com" in url
        ][0].rstrip(".,)"),
        EVIDENCE + " Sunday Sessions",
    )


def test_an_event_with_no_clock_time_gets_an_all_day_calendar_entry():
    # Never an invented start: a day nobody gave an hour for is an all-day
    # entry, which is what the source actually asserted.
    text = render_listing(Extraction((_potato(start_time=None, starts_at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),)), NOW)
    assert "dates=20260905%2F20260906" in text, text


def test_a_clean_listing_says_nothing_about_drops():
    text = render_listing(Extraction((_lawn(),)), NOW)
    assert "Not listed" not in text


def test_a_recurring_night_shows_the_phrase_its_date_was_derived_from():
    # The date is this week's occurrence of something regular. A reader who
    # cannot see that is being told a weekly night is a one-off announcement.
    text = render_listing(Extraction((_lawn(),)), NOW)
    assert "(every Sunday from 4pm)" in text
    assert "Tomorrow, Sun 30 Aug" in text


def test_an_event_with_no_clock_time_says_so_rather_than_inventing_one():
    text = render_listing(Extraction((_potato(start_time=None),)), NOW)
    assert "time not listed" in text
    assert "12am" not in text and "0:00" not in text


def test_a_price_is_always_stated_one_way_or_the_other():
    # A listing that simply omits the price when a page gave none reads as
    # free. Both shapes are labelled so a reader - and the post-deploy
    # harness - can always find the statement.
    assert "price not listed" in render_listing(Extraction((_potato(),)), NOW)
    assert "price: free before 6pm" in render_listing(Extraction((_lawn(),)), NOW)


def test_events_are_grouped_under_the_day_they_happen():
    text = render_listing(Extraction((_lawn(), _potato())), NOW)
    assert text.index("Tomorrow, Sun 30 Aug") < text.index("Sat 5 Sep")
    assert text.count("Sunday Sessions") == 1


def test_a_long_list_is_trimmed_and_says_it_was():
    many = tuple(_lawn(name=f"Night {index}") for index in range(11))
    text = render_listing(Extraction(many), NOW, limit=3)
    assert "8 further down the list" in text


def test_an_empty_extraction_renders_nothing_so_the_caller_keeps_its_own_answer():
    assert render_listing(Extraction(), NOW) == ""


def test_an_empty_extraction_that_dropped_things_can_still_explain_itself():
    said = render_nothing_found(Extraction(undated=4))
    assert "4 more that never said when" in said
    assert render_nothing_found(Extraction()) == ""
