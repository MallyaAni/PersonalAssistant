"""The confirmed dip-buy study's building blocks.

What has to hold: a trailing sum is the sum of the last k returns and
nothing earlier; a rolling low is the low of the window; a name's peer
return excludes itself; and an event is only an event when the low of
the fall holds through every confirmation session, with entry at the
close of the last of them.
"""

import numpy as np
import pytest

from backend.cli import market_dip as dip
from backend.market.panel import Panel


# The trailing sum over k sessions is exactly that, NaN before it fills.
def test_trailing_sum_is_the_last_k_returns():
    r = np.array([[0.1], [0.2], [0.3], [0.4]])
    out = dip._trailing(r, 2)
    assert np.isnan(out[0, 0])
    assert np.isclose(out[1, 0], 0.3)
    assert np.isclose(out[3, 0], 0.7)


# A rolling low over k sessions is the minimum of the window, inclusive.
def test_rolling_low_is_the_windows_minimum():
    v = np.array([[5.0], [3.0], [4.0], [6.0]])
    out = dip._rolling(v, 2, largest=False)
    assert np.isnan(out[0, 0])
    assert out[1, 0] == 3.0
    assert out[2, 0] == 3.0
    assert out[3, 0] == 4.0


# A name's peer return is its sector's mean without itself; a name with
# no sector of five or more reads the universe's mean.
def test_peer_return_excludes_the_name_itself():
    tickers = ("A", "B", "C", "D", "E", "F", "Z", "SPY")
    sector = {t: "tech" for t in "ABCDEF"}
    sector["Z"] = "lonely"
    logr = np.zeros((1, 8))
    logr[0, :6] = [0.1, 0.1, 0.1, 0.1, 0.1, -0.5]  # F fell, its peers did not
    logr[0, 6] = 0.2
    panel = Panel(
        dates=np.array(["2026-01-05"], dtype="datetime64[D]"),
        tickers=tickers,
        open=np.ones((1, 8)),
        high=np.ones((1, 8)),
        low=np.ones((1, 8)),
        close=np.ones((1, 8)),
        adj_close=np.ones((1, 8)),
        volume=np.ones((1, 8)),
        themes={},
        benchmark="SPY",
    )
    peers = dip._peer_returns(panel, sector, logr)
    assert np.isclose(peers[0, 5], 0.1)  # F's peers, without F
    assert np.isclose(peers[0, 0], (0.4 - 0.5) / 5)  # A's peers include F's fall
    assert np.isclose(peers[0, 6], np.mean(logr[0, :7]))  # Z: the universe


# An event needs the fall, then the low held through every confirmation
# session; entry is the close of the last one, and the label starts there.
@pytest.mark.parametrize(
    ("path_after", "expected_events"),
    [
        ([100.0, 101.0], 1),  # both confirmation closes hold the low of 90
        ([89.0, 101.0], 0),  # the first breaks it
        ([100.0, 88.0], 0),  # the second breaks it
    ],
)
def test_an_event_needs_the_low_to_hold(path_after, expected_events):
    rows = 300
    close = np.full((rows, 2), 100.0)
    close[:, 1] = 100.0  # the benchmark never moves
    t = 270
    close[t, 0] = 90.0  # a ten-percent fall in one session
    close[t + 1, 0], close[t + 2, 0] = path_after
    low = close.copy()
    low[t, 0] = 90.0
    high = close + 1.0
    panel = Panel(
        dates=np.datetime64("2025-01-01") + np.arange(rows).astype("timedelta64[D]"),
        tickers=("AAA", "SPY"),
        open=close,
        high=high,
        low=low,
        close=close,
        adj_close=close,
        volume=np.ones((rows, 2)),
        themes={},
        benchmark="SPY",
    )
    events = dip._events(panel, {"AAA": ""}, None, drop=0.08, window=3, confirm=2)
    # A broken low is a deeper fall, which earns its own confirmation later;
    # what must not happen is an entry at the original confirmation close.
    at_original = [e for e in events if e[0] == t + 2]
    assert len(at_original) == expected_events
    if at_original:
        entry, column, feats, labels = at_original[0]
        assert column == 0
        assert feats[0] < np.log(0.92)  # own_fall
        assert np.isclose(feats[2], np.log(close[t + 2, 0] / 90.0))  # held_low
        assert np.isnan(feats[-1])  # no tone rank was given
