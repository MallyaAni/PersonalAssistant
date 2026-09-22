"""Behavioral coverage of calendar completeness and archived-grade availability."""

from datetime import date, datetime, time, timedelta

import pytest

from backend.market.intraday_comparison import DailyRow
from backend.market.intraday_inputs import (
    RecordedEligibility,
    load_calendar,
    prior_daily,
    recorded_eligibility,
)


# Full holidays do not count toward horizons; early closes do.
def test_calendar_counts_exchange_sessions_and_bounds_coverage():
    calendar = load_calendar()
    assert calendar.offset(date(2025, 1, 8), 1) == date(2025, 1, 10)
    assert calendar.close_time(date(2026, 11, 27)) == time(13)
    assert calendar.offset(date(2026, 11, 25), 1) == date(2026, 11, 27)
    assert calendar.offset(date(2026, 9, 8), 20) == date(2026, 10, 6)
    with pytest.raises(ValueError, match="coverage"):
        calendar.offset(date(2019, 1, 2), -1)
    with pytest.raises(ValueError, match="trading session"):
        calendar.offset(date(2025, 1, 9), 1)


# A calendar range includes early closes but excludes holidays and weekends.
def test_calendar_range_is_explicit():
    calendar = load_calendar()
    assert calendar.sessions(date(2026, 11, 25), date(2026, 11, 30)) == {
        date(2026, 11, 25): time(16),
        date(2026, 11, 27): time(13),
        date(2026, 11, 30): time(16),
    }
    with pytest.raises(ValueError, match="coverage"):
        calendar.sessions(date(2028, 12, 29), date(2029, 1, 2))


# Construct twenty valid consecutive prior daily prices using exchange sessions.
def _history(session):
    calendar = load_calendar()
    return [
        DailyRow(calendar.offset(session, -n), 100 + n, 90 + n) for n in range(1, 21)
    ]


# Missing recent history cannot be replaced by an older available observation.
@pytest.mark.parametrize("missing", [0, 9, 19])
def test_daily_gaps_cannot_roll_the_window_back(missing):
    session = date(2026, 9, 15)
    rows = _history(session)
    rows.pop(missing)
    rows.append(DailyRow(load_calendar().offset(session, -21), 80, 70))
    with pytest.raises(ValueError, match="missing or duplicate"):
        prior_daily(rows, session, load_calendar())


# Same-day and future poison cannot remove valid earlier daily observations.
def test_daily_context_ignores_unseen_rows_but_rejects_observed_defects():
    session = date(2026, 9, 15)
    rows = _history(session)
    expected = prior_daily(rows, session, load_calendar())
    rows.extend(
        [
            DailyRow(session, float("nan"), -1),
            DailyRow(session + timedelta(days=1), 0, 0),
        ]
    )
    assert prior_daily(rows, session, load_calendar()) == expected
    with pytest.raises(ValueError, match="duplicate"):
        prior_daily(rows + [rows[0]], session, load_calendar())
    rows[0] = DailyRow(rows[0].date, 100, float("nan"))
    with pytest.raises(ValueError, match="invalid prior"):
        prior_daily(rows, session, load_calendar())


# Publication after the opening bars is not backdated to the record's label.
def test_late_record_is_not_available_early_and_previous_record_has_expired():
    records = [
        RecordedEligibility(date(2026, 9, 11), datetime(2026, 9, 12, 2), "A", False),
        RecordedEligibility(
            date(2026, 9, 14), datetime(2026, 9, 15, 10, 18, 21), "A+", False
        ),
    ]
    calendar = load_calendar()
    early = recorded_eligibility(records, datetime(2026, 9, 15, 10, 15), calendar)
    assert early.grade is None
    published = recorded_eligibility(records, datetime(2026, 9, 15, 10, 30), calendar)
    assert published.grade == "A+"
    assert published.grade_available_at.minute == 18
    assert (
        recorded_eligibility(records, datetime(2026, 9, 16, 10), calendar).grade is None
    )


# A missing field in a newer record must not fall back to an earlier good grade.
def test_missing_replacement_record_blocks_without_fallback():
    records = [
        RecordedEligibility(date(2026, 9, 14), datetime(2026, 9, 14, 18), "A", False),
        RecordedEligibility(date(2026, 9, 14), datetime(2026, 9, 15, 10), None, None),
    ]
    result = recorded_eligibility(
        records, datetime(2026, 9, 15, 10, 15), load_calendar()
    )
    assert result.grade is None
    assert result.rejecting_band is None


# Freshness uses trading dates across a long weekend rather than elapsed weekdays.
def test_long_weekend_preserves_previous_session_grade():
    record = RecordedEligibility(
        date(2026, 9, 4), datetime(2026, 9, 7, 19, 45), "A", False
    )
    result = recorded_eligibility(
        [record], datetime(2026, 9, 8, 9, 45), load_calendar()
    )
    assert result.grade == "A"


# Impossible early daily publications and conflicting same-time records stay blocked.
def test_impossible_daily_publication_and_ambiguous_records():
    record = RecordedEligibility(
        date(2026, 9, 15), datetime(2026, 9, 15, 9), "A", False
    )
    assert (
        recorded_eligibility([record], datetime(2026, 9, 15, 10), load_calendar()).grade
        is None
    )
    with pytest.raises(ValueError, match="ambiguous"):
        recorded_eligibility(
            [record, record], datetime(2026, 9, 15, 10), load_calendar()
        )
