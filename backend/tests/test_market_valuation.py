"""Valuation multiples, peer groups and cheapness."""

from datetime import date, timedelta

import numpy as np

from backend.market import valuation
from backend.market.panel import Panel


def _panel(close: np.ndarray) -> Panel:
    t, n = close.shape
    dates = np.array(
        [date(2026, 1, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    return Panel(
        dates=dates,
        tickers=tuple(f"N{i}" for i in range(n)),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={f"N{i}": () for i in range(n)},
        benchmark="N0",
    )


# A multiple is the log of market value over the filed level, and it is
# absent rather than wrong where the level is not positive.
def test_multiples_are_logs_and_absent_without_a_positive_level():
    close = np.full((2, 3), 10.0)
    panel = _panel(close)
    shares = np.full((2, 3), 100.0)  # market value 1,000 each
    revenue = np.array([[100.0, 500.0, 0.0]] * 2)
    earnings = np.array([[50.0, -20.0, 10.0]] * 2)
    equity = np.array([[200.0, 200.0, 200.0]] * 2)
    growth = np.array([[1.0, 0.0, 0.0]] * 2)
    m = valuation.multiples(panel, revenue, earnings, equity, shares, growth)
    assert m.price_sales[0, 0] == np.log(10.0)
    assert m.price_sales[0, 1] == np.log(2.0)
    assert np.isnan(m.price_sales[0, 2])  # no revenue filed
    assert np.isnan(m.price_earnings[0, 1])  # a loss has no earnings multiple
    assert m.price_book[0, 0] == np.log(5.0)
    # Growth-adjusted: the same multiple, less the growth rate.
    assert m.price_sales_growth[0, 0] == np.log(10.0) - np.log(2.0)
    assert m.market_cap[0, 0] == 1000.0


# Cheapness is the distance below the peer group's median, and a group with
# too few known values gives no opinion.
def test_cheapness_against_peers():
    values = np.array([[1.0, 2.0, 3.0, 9.0, np.nan]])
    groups = np.array([[0, 0, 0, 1, 1]])
    out = valuation.cheapness(values, groups)
    assert out[0, 0] == 1.0  # a point below the median of 2 is cheap
    assert out[0, 1] == 0.0
    assert out[0, 2] == -1.0
    assert np.isnan(out[0, 3])  # only one known value in that group
    ungrouped = valuation.cheapness(values, np.full((1, 5), -1))
    assert np.isnan(ungrouped).all()


# Size buckets split the eligible names into thirds, smallest first, and
# only once there are enough names for every third to have real peers.
def test_size_groups():
    cap = np.array([[float(i) for i in range(1, 10)] + [np.nan]])
    eligible = np.array([True] * 9 + [False])
    ids = valuation.size_groups(cap, eligible)
    assert ids[0].tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 2, -1]
    few = valuation.size_groups(np.array([[1.0, 2.0, 3.0]]), np.array([True] * 3))
    assert (few == -1).all()  # too few names to make thirds


# Size neutrality changes the answer: a cheap-but-large name is no longer
# beaten by a name that is only cheap because it is small.
def test_size_neutral_ranks_within_size_too():
    # Nine names in one peer group. Three are cheap against the group, but
    # one of them is small among equally cheap small names while another is
    # large among expensive large names.
    multiple = np.array([[1.0, 1.0, 1.0, 3.0, 3.0, 3.0, 1.0, 5.0, 5.0]])
    peers = np.zeros((1, 9), dtype=int)
    cap = np.array([[1.0, 2.0, 3.0, 100.0, 200.0, 300.0, 1e3, 2e3, 3e3]])
    eligible = np.array([True] * 9)
    raw = valuation.cheapness(multiple, peers)
    assert raw[0, 0] == raw[0, 6]  # against the group alone they look alike
    neutral = valuation.cheapness(
        multiple, peers, cap=cap, eligible=eligible, size_neutral=True
    )
    assert np.isfinite(neutral).all()
    # Cheap among expensive peers of its own size beats cheap among cheap ones.
    assert neutral[0, 6] > neutral[0, 0]
    # With too few names for size thirds, the peer view still stands.
    small = valuation.cheapness(
        np.array([[1.0, 3.0, 5.0]]),
        np.zeros((1, 3), dtype=int),
        cap=np.array([[1.0, 2.0, 3.0]]),
        eligible=np.array([True] * 3),
        size_neutral=True,
    )
    assert np.isfinite(small).all()
    assert small[0, 0] > small[0, 2]


# Group ids come from a ticker mapping and are -1 for anything unmapped.
def test_groups_from_mapping():
    panel = _panel(np.full((3, 4), 10.0))
    ids = valuation.groups_from(panel, {"N0": "ai", "N1": "software", "N2": "ai"})
    assert ids[0].tolist() == [0, 1, 0, -1]
    assert (ids[0] == ids[2]).all()
