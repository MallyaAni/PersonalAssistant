"""Sizing and exits on a model's score.

What has to hold: a session's entries are its top fraction by score and
their weights sum to one over the hold whatever the sizing rule; the
edge-over-volatility rule gives the calmer name more; a trailing stop
leaves on the first close the given fraction under the running peak and
a hold leaves at the horizon; the edge-decay exit leaves when the
re-scored probability drops under one half; and the book charges the
cost on the way in and out.
"""

import numpy as np

from backend.cli import market_position as pos


# Entries are the top fraction, weights sum to 1 / hold, and volatility
# scaling favours the calmer name.
def test_entries_are_the_top_fraction_and_sum_to_the_budget():
    scores = np.full((1, 40), np.nan)
    scores[0] = np.linspace(0.3, 0.7, 40)
    vol = np.full((1, 40), 0.3)
    vol[0, 39] = 0.6  # the highest-scored name is twice as volatile
    equal = pos._entries(scores, vol, top=0.1, hold=20, sizing="equal")
    assert len(equal) == 4
    assert {c for _, c, _ in equal} == {36, 37, 38, 39}
    assert np.isclose(sum(w for _, _, w in equal), 1 / 20)
    scaled = pos._entries(scores, vol, top=0.1, hold=20, sizing="edge over volatility")
    weight = {c: w for _, c, w in scaled}
    assert weight[38] > weight[39]  # the calmer name gets more
    assert np.isclose(sum(weight.values()), 1 / 20)


# A trailing stop leaves at the first close the fraction under the peak;
# a plain hold leaves at the horizon; edge decay leaves on the re-score.
def test_exit_rules_leave_when_they_say():
    close = np.array([[100.0], [110.0], [104.0], [96.0], [120.0], [130.0], [100.0]])
    scores = np.full(close.shape, 0.7)
    assert pos._exit_session(close, scores, 0, 0, 5, "hold", None) == 5
    assert (
        pos._exit_session(close, scores, 0, 0, 5, "hold", 0.10) == 3
    )  # 96 < 110 * 0.9
    assert pos._exit_session(close, scores, 0, 0, 5, "hold", 0.20) == 5  # never 20% off
    scores[2, 0] = 0.4  # the model turns on session 2
    assert pos._exit_session(close, scores, 0, 0, 5, "edge decay", None) == 2
    assert pos._exit_session(close, scores, 0, 0, 5, "edge decay", 0.05) == 2
    # A hold past the end of history stops at the last session.
    assert (
        pos._exit_session(close, np.full(close.shape, 0.7), 4, 0, 20, "hold", None) == 6
    )


# The book's daily return is the weighted path less cost at entry and exit.
def test_book_charges_cost_both_ways():
    close = np.array([[100.0], [110.0], [121.0], [121.0]])
    simple = np.array([[np.nan], [0.10], [0.10], [0.0]])
    scores = np.full(close.shape, 0.7)
    daily, trades = pos._book(
        [(0, 0, 0.5)], close, simple, scores, 2, "hold", None, 10.0
    )
    assert np.isclose(daily[1], 0.5 * 0.10 - 0.5 * 0.001)
    assert np.isclose(daily[2], 0.5 * 0.10 - 0.5 * 0.001)
    assert daily[3] == 0.0
    assert np.isclose(trades[0], 1.21 - 1 - 0.002)
