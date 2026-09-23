"""The `vol_trend` trend ceiling with hysteresis, on real price histories.

A single close crossing the 200-session mean used to flip the broad trend
ceiling 1 -> 0.5 -> 0 and back, so a benchmark oscillating around its mean
whipsawed the whole book. The ceiling now reads each benchmark with bands: a
benchmark counts as below trend only once its close is more than 3% under
its 200-session mean, and as above again only once it is more than 2% over
it; between the bands the most recent decided state holds, found by scanning
back through the prices at or before the decision index. These tests drive
`_trend_ceiling` and the full `decide` with constructed histories and assert
on the ceiling and the decision that came back, including that appending
future rows never changes an earlier read.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import allocation
from backend.agents.trading.desk.allocation import (
    QQQ,
    SPY,
    TREND_WINDOW,
    _trend_ceiling,
    decide,
)

BASE = date(2020, 1, 1)


# Consecutive session dates for a decision horizon.
def _dates(n: int) -> np.ndarray:
    """Return `n` consecutive datetime64[D] session dates from BASE."""
    return np.array([BASE + timedelta(days=i) for i in range(n)], dtype="datetime64[D]")


# A benchmark that sat flat at 100 for a full trend window and then walks the
# given closes, so each later close's ratio to its 200-session mean is, to
# within a few hundredths of a percent, the close's own distance from 100.
def _path(*closes: float) -> np.ndarray:
    """Return a price series: TREND_WINDOW flat closes at 100, then `closes`."""
    return np.concatenate([np.full(TREND_WINDOW, 100.0), np.array(closes, float)])


# The ceiling read at every session from the first complete window on.
def _ceilings(spy: np.ndarray, qqq: np.ndarray) -> list[float]:
    """Return the trend ceiling at each t in [TREND_WINDOW - 1, len)."""
    return [_trend_ceiling(spy, qqq, t) for t in range(TREND_WINDOW - 1, len(spy))]


# A close under the mean but inside the 3% band does not turn a benchmark
# that was above trend into one below it; only a close more than 3% under
# does. Coming back, a close over the mean inside the 2% band does not turn
# it above again; only a close more than 2% over does.
def test_the_bands_hold_the_last_decided_state():
    spy = _path(105.0, 99.0, 98.0, 97.5, 95.0, 101.0, 101.5, 103.0, 99.0)
    flat = np.full(len(spy), 100.0)
    flat_above = flat * np.linspace(1.0, 1.1, len(spy))  # QQQ above throughout
    ceilings = _ceilings(spy, flat_above)
    # t = 199 (flat), then the walk: +5% decides above; 99, 98 and 97.5 are
    # inside the lower band and hold above; 95 (-5%) decides below; 101 and
    # 101.5 are inside the upper band and hold below; 103 (+3%) decides
    # above; 99 holds above.
    assert ceilings == [
        0.5,  # the flat prefix: no decided state, SPY's close == mean is not above
        1.0,  # 105
        1.0,  # 99 holds
        1.0,  # 98 holds
        1.0,  # 97.5 holds
        0.5,  # 95 decides below
        0.5,  # 101 holds below
        0.5,  # 101.5 holds below
        1.0,  # 103 decides above
        1.0,  # 99 holds above
    ]


# The old rule: the same walk read without bands flips on every crossing of
# the mean, which is what the hysteresis exists to stop. This pins that the
# band reads differ from the raw comparison exactly on the in-band sessions.
def test_in_band_sessions_no_longer_flip_the_ceiling():
    spy = _path(105.0, 99.0, 105.0, 99.0, 105.0, 99.0)
    qqq = _path(105.0, 99.0, 105.0, 99.0, 105.0, 99.0)
    ceilings = _ceilings(spy, qqq)
    assert ceilings == [0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    raw = [
        float(spy[t] > spy[t - TREND_WINDOW + 1 : t + 1].mean())
        for t in range(TREND_WINDOW - 1, len(spy))
    ]
    assert raw == [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]


# Each benchmark is read on its own: SPY below and QQQ above is a half
# ceiling, and both below is zero.
def test_each_benchmark_contributes_half():
    below = _path(95.0, 99.0)
    above = _path(105.0, 101.0)
    assert _ceilings(below, above)[-1] == 0.5
    assert _ceilings(below, below)[-1] == 0.0
    assert _ceilings(above, above)[-1] == 1.0


# The read at t is a function of the rows through t only: appending future
# rows - including ones that would decide the other state - changes nothing.
def test_appending_future_rows_never_changes_an_earlier_read():
    spy = _path(105.0, 99.0, 98.0)
    qqq = _path(105.0, 101.0, 99.5)
    t = len(spy) - 1
    before = _trend_ceiling(spy, qqq, t)
    longer_spy = np.concatenate([spy, [90.0, 90.0, 90.0]])
    longer_qqq = np.concatenate([qqq, [90.0, 90.0, 90.0]])
    assert _trend_ceiling(longer_spy, longer_qqq, t) == before
    # And a history that later recovers reads the same at the earlier t.
    later_spy = np.concatenate([spy, [110.0, 110.0]])
    later_qqq = np.concatenate([qqq, [110.0, 110.0]])
    assert _trend_ceiling(later_spy, later_qqq, t) == before


# A gap in a benchmark's history is not carried across: the scan back for
# the last decided state stops at the first incomplete window, and the plain
# comparison at t decides when nothing in the contiguous run has left the
# bands. The window at t itself must be complete or the read is unusable.
def test_a_gap_is_not_carried_across_and_an_incomplete_window_is_unusable():
    spy = _path(95.0, 99.0)
    qqq = _path(105.0, 101.0)
    assert _trend_ceiling(spy, qqq, len(spy) - 1) == 0.5
    # Poke a NaN into SPY's window at t: the read is unusable, not imputed.
    gapped = spy.copy()
    gapped[len(spy) - 10] = np.nan
    assert _trend_ceiling(gapped, qqq, len(spy) - 1) is None
    # Both benchmarks decided below at 95 and then sat flat for a full window.
    # SPY has a gap right after its decided session, QQQ does not. At a last
    # close of 100.5 - inside the upper band - QQQ still holds below, while
    # SPY's run after the gap has no decided state and the plain comparison
    # reads it above; at 99.5 the plain comparison reads SPY below as well.
    long_spy = np.concatenate(
        [spy, [np.nan], np.full(TREND_WINDOW - 1, 100.0), [100.5]]
    )
    long_qqq = np.concatenate([spy, np.full(TREND_WINDOW, 100.0), [100.5]])
    t = len(long_spy) - 1
    assert len(long_qqq) == len(long_spy)
    assert _trend_ceiling(long_spy, long_qqq, t) == 0.5
    long_spy[-1] = 99.5
    long_qqq[-1] = 99.5
    assert _trend_ceiling(long_spy, long_qqq, t) == 0.0


# Through the full decision: a benchmark inside the lower band keeps the
# ceiling that its last decided state set, so the vol_trend decision does
# not scale the book down for a close that merely dipped under the mean,
# while a close through the band halves the ceiling and scales the book.
@pytest.mark.parametrize(("last_close", "expected_ceiling"), [(99.0, 1.0), (96.0, 0.5)])
def test_decide_reads_the_ceiling_with_hysteresis(last_close, expected_ceiling):
    spy = _path(105.0, last_close)
    qqq = _path(105.0, 103.0)
    n = len(spy)
    stock = 100.0 + 0.05 * np.arange(n)
    prices = np.column_stack([stock, stock, stock, stock, spy, qqq])
    tickers = ["AAA", "BBB", "CCC", "DDD", SPY, QQQ]
    desired = {"AAA": 0.15, "BBB": 0.15, "CCC": 0.15, "DDD": 0.15}
    d = decide(
        _dates(n),
        prices,
        tickers,
        n - 1,
        desired=desired,
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=allocation.POLICY_VOL_TREND,
    )
    assert d.available
    assert d.volatility is not None
    assert d.volatility.trend_ceiling == expected_ceiling
    if expected_ceiling == 1.0:
        assert d.binding == allocation.BINDING_NONE
        assert d.desired_weights == desired
    else:
        assert d.binding == allocation.BINDING_TREND
        assert d.desired_weights == pytest.approx({s: 0.125 for s in desired})
