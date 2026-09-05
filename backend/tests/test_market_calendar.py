"""The event calendar: distances and windows around decisions, per session."""

from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market import calendar
from backend.market.panel import panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory


# A weekday-only flat history.
def _history(ticker: str, first: date, sessions: int) -> TickerHistory:
    bars = []
    day = first
    while len(bars) < sessions:
        if day.weekday() < 5:
            bars.append(DailyBar(day, 100, 100, 100, 100, 100, 1_000_000))
        day += timedelta(days=1)
    return TickerHistory(
        ticker, tuple(bars), (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# Distances count sessions, a Sunday action lands on the next session, the
# windows are flagged, and far-away counts are capped.
def test_calendar_distances_and_windows():
    first = date(2025, 6, 2)  # a Monday
    panel = panel_from_histories(
        {"AAA": _history("AAA", first, 40), "SPY": _history("SPY", first, 40)},
        "SPY",
        {},
    )
    dates = list(panel.dates.astype("datetime64[D]").astype(object))
    decision = date(2025, 6, 18)  # a Wednesday
    sunday = date(2025, 7, 13)  # lands on Monday 07-14
    feats = calendar.calendar_by_session(panel, [decision, sunday])
    names = calendar.CALENDAR_NAMES
    t = dates.index(decision)
    assert feats[t, names.index("sessions_to_fomc")] == 0
    assert feats[t, names.index("fomc_decision_day")] == 1.0
    assert feats[t - 1, names.index("sessions_to_fomc")] == 1
    assert feats[t - 3, names.index("fomc_pre_window")] == 1.0
    assert feats[t - 4, names.index("fomc_pre_window")] == 0.0
    assert feats[t + 2, names.index("sessions_since_fomc")] == 2
    assert feats[t + 2, names.index("fomc_post_window")] == 1.0
    assert feats[t + 4, names.index("fomc_post_window")] == 0.0
    monday = dates.index(date(2025, 7, 14))
    assert feats[monday, names.index("fomc_decision_day")] == 1.0
    assert feats[0, names.index("sessions_since_fomc")] == calendar.FAR
    per_name = calendar.calendar_features(panel, [decision, sunday])
    assert per_name.shape == (len(dates), 2, calendar.CALENDAR_COUNT)
    assert np.array_equal(per_name[:, 0], per_name[:, 1])


# The committed file parses and covers the period.
def test_committed_decisions_cover_2015_to_2026():
    decisions = calendar.fomc_decisions()
    assert decisions[0].year == 2015
    assert any(d.year == 2026 for d in decisions)
    assert len(decisions) >= 90
