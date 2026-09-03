"""The words of an events question decide its calendar window, in code."""
from datetime import UTC, date, datetime

from backend.core.event_window import window_for

WED = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)  # a Wednesday evening
FRI = datetime(2026, 9, 4, 21, 0, tzinfo=UTC)
SUN = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)


def test_this_week_runs_to_sunday():
    window = window_for("what are the most fun events happening in the area this week?", WED)
    assert (window.start, window.end, window.label) == (date(2026, 9, 2), date(2026, 9, 6), "this week")
    assert window.holds(date(2026, 9, 5)) and not window.holds(date(2026, 9, 13))


def test_this_weekend_is_friday_to_sunday_and_from_friday_the_one_under_way():
    assert (window_for("what's on this weekend?", WED).start, window_for("what's on this weekend?", WED).end) == (date(2026, 9, 4), date(2026, 9, 6))
    friday = window_for("anything good this weekend", FRI)
    assert (friday.start, friday.end) == (date(2026, 9, 4), date(2026, 9, 6))
    sunday = window_for("weekend plans?", SUN)
    assert (sunday.start, sunday.end) == (date(2026, 9, 6), date(2026, 9, 6))


def test_today_tomorrow_next_week_and_next_weekend():
    assert window_for("anything fun tonight?", WED).label == "today"
    assert window_for("what's on tomorrow", WED).start == date(2026, 9, 3)
    nxt = window_for("events next week", WED)
    assert (nxt.start, nxt.end) == (date(2026, 9, 7), date(2026, 9, 13))
    nxtw = window_for("what's on next weekend", WED)
    assert (nxtw.start, nxtw.end) == (date(2026, 9, 11), date(2026, 9, 13))


def test_no_time_words_means_no_window():
    assert window_for("what jazz nights are there in Arlington?", WED) is None
