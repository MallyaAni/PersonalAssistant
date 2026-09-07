"""The execution measurement: what a fill schedule pays against the open.

What has to hold: a schedule's shortfall is signed by side and charges
the spread only inside a bar, never at either auction; the fixed
schedules each spend the whole order; and the state a policy sees at a
slot is built only from bars that had closed by then - the leak the
intraday experiment once had.
"""

import numpy as np
import pytest

# The commands under test import torch at module level; the gate container
# has none, and a research command is not what the gate is for.
torch = pytest.importorskip("torch")

from backend.cli import market_execution_rl as ex


def _session(n: int = 25, bars: int = 26, seed: int = 0):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.002, (n, bars)), axis=1))
    high = close * 1.001
    low = close * 0.999
    volume = rng.uniform(1_000, 2_000, (n, bars))
    open0 = close[:, 0] * (1 + rng.normal(0, 0.001, n))
    prev = np.r_[np.nan, close[:-1, -1]]
    return close, high, low, volume, open0, prev


# Buys pay what the fill price is above the open and sells earn it; a
# fill at either auction carries no spread cost, a fill inside a bar does.
def test_shortfall_is_signed_by_side_and_charges_only_intraday_fills():
    rel = np.zeros((1, ex.SLOTS))
    rel[0, 1:] = 10.0  # every bar is ten basis points above the open
    at_open = np.zeros((1, ex.SLOTS))
    at_open[0, 0] = 1.0
    at_close = np.zeros((1, ex.SLOTS))
    at_close[0, -1] = 1.0
    in_bar = np.zeros((1, ex.SLOTS))
    in_bar[0, 5] = 1.0
    buy, sell = np.ones(1), -np.ones(1)
    assert ex.shortfall(at_open, rel, buy, cost=2.0)[0] == 0.0
    assert ex.shortfall(at_close, rel, buy, cost=2.0)[0] == 10.0  # the print only
    assert ex.shortfall(at_close, rel, sell, cost=2.0)[0] == -10.0
    assert ex.shortfall(in_bar, rel, buy, cost=2.0)[0] == 12.0  # plus the spread
    assert ex.shortfall(in_bar, rel, sell, cost=2.0)[0] == -8.0


# Every fixed schedule spends exactly the whole order, and the VWAP shape
# follows the name's usual volume by slot.
def test_fixed_schedules_spend_the_whole_order():
    share = np.full((3, ex.SLOTS - 1), 1.0 / (ex.SLOTS - 1))
    share[:, 0] = 0.5
    share /= share.sum(axis=1, keepdims=True)
    orders = ex.Orders(
        tickers=np.array(["A"] * 3),
        days=np.arange("2026-01-05", "2026-01-08", dtype="datetime64[D]"),
        rel=np.zeros((3, ex.SLOTS), dtype=np.float32),
        x=np.zeros((3, ex.SLOTS, len(ex.FEATURES)), dtype=np.float32),
        slot_volume=share.astype(np.float32),
    )
    fixed = ex._fixed(orders)
    for name, f in fixed.items():
        assert np.allclose(f.sum(axis=1), 1.0), name
    assert fixed["open (the desk today)"][0, 0] == 1.0
    assert fixed["close"][0, -1] == 1.0
    assert np.isclose(fixed["VWAP shape"][0, 1], share[0, 0])


# The state at a slot depends only on bars that had closed before it. A
# change to bar j must leave every slot up to j + 1 untouched, since slot
# j + 1 is decided at the start of bar j.
def test_features_at_a_slot_use_only_earlier_bars():
    close, high, low, volume, open0, prev = _session()
    before, valid = ex._own_features(close, high, low, volume, open0, prev)
    assert valid[-1]  # the last session has a full volume window behind it
    for j in (0, 7, 25):
        c, h, lo, v = close.copy(), high.copy(), low.copy(), volume.copy()
        c[-1, j] *= 1.05
        h[-1, j] *= 1.05
        lo[-1, j] *= 0.95
        v[-1, j] *= 3.0
        after, _ = ex._own_features(c, h, lo, v, open0, prev)
        assert np.array_equal(before[-1, : j + 2], after[-1, : j + 2]), j
        if j + 2 < ex.SLOTS:
            assert not np.array_equal(before[-1, j + 2], after[-1, j + 2]), j


# The opening auction slot knows only the overnight gap; nothing about the
# session's own bars reaches it.
def test_the_open_slot_knows_only_the_gap():
    close, high, low, volume, open0, prev = _session()
    x, _ = ex._own_features(close, high, low, volume, open0, prev)
    assert np.all(x[:, 0, :7] == 0.0)
    assert np.isclose(x[-1, 0, 7], np.log(open0[-1] / prev[-1]))
    assert x[-1, 0, 8] == 1.0
    assert x[0, 0, 8] == 0.0  # the first session has no previous close


# The market column is the book's average move on the day, the same for
# every order that day, and computed within the day only.
def test_market_column_is_the_days_average_across_names():
    days = np.array(["2026-01-05", "2026-01-05", "2026-01-06"], dtype="datetime64[D]")
    x = np.zeros((3, ex.SLOTS, len(ex.FEATURES)), dtype=np.float32)
    x[0, :, 1] = 1.0
    x[1, :, 1] = 3.0
    x[2, :, 1] = 10.0
    orders = ex.Orders(
        tickers=np.array(["A", "B", "A"]),
        days=days,
        rel=np.zeros((3, ex.SLOTS), dtype=np.float32),
        x=x,
        slot_volume=np.zeros((3, ex.SLOTS - 1), dtype=np.float32),
    )
    ex._fill_market(orders)
    assert np.all(orders.x[0, :, 6] == 2.0)
    assert np.all(orders.x[1, :, 6] == 2.0)
    assert np.all(orders.x[2, :, 6] == 10.0)


# The session-clustered t: identical values every session give an infinite
# t only if the spread is zero, and a two-day sample is too few to say.
def test_clustered_t_pools_within_a_session():
    days = np.array(
        ["2026-01-05"] * 3 + ["2026-01-06"] * 3 + ["2026-01-07"] * 3,
        dtype="datetime64[D]",
    )
    values = np.array([1.0, 2.0, 3.0, 2.0, 2.0, 2.0, 3.0, 2.0, 1.0])
    mean, t = ex._stat(values, days)
    assert mean == 2.0
    assert t > 1e6  # every session's mean is exactly two
    _, few = ex._stat(values[:6], days[:6])
    assert np.isnan(few)
