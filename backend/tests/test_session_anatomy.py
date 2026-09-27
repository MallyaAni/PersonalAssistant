"""The session-anatomy study finds structure exactly where a synthetic
day carries it, and none where it does not.

Synthetic cubes: a U-shaped variance day puts the largest shares in the
first and last slots; an open-drive day where the rest of the session
carries half the first half-hour gives a slope near 0.5 with a large t
on the daily cross-sectional averages; a dip-recovery day where a 2%
drawdown by 11:30 is followed by an extra 1% gives a positive
conditional difference with a large t; an iid day gives |t| < 3 on every
cell. The VWAP proxy is checked by hand, benchmarks are never pooled with
the book, and the windows split sessions by date.
"""

import math
from datetime import date, timedelta

import numpy as np
import pytest

from backend.market import session_anatomy as sa
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

SLOTS = FULL_SESSION_SLOTS


# `n` weekdays from `start` as datetime64[D].
def _dates(n: int, start: date = date(2016, 1, 4)) -> np.ndarray:
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return np.array(out, dtype="datetime64[D]")


# A cube whose bar log returns are `returns` (N, 26), opening at `open0`
# on every session, with the prior close equal to the open (no gap)
# unless given. High and low are the bar's open/close extremes.
def _cube(
    ticker: str,
    dates: np.ndarray,
    returns: np.ndarray,
    open0: float = 100.0,
    volume: np.ndarray | None = None,
    prior_close: np.ndarray | None = None,
    auction_open: np.ndarray | None = None,
) -> SessionCube:
    n = len(dates)
    close = open0 * np.exp(np.cumsum(returns, axis=1))
    open_ = np.column_stack([np.full(n, open0), close[:, :-1]])
    return SessionCube(
        ticker=ticker,
        dates=dates,
        open=open_,
        high=np.maximum(open_, close),
        low=np.minimum(open_, close),
        close=close,
        volume=volume if volume is not None else np.full((n, SLOTS), 1000.0),
        prior_close=prior_close if prior_close is not None else np.full(n, open0),
        excluded={"early_close": 0, "incomplete": 0, "no_prior_close": 0},
        auction_open=auction_open if auction_open is not None else np.full(n, np.nan),
        auction_volume=np.full(n, np.nan),
    )


# Every session of every name is a member.
def _all_members(ticker: str, dates: np.ndarray) -> np.ndarray:
    return np.ones(len(dates), dtype=bool)


# The primitives agree with the cube's arithmetic.
def test_returns_gap_and_session_return():
    dates = _dates(2)
    returns = np.zeros((2, SLOTS))
    returns[0, 0] = 0.01
    returns[0, 5] = -0.02
    returns[1, 25] = 0.03
    cube = _cube("AAA", dates, returns, prior_close=np.array([99.0, 101.0]))
    np.testing.assert_allclose(sa.bar_returns(cube), returns, atol=1e-12)
    np.testing.assert_allclose(sa.session_return(cube), [-0.01, 0.03], atol=1e-12)
    np.testing.assert_allclose(
        sa.gap(cube), np.log([100 / 99.0, 100 / 101.0]), atol=1e-12
    )


# (i) A U-shaped variance process: the first and last slots carry the
# largest shares, the shares sum to one; the extreme-slot histograms
# count where the high and low are set.
def test_u_shaped_variance_lands_in_the_first_and_last_slots():
    rng = np.random.default_rng(1)
    sigma = np.full(SLOTS, 0.001)
    sigma[0] = 0.006
    sigma[-1] = 0.004
    returns = rng.normal(0.0, 1.0, size=(800, SLOTS)) * sigma
    cube = _cube("AAA", _dates(800), returns)
    shares = sa.variance_shares(cube)
    assert shares.shape == (SLOTS,)
    assert shares.sum() == pytest.approx(1.0)
    order = np.argsort(shares)[::-1]
    assert order[0] == 0
    assert order[1] == SLOTS - 1
    assert shares[1:-1].max() < shares[-1]
    high, low = sa.extreme_slot_shares(cube)
    assert high.sum() == pytest.approx(1.0)
    assert low.sum() == pytest.approx(1.0)
    # Hand-made: a day that rises to slot 3 then falls sets its high at 3
    # and its low at 25.
    steps = np.zeros((1, SLOTS))
    steps[0, :4] = 0.01
    steps[0, 4:] = -0.005
    high, low = sa.extreme_slot_shares(_cube("AAA", _dates(1), steps))
    assert high[3] == 1.0
    assert low[SLOTS - 1] == 1.0


# (ii) An open-drive process: r_rest = 0.5 r1 + noise across five names
# gives a pooled slope within 0.1 of 0.5 and |t| > 3 on 2000 sessions.
def test_open_drive_slope_is_recovered():
    rng = np.random.default_rng(2)
    dates = _dates(2000)
    cubes = {}
    for i in range(5):
        r1 = rng.normal(0.0, 0.01, size=2000)
        rest = 0.5 * r1 + rng.normal(0.0, 0.02, size=2000)
        returns = np.zeros((2000, SLOTS))
        returns[:, 0] = r1 / 2
        returns[:, 1] = r1 / 2
        returns[:, 2:] = rest[:, None] / (SLOTS - 2)
        cubes[f"N{i}"] = _cube(f"N{i}", dates, returns)
    payload = sa.study(cubes, _all_members)
    drive = payload["book"]["2016-2023"]["open_drive"]
    assert abs(drive["slope"] - 0.5) < 0.1
    assert abs(drive["t"]) > 3
    assert drive["dates"] == 2000
    assert payload["book"]["2016-2023"]["names"] == 5
    assert payload["book"]["2016-2023"]["sessions"] == 10000
    # The quintile table is monotone in r_rest with these edges.
    means = [q["mean_y"] for q in drive["quintiles"]]
    assert len(means) == sa.QUINTILES
    assert means[0] < means[-1]
    assert sum(q["n"] for q in drive["quintiles"]) == 10000
    assert drive["quintiles"][0]["lo"] is None  # -inf is not JSON


# (iii) A dip-recovery process: sessions whose drawdown by slot 7 reaches
# -2% earn +1% afterwards; the conditional difference is positive with
# |t| > 3.
def test_dip_recovery_is_detected():
    rng = np.random.default_rng(3)
    dates = _dates(2000)
    cubes = {}
    for i in range(5):
        returns = rng.normal(0.0, 0.01, size=(2000, SLOTS))
        path = np.cumsum(returns, axis=1)
        dipped = np.minimum.accumulate(path, axis=1)[:, 7] <= -0.02
        returns[dipped, 8] += 0.01
        cubes[f"N{i}"] = _cube(f"N{i}", dates, returns)
    payload = sa.study(cubes, _all_members)
    cells = {
        (c["slot"], c["threshold"]): c for c in payload["book"]["2016-2023"]["dips"]
    }
    cell = cells[(7, -0.02)]
    assert cell["n"] > 500
    assert cell["dates"] > 500
    assert cell["difference"] > 0.004
    assert cell["t"] > 3
    assert len(payload["book"]["2016-2023"]["dips"]) == len(sa.CHECK_SLOTS) * len(
        sa.DIP_THRESHOLDS
    )
    assert len(payload["book"]["2016-2023"]["extensions"]) == len(sa.CHECK_SLOTS) * len(
        sa.EXT_THRESHOLDS
    )


# (iv) An iid null: |t| < 3 on the open-drive slope and every dip and
# extension cell.
def test_iid_null_shows_nothing():
    rng = np.random.default_rng(4)
    dates = _dates(2000)
    cubes = {
        f"N{i}": _cube(f"N{i}", dates, rng.normal(0.0, 0.01, size=(2000, SLOTS)))
        for i in range(5)
    }
    book = sa.study(cubes, _all_members)["book"]["2016-2023"]
    assert abs(book["open_drive"]["t"]) < 3
    for cell in book["dips"] + book["extensions"]:
        assert cell["n"] > 0
        assert abs(cell["t"]) < 3, cell


# (v) The VWAP proxy on a hand-made cube: closes 100..125, one share a
# bar except five in slot 3.
def test_fill_costs_by_hand():
    returns = np.zeros((1, SLOTS))
    closes = 100.0 + np.arange(SLOTS)
    returns[0, 0] = 0.0
    returns[0, 1:] = np.diff(np.log(closes))
    volume = np.ones((1, SLOTS))
    volume[0, 3] = 5.0
    cube = _cube("AAA", _dates(1), returns, volume=volume)
    np.testing.assert_allclose(cube.close[0], closes, atol=1e-9)
    costs = sa.fill_costs(cube)
    first_hour = (100 + 101 + 102 + 103 * 5) / 8
    session = (closes.sum() + 4 * 103) / 30
    assert costs["first_hour_vwap"][0] == pytest.approx(math.log(first_hour / 100))
    assert costs["session_vwap"][0] == pytest.approx(math.log(session / 100))
    assert costs["close"][0] == pytest.approx(math.log(125 / 100))
    # No auction row in the cube: the auction cost is NaN and counts as no
    # observation; with one, it is the cross's print against the open.
    assert math.isnan(costs["auction"][0])
    assert sa._moments(costs["auction"])["n"] == 0
    with_cross = _cube("AAA", _dates(1), returns, volume=volume, auction_open=np.array([126.0]))
    assert sa.fill_costs(with_cross)["auction"][0] == pytest.approx(math.log(126 / 100))
    # A session with no volume has no VWAP, and the moments say so.
    zero = _cube("AAA", _dates(1), returns, volume=np.zeros((1, SLOTS)))
    assert math.isnan(sa.fill_costs(zero)["session_vwap"][0])
    assert sa._moments(sa.fill_costs(zero)["session_vwap"])["n"] == 0


# (vi) Benchmarks are reported on their own and never enter the book,
# whatever the mask says about them.
def test_benchmarks_are_never_pooled_with_the_book():
    rng = np.random.default_rng(5)
    dates = _dates(300)
    book = _cube("AAA", dates, rng.normal(0.0002, 0.004, size=(300, SLOTS)))
    spy = _cube("SPY", dates, np.full((300, SLOTS), 0.01))  # a 26% day, every day
    payload = sa.study({"AAA": book, "SPY": spy}, _all_members)
    assert payload["book_tickers"] == ["AAA"]
    assert payload["benchmark_tickers"] == ["SPY"]
    choosing = payload["book"]["2016-2023"]
    assert choosing["names"] == 1
    assert choosing["sessions"] == 300
    assert choosing["session_return"]["mean"] == pytest.approx(
        float(sa.session_return(book).mean())
    )
    bench = payload["benchmarks"]["SPY"]["2016-2023"]
    assert bench["sessions"] == 300
    assert bench["session_return"]["mean"] == pytest.approx(0.26)
    assert payload["benchmarks"]["SPY"]["2024-2026"]["sessions"] == 0


# (vii) Windows split by date, and the membership mask restricts the
# book's rows per name; quintile edges come from the choosing window.
def test_windows_and_mask():
    rng = np.random.default_rng(6)
    dates = _dates(120, start=date(2023, 10, 2))
    before = int((dates < np.datetime64("2024-01-01")).sum())
    assert 0 < before < 120
    cubes = {
        "AAA": _cube("AAA", dates, rng.normal(0.0, 0.004, size=(120, SLOTS))),
        "BBB": _cube("BBB", dates, rng.normal(0.0, 0.004, size=(120, SLOTS))),
    }
    payload = sa.study(cubes, _all_members)
    assert payload["book"]["2016-2023"]["sessions"] == 2 * before
    assert payload["book"]["2024-2026"]["sessions"] == 2 * (120 - before)
    assert payload["book"]["2016-2023"]["dates"] == before
    assert payload["windows"]["2016-2023"] == {
        "start": "2016-01-01",
        "end": "2024-01-01",
    }
    assert payload["windows"]["2024-2026"]["end"] is None
    # The edges are the choosing window's and are applied to both.
    choosing_r1 = np.concatenate([sa.open_drive(c)[0][:before] for c in cubes.values()])
    edges = sa.quintile_edges(choosing_r1)
    np.testing.assert_allclose(
        payload["book"]["2016-2023"]["open_drive"]["edges"], edges
    )
    np.testing.assert_allclose(
        payload["book"]["2024-2026"]["open_drive"]["edges"], edges
    )
    # A dict mask: BBB is a member on its first ten sessions only.
    mask = {"AAA": dates, "BBB": dates[:10]}
    masked = sa.study(cubes, mask)
    assert masked["book"]["2016-2023"]["sessions"] == before + 10
    assert masked["book"]["2024-2026"]["sessions"] == 120 - before
    assert masked["book"]["2024-2026"]["names"] == 1
    # A name absent from the mask contributes nothing; an empty window is
    # well formed with zero counts.
    nobody = sa.study(cubes, {"AAA": set(dates[:3].astype(object))})
    assert nobody["book"]["2016-2023"]["sessions"] == 3
    empty = nobody["book"]["2024-2026"]
    assert empty["sessions"] == 0
    assert empty["names"] == 0
    assert empty["open_drive"]["slope"] is None
    assert empty["variance_shares"] == [None] * SLOTS


# The slope's t reuses `hac_t` exactly: it equals the Newey-West sandwich
# computed directly.
def test_slope_hac_t_matches_a_direct_sandwich():
    rng = np.random.default_rng(7)
    x = rng.normal(size=400)
    y = 0.3 * x + rng.normal(size=400)
    slope, t, n = sa.slope_hac_t(x, y, lag=5)
    assert n == 400
    xc = x - x.mean()
    beta = float(xc @ (y - y.mean()) / (xc @ xc))
    assert slope == pytest.approx(beta)
    score = xc * ((y - y.mean()) - beta * xc)
    lrv = float(score @ score) / n
    for k in range(1, 6):
        lrv += 2.0 * (1.0 - k / 6.0) * float(score[k:] @ score[:-k]) / n
    direct = beta * float(xc @ xc) / math.sqrt(n * lrv)
    assert t == pytest.approx(direct, rel=1e-9)
    # Degenerate inputs are NaN, never an exception.
    assert all(math.isnan(v) for v in sa.slope_hac_t(np.ones(5), np.arange(5.0))[:2])
    assert sa.slope_hac_t(np.arange(2.0), np.arange(2.0))[2] == 2


# The daily average groups rows by date, and a conditional cell counts
# the dates that contribute.
def test_daily_average_and_conditional_difference():
    dates = np.array(
        ["2016-01-04", "2016-01-05", "2016-01-04", "2016-01-06"], dtype="datetime64[D]"
    )
    values = np.array([1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(sa.daily_average(dates, values), [2.0, 2.0, 4.0])
    cell = sa.conditional_difference(
        dates, values, np.array([True, False, True, False])
    )
    assert cell["n"] == 2
    assert cell["dates"] == 1
    assert cell["unconditional_mean"] == pytest.approx(2.5)
    assert cell["conditional_mean"] == pytest.approx(2.0)
    assert cell["difference"] == pytest.approx(-0.5)
    assert math.isnan(cell["t"])  # one date is below MIN_CELL_DATES
    none = sa.conditional_difference(dates, values, np.zeros(4, dtype=bool))
    assert none["n"] == 0
    assert math.isnan(none["difference"])
