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


def test_an_upcoming_stated_date_dates_the_find():
    keep, starts_at = apply_described_dates(None, _readable(date(2026, 8, 23)), TODAY)
    assert keep is True
    assert starts_at == datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


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
