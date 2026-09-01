"""Four ways a digest read badly, each taken from a delivered message.

None of these were crashes. Every one of them shipped, was read by a person,
and made the agent look like it was not paying attention — which is the only
failure mode that matters for something that messages you unprompted.
"""

from datetime import UTC, date, datetime, timedelta

from backend.discovery.digest import _clean_url, render_message
from backend.discovery.events import DiscoveredEvent, clean_title
from backend.discovery.listing_filter import looks_like_a_directory
from backend.discovery.relevance import (
    MIN_ATTRIBUTION_MARGIN,
    RankedCandidate,
    RelevanceRanker,
    ScoredCandidate,
)
from backend.discovery.url_dates import date_from_url, looks_past

_TODAY = date(2026, 8, 8)
_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


# --- 1. an interest named when the match was really a tie ---------------------


def _ranker(**vectors: list[float]) -> RelevanceRanker:
    return RelevanceRanker(vectors, {label: 2 for label in vectors})


def _candidate(embedding: list[float]) -> ScoredCandidate:
    event = DiscoveredEvent(
        source_id="s",
        external_id="e",
        title="Water Lantern Festival",
        starts_at=None,
        ends_at=None,
        place=None,
        url="https://example.org/e",
        summary=None,
    )
    return ScoredCandidate(event, embedding)


def test_a_clear_winner_is_still_named():
    ranker = _ranker(dancing=[1.0, 0.0], wine=[0.0, 1.0])

    score, matched = ranker.score(_candidate([1.0, 0.0]))

    assert matched == "dancing"
    assert score > 0.9


def test_a_near_tie_reports_no_interest_rather_than_a_wrong_one():
    # "Water Lantern Festival" was announced as matching Line Dancing at 0.616
    # while every other interest scored within a hair of it. The score is real;
    # the reason was not.
    ranker = _ranker(dancing=[1.0, 0.02], wine=[1.0, 0.0])

    score, matched = ranker.score(_candidate([1.0, 0.01]))

    assert matched is None
    # Still scored, so it can still be selected on merit.
    assert score > 0.5


def test_the_margin_is_what_decides_attribution():
    ranker = _ranker(a=[1.0, 0.0], b=[0.0, 1.0])
    scores = [
        ranker.score(_candidate([1.0, ratio / 100])) for ratio in range(0, 100, 10)
    ]
    # Every named result beat its runner-up by the stated margin; nothing is
    # named on a smaller gap.
    assert all(score >= MIN_ATTRIBUTION_MARGIN for score, name in scores if name)


# --- 2. an event that had already happened -----------------------------------


def test_the_date_a_publisher_put_in_its_own_url_is_read():
    assert date_from_url("https://x.org/event/2026-08-06-phillips-after-5") == date(
        2026, 8, 6
    )
    assert date_from_url("https://nvcwda.org/events/country-dance-august-01-2026") == (
        date(2026, 8, 1)
    )
    assert date_from_url("https://x.org/e/01-august-2026") == date(2026, 8, 1)
    assert date_from_url("https://x.org/events/2026/08/06/thing") == date(2026, 8, 6)


def test_a_url_without_a_date_states_none():
    assert date_from_url("https://x.org/events/summer-concert") is None
    assert date_from_url("https://x.org/e/2026-13-45") is None
    assert date_from_url(None) is None


def test_a_find_dated_before_today_by_its_url_has_passed():
    # The jazz evening announced two days after it happened.
    assert looks_past("https://x.org/event/2026-08-06-after-5", _TODAY) is True


def test_a_find_dated_today_survives():
    # An evening event is still ahead of someone reading in the morning, and a
    # slug carries no time of day to decide otherwise.
    assert looks_past("https://x.org/event/2026-08-08-tonight", _TODAY) is False


def test_a_month_is_only_past_once_every_day_in_it_is():
    assert looks_past("https://x.org/e/august-2026", _TODAY) is False
    assert looks_past("https://x.org/e/july-2026", _TODAY) is True


def test_an_undated_find_that_already_happened_is_not_selected():
    ranker = _ranker(dancing=[1.0, 0.0])
    passed = ScoredCandidate(
        DiscoveredEvent(
            source_id="s",
            external_id="e1",
            title="Phillips After 5",
            starts_at=None,
            ends_at=None,
            place=None,
            url="https://x.org/event/2026-08-06-phillips-after-5",
            summary=None,
        ),
        [1.0, 0.0],
    )
    upcoming = ScoredCandidate(
        DiscoveredEvent(
            source_id="s",
            external_id="e2",
            title="Phillips After 5",
            starts_at=None,
            ends_at=None,
            place=None,
            url="https://x.org/event/2026-08-20-phillips-after-5",
            summary=None,
        ),
        [1.0, 0.0],
    )

    ranked = ranker.rank((passed, upcoming), now=_NOW)

    assert [item.candidate.event.external_id for item in ranked] == ["e2"]


def test_a_dated_event_is_still_judged_on_its_real_start():
    # The URL fallback must not override a start the source actually stated.
    ranker = _ranker(dancing=[1.0, 0.0])
    stale_slug_future_event = ScoredCandidate(
        DiscoveredEvent(
            source_id="s",
            external_id="e1",
            title="Series Announced",
            starts_at=_NOW + timedelta(days=10),
            ends_at=None,
            place=None,
            url="https://x.org/posted/2026-01-01/next-season",
            summary=None,
        ),
        [1.0, 0.0],
    )

    ranked = ranker.rank((stale_slug_future_event,), now=_NOW)

    assert len(ranked) == 1


# --- 3. a listing page dressed as a happening --------------------------------


def test_a_lineup_is_a_calendar_under_another_name():
    assert looks_like_a_directory(
        "The Renegade VA - Lineup",
        "https://renegadeva.com/arlington-clarendon-the-renegade-va-lineup",
    )


def test_a_standing_programme_is_refused_on_its_url_not_its_name():
    # This one led a delivered digest. The decision is made on the path — a
    # county's standing arts programme — rather than on "Series" in the title,
    # because "Eventide Concert Series Opening Night" is a real night out and a
    # rule keyed on the word would throw it away with this.
    assert looks_like_a_directory(
        "Lubber Run Amphitheater – Free Concert Series - Arlington County",
        "https://www.arlingtonva.us/Government/Programs/Arts/Programs/Lubber-Run",
    )


def test_a_real_happening_with_series_in_its_name_survives():
    # The rules must not eat the thing they are meant to protect.
    assert not looks_like_a_directory(
        "Eventide Concert Series Opening Night", "https://sollys.com/event/eventide"
    )
    assert not looks_like_a_directory(
        "Lubber Run Amphitheater - Free Concert Series",
        "https://parks.arlingtonva.us/lubber-run",
    )
    assert not looks_like_a_directory(
        "Water Lantern Festival", "https://waterlanternfestival.com/e/dc-2026"
    )


# --- 4. a paragraph where a name should be -----------------------------------


def test_a_sentence_length_title_is_cut_at_the_sentence():
    title = clean_title(
        "Country Dance at Faith Lutheran Church in Arlington. Lessons: Love, "
        "JoAnn (LD), East Coast Swing with Ken"
    )

    assert title == "Country Dance at Faith Lutheran Church in Arlington."


def test_an_abbreviation_is_not_a_sentence_ending():
    assert clean_title("Dr. Dog at the Anthem") == "Dr. Dog at the Anthem"
    assert clean_title("Mt. Vernon Wine Fest") == "Mt. Vernon Wine Fest"


def test_an_ordinary_title_is_left_alone():
    assert clean_title("Water Lantern Festival") == "Water Lantern Festival"
    assert clean_title(None) is None


# --- 5. a time nobody published ----------------------------------------------


def _dated(title: str, starts_at: datetime) -> RankedCandidate:
    event = DiscoveredEvent(
        source_id="s",
        external_id="e",
        title=title,
        starts_at=starts_at,
        ends_at=None,
        place=None,
        url="https://example.org/e",
        summary=None,
    )
    return RankedCandidate(ScoredCandidate(event, None), 0.9, "concerts")


def test_a_date_with_no_time_is_never_given_one():
    # Sources overwhelmingly publish a bare date, which parses to midnight UTC.
    # Converting that into the reader's zone moved it to the previous evening
    # and printed a clock: a concert listed for Oct 3 was announced as "Fri Oct
    # 2, 8:00pm", directly under a title reading "Oct 03, 2026, 9:30 PM".
    message = render_message(
        (_dated("COLLECTIVE concert", datetime(2026, 10, 3, tzinfo=UTC)),),
        timezone="America/New_York",
    )

    assert message is not None
    assert "Sat Oct 3" in message
    # The day it was published for, and no invented clock.
    assert "Oct 2" not in message
    assert "8:00pm" not in message
    assert "12:00am" not in message


def test_a_real_start_time_is_still_shown_in_the_readers_zone():
    # The fix must not flatten times that were actually published: 12:00Z is
    # 08:00 in New York, and saying only "Aug 11" would lose the evening.
    message = render_message(
        (_dated("Jazz at the Green", datetime(2026, 8, 11, 12, 0, tzinfo=UTC)),),
        timezone="America/New_York",
        now=_NOW,
    )

    assert message is not None
    assert "8:00am" in message


def test_a_venue_calendar_is_not_a_happening():
    # "Old Town Alexandria Events" on a /calendar-of-events path reached a
    # delivered digest with an invented start time attached to it.
    assert looks_like_a_directory(
        "Old Town Alexandria Events - The Alexandrian | Marriott",
        "https://www.thealexandrian.com/hotel/calendar-of-events",
    )


# --- 6. a link a phone can actually open --------------------------------------


def test_a_url_is_cleaned_before_it_is_pasted_into_a_message():
    # A feed can bury whitespace or a control character in a URL; iMessage only
    # auto-links a URL that is whole and well-formed, so a raw paste with a
    # stray newline is dead text on a phone.
    assert (
        _clean_url("https://example.org/e?q=1\n")
        == "https://example.org/e?q=1"
    )
    assert _clean_url("https://exa\x00mple.org/e") == "https://example.org/e"
    assert _clean_url("  https://example.org/e  ") == "https://example.org/e"
    assert _clean_url("") is None
    assert _clean_url(None) is None


def test_the_cleaned_url_reaches_the_assembled_message():
    event = DiscoveredEvent(
        source_id="s",
        external_id="e",
        title="Garden Party",
        starts_at=datetime(2026, 8, 12, 18, 0, tzinfo=UTC),
        ends_at=None,
        place=None,
        url="https://example.org/garden\n",
        summary=None,
    )
    message = render_message(
        (RankedCandidate(ScoredCandidate(event, None), 0.9, "social"),),
        timezone="America/New_York",
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )
    assert message is not None
    assert "https://example.org/garden" in message
    assert "\nhttps://example.org/garden\n" not in message
