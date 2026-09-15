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
    # Options expiry: the third Friday of June 2025 is the 20th, a quad
    # witching month; the Russell reconstitution is the fourth Friday.
    opex = dates.index(date(2025, 6, 20))
    assert feats[opex, names.index("opex_day")] == 1.0
    assert feats[opex, names.index("quad_witching")] == 1.0
    assert feats[opex - 1, names.index("opex_day")] == 0.0
    assert feats[opex - 4, names.index("opex_week")] == 1.0  # Monday of that week
    assert feats[opex - 5, names.index("opex_week")] == 0.0
    assert (
        feats[dates.index(date(2025, 6, 27)), names.index("russell_reconstitution")]
        == 1.0
    )
    # Turn of the month: June's last session and July's first three.
    assert feats[dates.index(date(2025, 6, 30)), names.index("turn_of_month")] == 1.0
    assert feats[dates.index(date(2025, 6, 27)), names.index("turn_of_month")] == 0.0
    assert feats[dates.index(date(2025, 7, 3)), names.index("turn_of_month")] == 1.0
    assert feats[dates.index(date(2025, 7, 8)), names.index("turn_of_month")] == 0.0
    assert (
        feats[dates.index(date(2025, 6, 27)), names.index("month_end_sessions")] == 1.0
    )
    assert feats[dates.index(date(2025, 7, 15)), names.index("january")] == 0.0
    per_name = calendar.calendar_features(panel, [decision, sunday])
    assert per_name.shape == (len(dates), 2, calendar.CALENDAR_COUNT)
    assert np.array_equal(per_name[:, 0], per_name[:, 1])


# The committed file parses and covers the period, and reaches the FOMC
# gate's horizon: six completed meetings from 2026-09-16 need the 2027
# schedule, or the policy pauses for an unknown calendar in January.
def test_committed_decisions_cover_2015_to_2027():
    decisions = calendar.fomc_decisions()
    assert decisions[0].year == 2015
    assert any(d.year == 2026 for d in decisions)
    assert len(decisions) >= 90
    later = [d for d in decisions if d >= date(2026, 9, 16)]
    assert len(later) >= 6
    assert date(2027, 6, 9) in decisions
    assert date(2027, 12, 8) in decisions


# A decision whose date falls after the panel's last session is still a
# meeting the desk can see: the sessions before it read their distance to
# it and their pre-window flag, instead of "none within 30 sessions". The
# clipped version made the week before an upcoming meeting invisible.
def test_an_upcoming_meeting_beyond_the_panel_still_flags_the_pre_window():
    first = date(2026, 9, 8)  # Tuesday after Labor Day
    panel = panel_from_histories(
        {"AAA": _history("AAA", first, 4), "SPY": _history("SPY", first, 4)},
        "SPY",
        {},
    )
    dates = list(panel.dates.astype("datetime64[D]").astype(object))
    upcoming = date(2026, 9, 16)  # past the panel's last session
    feats = calendar.calendar_by_session(panel, [upcoming])
    names = calendar.CALENDAR_NAMES
    last = len(dates) - 1
    assert feats[last, names.index("sessions_to_fomc")] == 3
    assert feats[last, names.index("fomc_pre_window")] == 1.0
    assert feats[last - 1, names.index("fomc_pre_window")] == 0.0
    # No session is itself the future decision day.
    assert feats[:, names.index("fomc_decision_day")].sum() == 0


# A distant future meeting must not create a pre-meeting window at the panel boundary.
def test_a_distant_future_meeting_does_not_trigger_the_pre_window():
    dates = np.asarray(
        ["2026-09-09", "2026-09-10", "2026-09-11"], dtype="datetime64[D]"
    )
    near, _ = calendar._fomc_distances(dates, [date(2026, 9, 16)])
    far, _ = calendar._fomc_distances(dates, [date(2026, 12, 16)])
    np.testing.assert_array_equal(near, [5, 4, 3])
    np.testing.assert_array_equal(far, [30, 30, 30])


# Full exchange holidays are skipped, while an early-close session is still counted.
def test_future_distance_uses_exchange_holidays():
    dates = np.asarray(["2026-11-25"], dtype="datetime64[D]")
    distance, _ = calendar._fomc_distances(dates, [date(2026, 11, 30)])
    assert distance[0] == 2  # Friday's early close and Monday, not Thanksgiving.
    dates = np.asarray(["2026-04-02"], dtype="datetime64[D]")
    distance, _ = calendar._fomc_distances(dates, [date(2026, 4, 5)])
    assert distance[0] == 1  # Good Friday closed, Sunday action reacts Monday.


# Unknown coverage stays unknown; an earlier decision cannot become today's event.
def test_calendar_boundaries_do_not_invent_decision_days():
    dates = np.asarray(["2029-01-02"], dtype="datetime64[D]")
    distance, since = calendar._fomc_distances(
        dates, [date(2029, 1, 1), date(2029, 1, 31)]
    )
    assert np.isnan(distance[0])
    assert np.isnan(since[0])
