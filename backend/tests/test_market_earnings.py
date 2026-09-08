"""The earnings-into-slope study's date logic.

What has to hold: a results release accepted after the open reacts on
the next session and one accepted before it on its own session; forms
without item 2.02 are not reports; and the distances to the next report
and from the last are counted in sessions, infinite where there is none.
"""

from datetime import date

import numpy as np

from backend.cli.market_earnings import reaction_sessions, report_distances

DATES = [
    date(2026, 9, 1),
    date(2026, 9, 2),
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 8),
]


def test_after_the_open_reacts_next_session_and_before_it_the_same_day():
    events = {
        "accepted": [
            "2026-09-02T20:13:19+00:00",  # 16:13 ET, after the close
            "2026-09-04T11:05:00+00:00",  # 07:05 ET, before the open
            "2026-09-03T14:00:00+00:00",  # not a results release
        ],
        "filed": [date(2026, 9, 2), date(2026, 9, 4), date(2026, 9, 3)],
        "items": ["2.02,9.01", "2.02", "8.01"],
    }
    assert reaction_sessions(DATES, events) == [2, 3]


def test_a_report_on_a_holiday_reacts_on_the_next_session_in_the_panel():
    events = {
        "accepted": ["2026-09-05T12:00:00+00:00"],
        "filed": [date(2026, 9, 5)],
        "items": ["2.02"],
    }
    assert reaction_sessions(DATES, events) == [4]


def test_distances_are_in_sessions_and_infinite_without_a_report():
    until, since = report_distances(5, [2])
    assert until.tolist() == [2.0, 1.0, 0.0, np.inf, np.inf]
    assert since.tolist() == [np.inf, np.inf, 0.0, 1.0, 2.0]
    until, since = report_distances(3, [])
    assert np.isinf(until).all()
    assert np.isinf(since).all()
