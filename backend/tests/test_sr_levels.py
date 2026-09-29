"""Point-in-time support and resistance levels.

The plan: docs/research/sr-levels-plan-2026-09-29.md.

What has to hold:

- Every level is known when the plan says and not before.
  - The daily structure for session d reads rows up to d - 1. Perturbing
    every row from d on leaves it unchanged.
  - The weekly levels read only completed weeks: a Wednesday ignores its
    own Monday and Tuesday.
  - A swing enters the day after its confirming session.
  - The volume nodes read the prior 20 cube sessions and none of the
    session itself.
  - The opening range appears from slot 2, and the VWAP in force during a
    bar stops at the bar before.
  - The assembled levels at (session, bar) survive perturbing everything
    after that bar's start.
- The zone half-width is max(0.25 ATR14, 0.3% of the prior close).
- A support touch enters a zone from above, never from below, and never
  before slot 2. It is the highest zone reached, and it carries the
  families and confluence inside that zone. Resistance mirrors it.
- Confluence counts distinct level prices within the half-width.
- A clear move has nothing within two half-widths beyond its extreme.
- The close zones hold the largest confluence of a zone around the close,
  split by the level's side of the prior bar's close.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from backend.market import levels as daily_structure
from backend.market import sr_levels as sr
from backend.market.panel import Panel
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.market.technical import sma

SLOTS = FULL_SESSION_SLOTS
K = len(sr.KINDS)


# `n` weekdays from `start` as datetime64[D].
def _weekdays(n: int, start: date = date(2021, 1, 4)) -> np.ndarray:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return np.array(out, dtype="datetime64[D]")


# A panel of `names` random-walk names plus SPY over `n` weekdays, with
# highs and lows around the open and close and a dividend factor on the
# adjusted close of the first name.
def _panel(n: int = 700, names: int = 3, seed: int = 0) -> Panel:
    rng = np.random.default_rng(seed)
    cols = names + 1
    close = 50.0 * np.exp(rng.normal(0.0004, 0.02, size=(n, cols)).cumsum(axis=0))
    prior = np.vstack([close[:1], close[:-1]])
    open_ = prior * np.exp(rng.normal(0, 0.006, size=(n, cols)))
    high = np.maximum(open_, close) * np.exp(
        np.abs(rng.normal(0, 0.008, size=(n, cols)))
    )
    low = np.minimum(open_, close) * np.exp(
        -np.abs(rng.normal(0, 0.008, size=(n, cols)))
    )
    adj = close.copy()
    adj[:, 0] *= np.linspace(0.9, 1.0, n)
    tickers = tuple(f"N{i}" for i in range(names)) + ("SPY",)
    return Panel(
        dates=_weekdays(n),
        tickers=tickers,
        open=open_,
        high=high,
        low=low,
        close=close,
        adj_close=adj,
        volume=np.full((n, cols), 1e6),
        themes={t: () for t in tickers},
        benchmark="SPY",
    )


# The panel with every price row from `row` on multiplied by random factors.
def _perturb_from(panel: Panel, row: int, seed: int = 1) -> Panel:
    rng = np.random.default_rng(seed)
    shape = panel.close[row:].shape
    fields = {}
    for name in ("open", "high", "low", "close", "adj_close"):
        values = getattr(panel, name).copy()
        values[row:] *= np.exp(rng.normal(0, 0.05, size=shape))
        fields[name] = values
    return replace(panel, **fields)


# A cube of `n` random-walk sessions opening where the last closed, with
# volume per bar, raw prices and the auction print at the last close.
def _cube(n: int = 60, seed: int = 0, start: date = date(2021, 1, 4)) -> SessionCube:
    rng = np.random.default_rng(seed)
    close = np.zeros((n, SLOTS))
    open_ = np.zeros((n, SLOTS))
    price = 100.0
    for i in range(n):
        o = price * math.exp(rng.normal(0, 0.004))
        c = o * np.exp(np.cumsum(rng.normal(0, 0.004, SLOTS)))
        open_[i] = np.concatenate([[o], c[:-1]])
        close[i] = c
        price = c[-1]
    wick = np.abs(rng.normal(0, 0.002, size=(2, n, SLOTS)))
    return SessionCube(
        ticker="N0",
        dates=_weekdays(n, start),
        open=open_,
        high=np.maximum(open_, close) * np.exp(wick[0]),
        low=np.minimum(open_, close) * np.exp(-wick[1]),
        close=close,
        volume=rng.uniform(100, 1000, size=(n, SLOTS)),
        prior_close=np.full(n, np.nan),
        excluded={},
        auction_open=close[:, -1].copy(),
        auction_volume=np.full(n, np.nan),
    )


# One hand-built session: bar closes `close` (26,), lows and highs a tenth
# either side unless given, and `placed` levels ({kind: price}) in force on
# every bar from slot 0; the half-width `width`.
def _session(
    close: np.ndarray,
    placed: dict[str, float],
    width: float = 1.0,
    low: np.ndarray | None = None,
    high: np.ndarray | None = None,
) -> sr.SessionLevels:
    close = np.asarray(close, dtype=float)
    values = np.full((1, SLOTS, K), np.nan)
    for kind, price in placed.items():
        values[0, :, sr.KINDS.index(kind)] = price
    return sr.SessionLevels(
        dates=np.array(["2021-03-01"], dtype="datetime64[D]"),
        open=np.concatenate([[close[0]], close[:-1]])[None, :],
        high=(close + 0.1 if high is None else np.asarray(high, dtype=float))[None, :],
        low=(close - 0.1 if low is None else np.asarray(low, dtype=float))[None, :],
        close=close[None, :],
        width=np.array([width]),
        levels=values,
    )


# The plan's constants, frozen.
def test_constants_are_the_plans():
    assert len(sr.KINDS) == 22
    assert len(sr.FAMILIES) == 12
    assert sr.SWING_HORIZONS == (20, 60, 250)
    assert sr.SMA_LENGTHS == (50, 200)
    assert sr.WEEKLY_SMA_WEEKS == 21
    assert sr.YEAR_SESSIONS == 252
    assert (sr.ATR_SESSIONS, sr.ATR_SHARE, sr.MIN_WIDTH) == (14, 0.25, 0.003)
    assert sr.FIRST_SLOT == 2
    assert sr.PROFILE_SESSIONS == 20
    assert math.isclose(sr.PROFILE_BIN, math.log(1.0025))
    assert sr.NODE_COUNT == 3
    assert {sr.FAMILY_OF[k] for k in sr.KINDS} == set(sr.FAMILIES)
    assert sr.KINDS[: len(sr.DAILY_KINDS)] == sr.DAILY_KINDS


# Weeks run Monday to Friday: a Monday starts a new week and a weekend
# belongs to the week before.
def test_week_of():
    days = np.array(
        ["2021-03-05", "2021-03-06", "2021-03-07", "2021-03-08", "2021-03-12"],
        dtype="datetime64[D]",
    )
    weeks = sr.week_of(days)
    assert weeks[0] == weeks[1] == weeks[2]
    assert weeks[3] == weeks[4] == weeks[0] + 1


# Availability of the daily structure: the levels in force during session d
# are unchanged when every row from d on is perturbed, for every d tried,
# every kind and the half-width. And the prior-day levels are exactly row
# d - 1's, the moving averages and the 52-week range stop at d - 1.
def test_daily_levels_are_known_at_the_prior_close():
    panel = _panel()
    base = sr.daily_levels(panel)
    assert base.levels.shape == (700, 4, len(sr.DAILY_KINDS))
    for d in (1, 100, 251, 300, 453, 699):
        moved = sr.daily_levels(_perturb_from(panel, d, seed=d))
        np.testing.assert_array_equal(moved.levels[: d + 1], base.levels[: d + 1])
        np.testing.assert_array_equal(moved.width[: d + 1], base.width[: d + 1])
    # The perturbation does reach the next session's levels.
    later = sr.daily_levels(_perturb_from(panel, 300))
    assert not np.array_equal(later.levels[301], base.levels[301], equal_nan=True)
    factor = panel.adj_close / panel.close
    at = {k: base.levels[:, :, i] for i, k in enumerate(sr.DAILY_KINDS)}
    d = 400
    np.testing.assert_array_equal(at["prior_day_close"][d], panel.adj_close[d - 1])
    np.testing.assert_array_equal(at["prior_day_high"][d], (panel.high * factor)[d - 1])
    np.testing.assert_array_equal(at["prior_day_low"][d], (panel.low * factor)[d - 1])
    np.testing.assert_allclose(
        at["sma_50"][d], panel.adj_close[d - 50 : d].mean(axis=0), rtol=1e-12
    )
    np.testing.assert_array_equal(at["sma_200"][d], sma(panel.adj_close, 200)[d - 1])
    np.testing.assert_allclose(
        at["high_52w"][d], (panel.high * factor)[d - 252 : d].max(axis=0), rtol=1e-12
    )
    np.testing.assert_allclose(
        at["low_52w"][d], (panel.low * factor)[d - 252 : d].min(axis=0), rtol=1e-12
    )
    assert np.isnan(base.levels[0]).all()


# The weekly levels read only completed weeks. On a Wednesday, perturbing
# its own Monday and Tuesday changes the prior-day levels but not the
# 21-week mean or the prior week's range. The prior week's range is last
# week's extremes; the mean is of 21 Friday closes.
def test_weekly_levels_read_only_completed_weeks():
    panel = _panel()
    days = panel.dates.astype("datetime64[D]")
    weekday = (days.astype(np.int64) + 3) % 7  # 0 = Monday
    # A Wednesday with well over 21 weeks behind it.
    d = int(np.flatnonzero((weekday == 2) & (np.arange(len(days)) > 200))[0])
    base = sr.daily_levels(panel)
    moved = replace(
        panel,
        **{
            name: _bump(getattr(panel, name), [d - 2, d - 1])
            for name in ("high", "low", "close", "adj_close")
        },
    )
    after = sr.daily_levels(moved)
    kinds = sr.DAILY_KINDS
    for kind in ("wsma_21", "prior_week_high", "prior_week_low"):
        i = kinds.index(kind)
        np.testing.assert_array_equal(after.levels[d, :, i], base.levels[d, :, i])
    assert not np.array_equal(
        after.levels[d, :, kinds.index("prior_day_close")],
        base.levels[d, :, kinds.index("prior_day_close")],
    )
    # The prior week is the five sessions before this week's Monday.
    factor = panel.adj_close / panel.close
    last_week = slice(d - 7, d - 2)
    np.testing.assert_allclose(
        base.levels[d, :, kinds.index("prior_week_high")],
        (panel.high * factor)[last_week].max(axis=0),
    )
    np.testing.assert_allclose(
        base.levels[d, :, kinds.index("prior_week_low")],
        (panel.low * factor)[last_week].min(axis=0),
    )
    fridays = np.flatnonzero((weekday == 4) & (np.arange(len(days)) < d - 2))[-21:]
    np.testing.assert_allclose(
        base.levels[d, :, kinds.index("wsma_21")],
        panel.adj_close[fridays].mean(axis=0),
        rtol=1e-12,
    )


# Every entry at `rows` multiplied by 1.07.
def _bump(values: np.ndarray, rows: list[int]) -> np.ndarray:
    out = values.copy()
    out[rows] *= 1.07
    return out


# A swing low printed on row t is confirmed at t + 5's close. It is in force
# from session t + 6, not on t + 5 itself. A swing found by two horizons is
# kept at the shorter one only.
def test_swing_enters_the_day_after_confirmation():
    n = 120
    close = np.full((n, 2), 100.0)
    close[60, 0] = 90.0
    dates = _weekdays(n)
    panel = Panel(
        dates=dates,
        tickers=("AAA", "SPY"),
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close.copy(),
        volume=np.full((n, 2), 1e6),
        themes={"AAA": ()},
        benchmark="SPY",
    )
    daily = sr.daily_levels(panel)
    low20 = daily.levels[:, 0, sr.DAILY_KINDS.index("swing_low_20")]
    low60 = daily.levels[:, 0, sr.DAILY_KINDS.index("swing_low_60")]
    low250 = daily.levels[:, 0, sr.DAILY_KINDS.index("swing_low_250")]
    assert np.isnan(low20[: 60 + daily_structure.SWING + 1]).all()
    assert low20[60 + daily_structure.SWING + 1] == pytest.approx(90.0 * 0.99)
    # Twenty sessions after confirmation it leaves the 20-session horizon
    # and is found by the 60 one, and never by two at once.
    both = np.isfinite(low20) & np.isfinite(low60)
    assert not both.any()
    assert np.isfinite(low60).any()
    assert not (np.isfinite(low250) & (np.isfinite(low20) | np.isfinite(low60))).any()


# The zone half-width: 0.25 x ATR14 through the prior close when that is
# wider than 0.3% of the prior close, and the 0.3% floor when it is not.
def test_zone_width():
    n = 40
    close = np.full((n, 2), 100.0)
    wide = Panel(
        dates=_weekdays(n),
        tickers=("AAA", "SPY"),
        open=close,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        adj_close=close.copy(),
        volume=np.full((n, 2), 1e6),
        themes={"AAA": ()},
        benchmark="SPY",
    )
    width = sr.daily_levels(wide).width[:, 0]
    # A true range of 4 on every session: ATR 4, a quarter of it 1.0 > 0.3.
    assert width[20] == pytest.approx(1.0)
    narrow = replace(wide, high=close + 0.2, low=close - 0.2)
    assert sr.daily_levels(narrow).width[20, 0] == pytest.approx(0.3)
    # Before 14 sessions of ranges the floor holds; row 0 has no prior close.
    assert math.isnan(width[0])
    assert width[5] == pytest.approx(0.3)


# The volume nodes of session n come from sessions n - 20 .. n - 1 alone.
# A session with fewer than 20 before it has none. Session n and later
# sessions get a thousand times the volume at a fifth higher prices: enough
# to own the top node of any profile that read them. That leaves session
# n's nodes unchanged and moves session n + 1's. A later basis scale does
# the same. Volume spread over the bins a bar covers puts the top node
# where the volume sat.
def test_volume_nodes_read_only_prior_sessions():
    cube = _cube(n=40)
    scale = np.full(len(cube), 1.0)
    nodes = sr.volume_nodes(cube, scale)
    assert nodes.shape == (40, 3)
    assert np.isnan(nodes[:20]).all()
    assert np.isfinite(nodes[20:, 0]).all()
    for n in (20, 27, 38):
        future = replace(
            cube,
            high=_scaled_from(cube.high, n),
            low=_scaled_from(cube.low, n),
            volume=_scaled_from(cube.volume, n, 1000.0),
        )
        moved = sr.volume_nodes(future, scale)
        np.testing.assert_array_equal(moved[: n + 1], nodes[: n + 1])
        # Session n + 1 reads session n: its top node is inside n's new range.
        lo, hi = future.low[n].min(), future.high[n].max()
        assert lo * 0.997 <= moved[n + 1, 0] <= hi * 1.003
        assert not lo * 0.997 <= nodes[n + 1, 0] <= hi * 1.003
        loud = replace(cube, volume=_scaled_from(cube.volume, n, 1000.0))
        future_scale = scale.copy()
        future_scale[n:] = 1.3
        rescaled = sr.volume_nodes(loud, future_scale)
        np.testing.assert_array_equal(rescaled[: n + 1], nodes[: n + 1])
        lo, hi = 1.3 * cube.low[n].min(), 1.3 * cube.high[n].max()
        assert lo * 0.997 <= rescaled[n + 1, 0] <= hi * 1.003
    # Heavy volume on one flat bar in every session: the top node is its bin.
    flat = replace(cube, volume=np.full(cube.volume.shape, 1.0))
    high, low = flat.high.copy(), flat.low.copy()
    high[:, 10] = low[:, 10] = 123.0
    volume = flat.volume.copy()
    volume[:, 10] = 1e6
    heavy = replace(flat, high=high, low=low, volume=volume)
    top = sr.volume_nodes(heavy, scale)[25, 0]
    b = math.floor(math.log(123.0) / sr.PROFILE_BIN)
    assert top == pytest.approx(math.exp((b + 0.5) * sr.PROFILE_BIN))


# Values from session `n` on multiplied by `factor`.
def _scaled_from(values: np.ndarray, n: int, factor: float = 1.2) -> np.ndarray:
    out = values.copy()
    out[n:] *= factor
    return out


# The opening range appears from slot 2 as the first two bars' extremes;
# the VWAP in force during bar s is sum(close x volume) / sum(volume) over
# bars before s; changing bar s or later changes neither at s.
def test_intraday_levels_are_formed_before_the_bar():
    cube = _cube(n=3)
    levels = sr.intraday_levels(cube.high, cube.low, cube.close, cube.volume)
    assert np.isnan(levels[:, :2, :2]).all()
    np.testing.assert_array_equal(
        levels[:, 2:, 0],
        np.repeat(cube.high[:, :2].max(axis=1)[:, None], SLOTS - 2, axis=1),
    )
    np.testing.assert_array_equal(
        levels[:, 2:, 1],
        np.repeat(cube.low[:, :2].min(axis=1)[:, None], SLOTS - 2, axis=1),
    )
    assert np.isnan(levels[:, 0, 2]).all()
    for s in (1, 2, 9, 25):
        expected = (cube.close[:, :s] * cube.volume[:, :s]).sum(axis=1) / cube.volume[
            :, :s
        ].sum(axis=1)
        np.testing.assert_allclose(levels[:, s, 2], expected, rtol=1e-12)
        high, low, close, volume = (
            x.copy() for x in (cube.high, cube.low, cube.close, cube.volume)
        )
        for x in (high, low, close, volume):
            x[:, s:] *= 1.5
        moved = sr.intraday_levels(high, low, close, volume)
        np.testing.assert_array_equal(moved[:, s], levels[:, s])


# The assembled levels in force at (session n, bar s) see nothing after
# the bar's start. Perturb every panel row from the session's own, every
# bar of session n from s on, and every later cube session, with the basis
# scale held: all 22 levels at (n, s) and the half-width are unchanged. The
# bar before does move the VWAP.
def test_session_levels_see_nothing_after_the_decision_point():
    n_sessions = 330
    panel = _panel(n=n_sessions, names=1, seed=3)
    cube = replace(
        _cube(n=n_sessions, seed=5), dates=panel.dates.astype("datetime64[D]")
    )
    dates = panel.dates.astype("datetime64[D]")
    pos = np.searchsorted(dates, cube.dates)
    ok = np.ones(len(cube), dtype=bool)
    scale = panel.adj_close[:, 0] / cube.auction_open
    base = sr.for_cube(cube, sr.daily_levels(panel), 0, pos, ok, scale)
    for n, s in ((300, 2), (310, 7), (329, 25)):
        future_panel = _perturb_from(panel, n, seed=n)
        bars = {}
        for name in ("open", "high", "low", "close", "volume"):
            values = getattr(cube, name).copy()
            values[n, s:] *= 1.4
            values[n + 1 :] *= 0.7
            bars[name] = values
        future_cube = replace(cube, **bars)
        moved = sr.for_cube(
            future_cube, sr.daily_levels(future_panel), 0, pos, ok, scale
        )
        np.testing.assert_array_equal(moved.levels[n, s], base.levels[n, s])
        np.testing.assert_array_equal(moved.width[n], base.width[n])
        assert np.isfinite(base.levels[n, s]).sum() >= 15
    # The bar before is read: it moves the VWAP in force at (n, s).
    closes = cube.close.copy()
    closes[310, 6] *= 1.1
    touched = sr.for_cube(
        replace(cube, close=closes), sr.daily_levels(panel), 0, pos, ok, scale
    )
    vwap = sr.KINDS.index("vwap")
    assert touched.levels[310, 7, vwap] != base.levels[310, 7, vwap]


# Confluence counts the distinct level prices within the half-width,
# itself included: a repeated price once, a price exactly w away inside,
# one just beyond outside, an absent level zero.
def test_confluence_counts_distinct_prices():
    session = _session(
        np.full(SLOTS, 110.0),
        {
            "prior_day_low": 100.0,
            "prior_week_low": 100.0,  # the same price: one level
            "vwap": 100.75,
            "node_1": 101.0,  # exactly w from 100.0
            "sma_50": 102.01,  # beyond w from 101.0
        },
        width=1.0,
    )
    conf = sr.confluence(session)[0, 5]
    at = {k: conf[sr.KINDS.index(k)] for k in sr.KINDS}
    assert at["prior_day_low"] == 3  # 100, 100.75, 101
    assert at["prior_week_low"] == 3
    assert at["vwap"] == 3  # 100, 100.75, 101 (102.01 is 1.26 away)
    assert at["node_1"] == 3  # 100, 100.75, 101; 102.01 is 1.01 away
    assert at["sma_50"] == 1
    assert at["swing_low_20"] == 0


# A support touch: the prior bar closed above the zone and this bar's low
# enters it. The highest zone reached is the touch, with every family inside
# it and its confluence. A bar entering from below is not a support touch
# (it is a resistance touch), a bar whose prior close was already inside the
# zone is not one, and nothing before slot 2 is one.
def test_support_touch_enters_from_above():
    close = np.full(SLOTS, 110.0)
    low = close - 0.1
    low[6] = 100.5  # into the prior-day low's zone [99, 101] from 110
    placed = {"prior_day_low": 100.0, "node_2": 100.4, "sma_200": 90.0}
    session = _session(close, placed, width=1.0, low=low)
    hit = sr.touches(session, sr.confluence(session), sr.SUPPORT)
    assert hit.hit[0].tolist() == [s == 6 for s in range(SLOTS)]
    assert hit.level[0, 6] == 100.4  # the higher of the two in reach
    assert set(sr.family_names(hit.families[0, 6])) == {"prior_day", "volume_node"}
    assert hit.confluence[0, 6] == 2
    # Deeper: both zones and the 200-day's reached, the highest still wins.
    deep = low.copy()
    deep[6] = 89.5
    hit = sr.touches(
        _session(close, placed, 1.0, low=deep), sr.confluence(session), sr.SUPPORT
    )
    assert hit.level[0, 6] == 100.4
    # The prior bar closed inside the zone: no touch.
    inside = close.copy()
    inside[5] = 100.9
    hit = sr.touches(
        _session(inside, placed, 1.0, low=low), sr.confluence(session), sr.SUPPORT
    )
    assert not hit.hit[0, 6]
    # From below: price under the level rises into its zone - resistance.
    below = np.full(SLOTS, 95.0)
    high = below + 0.1
    high[6] = 99.5
    rising = _session(below, {"prior_day_low": 100.0}, 1.0, high=high)
    conf = sr.confluence(rising)
    assert not sr.touches(rising, conf, sr.SUPPORT).hit.any()
    up = sr.touches(rising, conf, sr.RESISTANCE)
    assert up.hit[0].tolist() == [s == 6 for s in range(SLOTS)]
    assert up.level[0, 6] == 100.0
    assert sr.family_names(up.families[0, 6]) == ["prior_day"]
    # Before 10:00: the same entry at slot 1 is never a touch.
    early = close.copy()
    early_low = close - 0.1
    early_low[1] = 100.5
    first = _session(early, placed, 1.0, low=early_low)
    assert not sr.touches(first, sr.confluence(first), sr.SUPPORT).hit.any()
    with pytest.raises(ValueError, match="side must be"):
        sr.touches(first, sr.confluence(first), "sideways")


# A clear dip trades under the prior bar's close with nothing in
# [low - 2w, P): a level 2.5w below its low leaves it clear, one 1.5w below
# does not, nor does one it passed through; resistance mirrors above.
def test_clear_moves():
    close = np.full(SLOTS, 110.0)
    close[7] = 109.0
    low = close - 0.1
    low[7] = 108.5  # a dip bar

    # The support-side clear flags of the session with one level at `price`.
    def clear_with(price: float) -> np.ndarray:
        return sr.clear_moves(
            _session(close, {"vwap": price}, 1.0, low=low), sr.SUPPORT
        )[0]

    assert clear_with(108.5 - 2.5)[7]
    assert not clear_with(108.5 - 1.5)[7]
    assert not clear_with(109.5)[7]  # between the low and the prior close
    assert clear_with(111.0)[7]  # above the prior close: not support
    # Bars that did not trade below the prior close are never clear dips.
    assert not clear_with(50.0)[8]
    assert not clear_with(50.0)[:2].any()
    high = close + 0.1
    high[7] = 111.5
    rise = _session(np.full(SLOTS, 110.0), {"vwap": 111.5 + 2.5}, 1.0, high=high)
    assert sr.clear_moves(rise, sr.RESISTANCE)[0, 7]
    rise = _session(np.full(SLOTS, 110.0), {"vwap": 111.5 + 1.5}, 1.0, high=high)
    assert not sr.clear_moves(rise, sr.RESISTANCE)[0, 7]
    no_width = replace(rise, width=np.array([np.nan]))
    assert not sr.clear_moves(no_width, sr.RESISTANCE).any()


# The close zones: the largest confluence of a zone around the bar's close,
# counting levels below the prior bar's close as support and above it as
# resistance; zero before slot 2.
def test_close_zones():
    close = np.full(SLOTS, 110.0)
    close[4] = 105.2  # near 105 and 105.9, both below 110
    close[9] = 112.0  # near 112.5, above 110
    close[1] = 105.2  # before slot 2
    placed = {"prior_day_low": 105.0, "node_1": 105.9, "prior_day_high": 112.5}
    session = _session(close, placed, width=1.0)
    zones = sr.close_zones(session, sr.confluence(session))
    assert zones.support[0, 4] == 2
    assert zones.resistance[0, 4] == 0
    assert zones.resistance[0, 9] == 1
    assert zones.support[0, 9] == 0
    assert zones.support[0, 1] == 0
    assert zones.support[0, 5] == 0  # 110 back from 105.2: nothing within 1


# A session-levels call with arrays of the wrong length is refused.
def test_session_levels_checks_shapes():
    cube = _cube(n=5)
    with pytest.raises(ValueError, match="one value per cube session"):
        sr.session_levels(cube, np.ones(4), np.full((5, 16), np.nan), np.ones(5))
    with pytest.raises(ValueError, match="daily levels have shape"):
        sr.session_levels(cube, np.ones(5), np.full((5, 3), np.nan), np.ones(5))
