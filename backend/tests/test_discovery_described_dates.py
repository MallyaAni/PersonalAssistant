"""What a transcribed date does to a find: the arithmetic stays in code.

An audit judged five selected web finds and none had an established date, so
the past-event guard had nothing to act on and a county fair was sent five
days after it ended. The describer now transcribes the page's stated dates;
this decides what they mean - a find whose last stated day is behind today is
dropped, and an undated find with a stated start becomes dated, competing as
dated instead of riding the undated allowance.
"""

from datetime import UTC, date, datetime

from backend.agents.scout.describing import Readable
from backend.discovery.runner import apply_described_dates

TODAY = date(2026, 8, 21)


def _readable(starts=None, ends=None) -> Readable:
    return Readable(title="t", description="d", starts_on=starts, ends_on=ends)


# The county fair case: a multi-day event whose last day is behind today.
def test_an_event_whose_stated_end_has_passed_is_dropped():
    keep, _ = apply_described_dates(
        None, _readable(date(2026, 8, 12), date(2026, 8, 16)), TODAY
    )
    assert keep is False


def test_a_single_stated_day_in_the_past_is_dropped():
    keep, _ = apply_described_dates(None, _readable(date(2026, 8, 15)), TODAY)
    assert keep is False


# Midnight UTC exactly, because that is the pipeline's one convention for a
# date with no stated time - _format_when renders it as a bare date, and any
# other clock gets shifted into the reader's zone and printed as a start
# nobody published ("at 8:00am", in two real digests, from a noon stamp).
def test_an_upcoming_stated_date_dates_the_find_as_date_only():
    keep, starts_at = apply_described_dates(None, _readable(date(2026, 8, 23)), TODAY)
    assert keep is True
    assert starts_at == datetime(2026, 8, 23, 0, 0, tzinfo=UTC)


# Today's event is still on: an end date equal to today has not passed.
def test_an_event_ending_today_survives():
    keep, _ = apply_described_dates(
        None, _readable(date(2026, 8, 19), date(2026, 8, 21)), TODAY
    )
    assert keep is True


def test_a_dateless_find_is_kept_and_stays_undated():
    keep, starts_at = apply_described_dates(None, _readable(), TODAY)
    assert keep is True
    assert starts_at is None


# A source that already published a real start keeps it; the transcription
# never overrides structured data.
def test_a_real_start_is_never_overridden():
    published = datetime(2026, 8, 25, 19, 30, tzinfo=UTC)
    keep, starts_at = apply_described_dates(
        published, _readable(date(2026, 8, 26)), TODAY
    )
    assert keep is True
    assert starts_at == published


# The all-day convention's comparisons. Midnight UTC means "the source stated
# a day", and a day is live until it ends: an event happening tonight was
# dropped from a real digest at 4pm because midnight had passed. These pin
# both comparison sites - ranking's lead-time window and delivery's pastness
# check - against treating the day's start as the event's end.
def test_a_date_only_event_is_schedulable_all_day():
    from backend.discovery.relevance import within_lead_time

    day = datetime(2026, 8, 21, 0, 0, tzinfo=UTC)
    late_that_day = datetime(2026, 8, 21, 20, 15, tzinfo=UTC)
    assert within_lead_time(day, late_that_day) is True
    assert within_lead_time(day, datetime(2026, 8, 22, 0, 0, tzinfo=UTC)) is False


def test_a_timed_event_still_needs_its_lead_time():
    from backend.discovery.relevance import within_lead_time

    soon = datetime(2026, 8, 21, 21, 30, tzinfo=UTC)
    assert within_lead_time(soon, datetime(2026, 8, 21, 21, 0, tzinfo=UTC)) is False


def test_delivery_keeps_a_date_only_event_until_its_day_ends():
    from backend.discovery.digest import _has_passed
    from backend.discovery.events import DiscoveredEvent
    from backend.discovery.relevance import RankedCandidate, ScoredCandidate

    def _item(starts_at):
        event = DiscoveredEvent(
            source_id="s",
            external_id="x",
            title="t",
            starts_at=starts_at,
            ends_at=None,
            place=None,
            url=None,
            summary=None,
        )
        return RankedCandidate(ScoredCandidate(event, None), 1.0, None)

    day = datetime(2026, 8, 21, 0, 0, tzinfo=UTC)
    afternoon = datetime(2026, 8, 21, 20, 15, tzinfo=UTC)
    assert _has_passed(_item(day), afternoon) is False
    assert _has_passed(_item(day), datetime(2026, 8, 22, 0, 0, tzinfo=UTC)) is True
    timed = datetime(2026, 8, 21, 19, 0, tzinfo=UTC)
    assert _has_passed(_item(timed), afternoon) is True
