"""The forward earnings calendar: 8-K dates, no hindsight, a fixed predictor."""

from datetime import date
from unittest.mock import patch

from backend.market import earnings_calendar as ec

# One quarter's release dates on the 20th of January, April, July and October.
QUARTERLY = [
    date(2023, 1, 20),
    date(2023, 4, 20),
    date(2023, 7, 20),
    date(2023, 10, 20),
    date(2024, 1, 20),
    date(2024, 4, 20),
    date(2024, 7, 20),
    date(2024, 10, 20),
    date(2025, 1, 20),
    date(2025, 4, 20),
    date(2025, 7, 20),
    date(2025, 10, 20),
]


# The stored events frame keeps only 8-K item 2.02, not other items or forms.
def test_release_dates_filters_the_earnings_item():
    columns = {
        "filed": ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
        "items": ["2.02,9.01", "1.01", "12.02", "2.02"],
        "form": ["8-K", "8-K", "8-K", "10-Q"],
    }
    assert ec.release_dates(columns) == [date(2026, 1, 5)]


# The next release is the same fiscal quarter last year, shifted one year.
def test_same_quarter_predicts_the_next_release():
    prediction = ec.predict(QUARTERLY, date(2025, 10, 21))
    assert prediction is not None
    assert prediction["predicted"] == "2026-01-20"
    assert prediction["method"] == "same_quarter"
    assert prediction["confidence"] == "high"
    assert prediction["years"] == 3
    assert not prediction["overdue"]


# Only releases filed on or before the as-of date are read: adding later
# filings leaves the prediction for an earlier date unchanged.
def test_prediction_reads_only_releases_filed_by_asof():
    asof = date(2025, 10, 21)
    before = ec.predict(QUARTERLY, asof)
    later = QUARTERLY + [
        date(2026, 1, 20),
        date(2026, 4, 20),
        date(2026, 7, 20),
        date(2026, 10, 20),
    ]
    after = ec.predict(later, asof)
    assert before == after


# A name with fewer than five releases has no prediction.
def test_predict_requires_five_releases():
    assert ec.predict(QUARTERLY[:4], date(2025, 10, 21)) is None


# A prediction whose date has passed is reported as overdue, not silently moved.
def test_predict_marks_overdue():
    prediction = ec.predict(QUARTERLY, date(2026, 2, 1))
    assert prediction is not None
    assert prediction["predicted"] == "2026-01-20"
    assert prediction["overdue"]


# The confidence falls with the spread of the candidates. `predict` shifts the
# candidates to the target year before grading them, so the dates here share it.
def test_confidence_uses_the_candidate_spread():
    tight = [date(2026, 1, 20), date(2026, 1, 22), date(2026, 1, 19)]
    wide = [date(2026, 1, 20), date(2026, 2, 5)]
    single = [date(2026, 1, 20)]
    assert ec.confidence(tight, "same_quarter") == "high"
    assert ec.confidence(wide, "same_quarter") == "medium"
    assert ec.confidence(single, "same_quarter") == "low"
    assert ec.confidence(tight, "interval") == "low"


# Without a prior-year match the median interval between recent releases is
# the fallback, and it ignores a gap that is not a quarter.
def test_interval_fallback_uses_quarterly_gaps():
    dates = [
        date(2024, 1, 1),
        date(2024, 4, 1),
        date(2024, 7, 1),
        date(2024, 10, 1),
        date(2025, 1, 1),
    ]
    # Gaps 91, 91, 92, 92: the median is 91.5 and rounds to 92.
    assert ec.interval_days(dates, len(dates) - 1) == 92
    # A long gap outside the quarterly band is dropped rather than averaged in.
    irregular = [date(2024, 1, 1), date(2024, 4, 1), date(2025, 3, 1)]
    assert ec.interval_days(irregular, len(irregular) - 1) == 91
    with patch.object(ec, "same_quarter_candidates", return_value=[]):
        prediction = ec.predict(dates, date(2025, 1, 2))
    assert prediction is not None
    assert prediction["method"] == "interval"
    assert prediction["predicted"] == "2025-04-03"
    assert prediction["confidence"] == "low"


# The session count is signed: a passed date is negative, a future date positive.
def test_sessions_until_is_signed():
    asof = date(2026, 10, 30)
    assert ec.sessions_until(asof, date(2026, 11, 2)) == 1
    assert ec.sessions_until(asof, date(2026, 10, 29)) == -1
    assert ec.sessions_until(asof, asof) == 0


# Each usable release opens an interval that runs to the next release, and the
# prediction is the one made at that release.
def test_intervals_start_at_the_fifth_release():
    out = ec.intervals(QUARTERLY)
    assert len(out) == len(QUARTERLY) - ec.MIN_RELEASES + 1
    assert out[0] == (date(2024, 1, 20), date(2024, 4, 20), date(2024, 4, 20))
    assert out[-1][0] == date(2025, 10, 20)
    assert out[-1][1] is None


# A later release cannot change an interval that ended before it: the history
# is read as of the release that opened the interval.
def test_intervals_are_point_in_time():
    before = ec.intervals(QUARTERLY)
    later = QUARTERLY + [date(2026, 1, 20), date(2026, 4, 20)]
    after = ec.intervals(later)
    assert after[: len(before) - 1] == before[: len(before) - 1]
    assert after[len(before) - 1] == (
        date(2025, 10, 20), date(2026, 1, 20), date(2026, 1, 20)
    )


# The flag window includes the predicted session, the window before it and the
# overdue tail, and excludes a None distance.
def test_pre_release_window_boundaries():
    assert ec.pre_release(5, 5, 20)
    assert not ec.pre_release(6, 5, 20)
    assert ec.pre_release(0, 5, 20)
    assert ec.pre_release(-20, 5, 20)
    assert not ec.pre_release(-21, 5, 20)
    assert not ec.pre_release(None, 5, 20)


# One name's row carries the last release and the next prediction together.
def test_calendar_row_carries_the_history_and_prediction():
    columns = {
        "filed": [day.isoformat() for day in QUARTERLY],
        "items": ["2.02"] * len(QUARTERLY),
        "form": ["8-K"] * len(QUARTERLY),
    }
    row = ec.calendar_row("XXX", columns, date(2025, 10, 21))
    assert row is not None
    assert row["ticker"] == "XXX"
    assert row["last_release"] == "2025-10-20"
    assert row["predicted"] == "2026-01-20"
