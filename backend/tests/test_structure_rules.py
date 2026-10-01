"""Structure rules S1: the six fill candidates on hand-made cubes and books.

What has to hold (docs/research/structure-rules-plan-2026-09-30.md):

- The level L(t+1) is the board's: the nearer of EMA21(t) and H20(t) above
  the close of t, through `structure_panel`.
- S1a: a first bar that tags L (high within 0.5% of it) and closes back
  under it sends the buy to the official close of t+1; a tag that holds,
  or no tag, leaves the control to the bit.
- S1b: the same rejected buy is re-planned for t+2 and filled there by the
  control rule, wait 1, drift-adjusted as a one-session wait; without t+2
  it is unpriced.
- S1c: at the first 1% dip bar k the buy fills at bar k+1's close only if
  it is above bar k's low; else at a later bar closing 1% under the open
  and above the prior bar's low; else the close; no dip, the close.
- S1d: the dip level is min(open, close(t)) x 0.99, so a gap-up session
  measures the dip from the decision price; a gap of more than sigma waits
  for the close; a session opening under close(t) is the control.
- S1e: the trigger is the bar's return from the open at or under -1% net
  of SPY's over the same bar; without a SPY session, the control.
- S1f: a sell fills at L at the first bar whose high reaches it, unless
  the pop rule fired first; a session opening through L fills at the open;
  no level, the control; next_bar leaves the limit fill where it is.
- Every price is on the adjusted basis via `cube_scale`.
- The book prices sells as well as buys, carries the wait, and the
  statistics are stage 4's; the verdict is the adaptive-entry judge with
  N = 7 and the lines say which side; S1g's verdict reads two scorecard
  payloads on the return gate or the drawdown route.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import structure_panel
from backend.market import adaptive_entry as ae
from backend.market import candidate_stats, fill_timing
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market import structure_rules as sr
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.tests.test_stage4_decisions import _orders, _weekdays
from backend.tests.test_stage4_labels import _dates, _series

SLOTS = FULL_SESSION_SLOTS
T = 70
t0 = 50


# A cube whose sessions are flat at `prices` (every bar's OHLC the price,
# the auction print the price) except the sessions in `paths`, each a dict
# with 26-long "close" and optional "open", "high", "low" and "auction"
# (defaults: open = the prior bar's close with open[0] = close[0], high =
# max(open, close), low = min(open, close), auction = close[-1]).
def _cube(dates, prices, paths=None, drop=()):
    keep = [i for i in range(len(dates)) if i not in set(drop)]
    n = len(keep)
    close = np.repeat(np.asarray(prices, dtype=float)[keep][:, None], SLOTS, axis=1)
    open_ = close.copy()
    high = close.copy()
    low = close.copy()
    auction = close[:, -1].copy()
    for i, path in (paths or {}).items():
        if i not in keep:
            continue
        r = keep.index(i)
        c = np.asarray(path["close"], dtype=float)
        o = np.asarray(path.get("open", np.r_[c[0], c[:-1]]), dtype=float)
        close[r], open_[r] = c, o
        high[r] = np.asarray(path.get("high", np.maximum(o, c)), dtype=float)
        low[r] = np.asarray(path.get("low", np.minimum(o, c)), dtype=float)
        auction[r] = float(path.get("auction", c[-1]))
    return SessionCube(
        ticker="T",
        dates=np.asarray(dates)[keep],
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=np.ones((n, SLOTS)),
        prior_close=np.r_[np.nan, auction[:-1]],
        excluded={},
        auction_open=auction,
        auction_volume=np.ones(n),
    )


# The panel closes that agree with a cube's auction prints (scale 1).
def _agree(closes, cube, dates):
    out = np.asarray(closes, dtype=float).copy()
    out[np.searchsorted(dates, cube.dates)] = cube.auction_open
    return out


# A history flat at 100 whose session t0 closes at `close_t` (under the
# flat 21-EMA and the 20-day high, so a level sits just above it), with
# session t0+1 (and t0+2) following `paths`; returns (series, cube, L).
def _scene(paths, close_t=98.0, drop=()):
    dates = _dates(T)
    prices = np.full(T, 100.0)
    prices[t0] = close_t
    prices[t0 + 1 :] = close_t
    cube = _cube(dates, prices, paths=paths, drop=drop)
    series = _series(dates, _agree(prices, cube, dates))
    level = sr.levels(series).level[t0]
    return series, cube, level


# A path of 26 closes at `base` with the given bars replaced.
def _path(base, **bars):
    close = np.full(SLOTS, float(base))
    for key, value in bars.items():
        close[int(key[1:])] = value
    return close


# The level is the board's: EMA21 of the closes and the 20-day high through
# t, the nearer one above the close; none when the close is above both.
def test_the_level_is_the_boards_nearer_level_above_the_close():
    series, cube, level = _scene({})
    lv = sr.levels(series)
    ema = structure_panel.ema21(series.close)
    assert lv.ema21[t0] == pytest.approx(ema[t0])
    assert lv.high20[t0] == pytest.approx(100.0)
    assert 98.0 < level < 100.0
    assert level == pytest.approx(ema[t0])
    assert level == pytest.approx(min(ema[t0], 100.0))
    # A close above both levels has none; a close between them takes H20.
    above, _, none = _scene({}, close_t=101.0)
    assert math.isnan(none)
    assert math.isnan(sr.levels(above).level[t0])
    between_series, _, between = _scene({}, close_t=99.9)
    ema_b = structure_panel.ema21(between_series.close)[t0]
    assert 99.9 < between < 100.0
    assert between == pytest.approx(ema_b)
    assert sr.levels(between_series).falling[t0]


# A rejected tag: the first bar's high reaches L and its close falls back
# under it. S1a fills at the official close of t+1 although the control's
# dip is reached at bar 3; S1b re-plans the buy for t+2 and fills there by
# the control rule with a wait of 1; both are active and tagged; the
# control is untouched. A tag that holds (the bar closes over L) and no
# tag at all leave both as the control.
def test_a_rejected_tag_defers_s1a_to_the_close_and_s1b_to_t_plus_two():
    _, _, level = _scene({})
    first = _path(98.0, b0=97.5, b3=96.9)
    high = np.maximum(np.r_[first[0], first[:-1]], first)
    high[0] = level  # the first bar reaches L exactly
    day1 = {"close": first, "open": np.full(SLOTS, 98.0), "high": high, "auction": 96.0}
    day2 = {"close": _path(96.0, b2=94.9), "open": np.full(SLOTS, 96.0)}
    series, cube, lv = _scene({t0 + 1: day1, t0 + 2: day2})
    assert lv == pytest.approx(level)
    fills = sr.name_fills(series, cube)
    ctrl = fills[(sr.CONTROL, sr.BUY)]
    s1a = fills[(sr.RESISTANCE_DEFER, sr.BUY)]
    s1b = fills[(sr.RESISTANCE_SKIP, sr.BUY)]
    assert ctrl.price[t0] == pytest.approx(96.9)
    assert ctrl.reached[t0]
    assert ctrl.slot[t0] == 3
    assert s1a.price[t0] == pytest.approx(96.0)
    assert not s1a.reached[t0]
    assert s1a.slot[t0] == -1
    assert s1a.active[t0]
    assert s1a.tagged[t0]
    assert s1a.wait[t0] == 0
    assert s1b.price[t0] == pytest.approx(94.9)
    assert s1b.reached[t0]
    assert s1b.slot[t0] == 2
    assert s1b.wait[t0] == 1
    assert s1b.active[t0]
    assert s1b.tagged[t0]
    assert lab.gain(ctrl.price[t0 : t0 + 1], s1a.price[t0 : t0 + 1], "buy")[0] > 0
    # Other sessions: nothing tagged, both are the control to the bit.
    for f in (s1a, s1b):
        np.testing.assert_array_equal(f.price[:t0], ctrl.price[:t0])
        assert not f.active[:t0].any()
        assert not f.tagged[:t0].any()
        assert (f.wait == 0)[:t0].all()
    # next_bar: S1a still the close (not a bar fill); S1b's t+2 fill moves
    # to the next bar's open.
    nb = sr.name_fills(series, cube, next_bar=True)
    assert nb[(sr.RESISTANCE_DEFER, sr.BUY)].price[t0] == pytest.approx(96.0)
    assert nb[(sr.RESISTANCE_SKIP, sr.BUY)].price[t0] == pytest.approx(
        cube.open[t0 + 2, 3]
    )
    # A tag that holds: the bar closes over L. Both are the control.
    held = dict(day1, close=_path(98.0, b0=level + 0.2, b3=96.9))
    held["high"] = np.maximum(held["high"], held["close"])
    series2, cube2, _ = _scene({t0 + 1: held, t0 + 2: day2})
    f2 = sr.name_fills(series2, cube2)
    for rule in (sr.RESISTANCE_DEFER, sr.RESISTANCE_SKIP):
        assert f2[(rule, sr.BUY)].price[t0] == pytest.approx(96.9)
        assert f2[(rule, sr.BUY)].tagged[t0]
        assert not f2[(rule, sr.BUY)].active[t0]
        assert f2[(rule, sr.BUY)].wait[t0] == 0
    # No tag: the bar's high stays more than 0.5% under L.
    away = dict(day1, high=np.full(SLOTS, level * 0.994))
    series3, cube3, _ = _scene({t0 + 1: away, t0 + 2: day2})
    f3 = sr.name_fills(series3, cube3)
    assert not f3[(sr.RESISTANCE_DEFER, sr.BUY)].tagged[t0]
    assert f3[(sr.RESISTANCE_DEFER, sr.BUY)].price[t0] == pytest.approx(96.9)
    # A rejected tag without t+2 leaves S1b unpriced and S1a priced.
    series4, cube4, _ = _scene({t0 + 1: day1}, drop=(t0 + 2,))
    f4 = sr.name_fills(series4, cube4)
    assert math.isnan(f4[(sr.RESISTANCE_SKIP, sr.BUY)].price[t0])
    assert not f4[(sr.RESISTANCE_SKIP, sr.BUY)].active[t0]
    assert f4[(sr.RESISTANCE_DEFER, sr.BUY)].price[t0] == pytest.approx(96.0)
    # No session at all: the tag on the last row is never read.
    assert math.isnan(f4[(sr.RESISTANCE_DEFER, sr.BUY)].price[T - 1])


# Hold the dip: the dip bar k, then bar k+1 closing above k's low fills
# there; closing under it keeps watching for a later dip bar above its
# prior bar's low; none fills at the close; no dip at all, the close.
def test_hold_the_dip_reads_the_next_bar_then_keeps_watching():
    base = 100.0
    dip = base * (1 - fill_timing.DIP)

    def scene(close, low=None):
        path = {"close": close, "open": np.full(SLOTS, base)}
        if low is not None:
            path["low"] = low
        return sr.name_fills(*_scene({t0 + 1: path}, close_t=98.0)[:2])

    # (a) bar 4 dips; bar 5 closes above bar 4's low: fill at bar 5's close.
    close = _path(base, b4=dip - 0.5, b5=dip - 0.2, b9=dip - 1.0)
    fills = scene(close)
    s1c, ctrl = fills[(sr.HOLD_THE_DIP, sr.BUY)], fills[(sr.CONTROL, sr.BUY)]
    assert ctrl.slot[t0] == 4
    assert ctrl.price[t0] == pytest.approx(dip - 0.5)
    assert s1c.price[t0] == pytest.approx(dip - 0.2)
    assert s1c.slot[t0] == 5
    assert s1c.reached[t0]
    assert s1c.active[t0]
    # (b) bar 5 closes under bar 4's low; bar 9 dips above bar 8's low:
    # fill at bar 9.
    low = np.minimum(np.r_[close[0], close[:-1]], close)
    low[4] = dip - 0.1  # bar 4's low is above bar 5's close
    low[8] = dip - 1.5  # bar 8's low is under bar 9's close
    close_b = _path(base, b4=dip - 0.5, b5=dip - 0.2, b9=dip - 1.0)
    fills = scene(close_b, low)
    s1c = fills[(sr.HOLD_THE_DIP, sr.BUY)]
    assert s1c.price[t0] == pytest.approx(dip - 1.0)
    assert s1c.slot[t0] == 9
    # (c) bar 9's close is under bar 8's low: nothing qualifies, the close.
    low_c = low.copy()
    low_c[8] = dip - 0.5
    fills = scene(close_b, low_c)
    s1c = fills[(sr.HOLD_THE_DIP, sr.BUY)]
    assert s1c.price[t0] == pytest.approx(close_b[-1])
    assert not s1c.reached[t0]
    assert s1c.slot[t0] == -1
    assert s1c.active[t0]
    # (d) a dip at the last bar has no next bar: the close.
    fills = scene(_path(base, b25=dip - 1.0))
    assert fills[(sr.HOLD_THE_DIP, sr.BUY)].price[t0] == pytest.approx(dip - 1.0)
    assert not fills[(sr.HOLD_THE_DIP, sr.BUY)].reached[t0]
    # (e) no dip: the close, inactive, as the control.
    fills = scene(_path(base, b3=base - 0.1))
    s1c = fills[(sr.HOLD_THE_DIP, sr.BUY)]
    assert s1c.price[t0] == pytest.approx(base)
    assert not s1c.active[t0]
    assert not fills[(sr.CONTROL, sr.BUY)].reached[t0]
    # next_bar moves a bar fill to the next bar's open.
    series, cube, _ = _scene({t0 + 1: {"close": close, "open": np.full(SLOTS, base)}})
    nb = sr.name_fills(series, cube, next_bar=True)[(sr.HOLD_THE_DIP, sr.BUY)]
    assert nb.price[t0] == pytest.approx(cube.open[t0 + 1, 6])
    assert nb.slot[t0] == 5


# The decision-price reference: on a gap-up session the dip is measured
# from close(t), so a 1% wiggle under the open that stays over close(t) x
# 0.99 fills the control at the bar and S1d at the close; a gap of more
# than sigma waits for the close whatever the bars do; a session opening
# under close(t) is the control to the bit.
def test_gap_up_reference_and_the_sigma_guard():
    close_t = 98.0
    sigma = _series(_dates(T), np.full(T, 100.0)).sigma
    series0, _, _ = _scene({}, close_t=close_t)
    s = series0.sigma[t0]
    assert np.isfinite(s)
    assert s > 0
    assert np.isnan(sigma[t0]) is not None
    open_ = close_t * (1.0 + 0.5 * s)  # a gap up inside sigma
    assert open_ > close_t * 1.001
    wiggle = open_ * (1 - fill_timing.DIP) - 0.01
    assert wiggle > close_t * (1 - fill_timing.DIP)
    path = {"close": _path(open_, b2=wiggle), "open": np.full(SLOTS, open_)}
    series, cube, _ = _scene({t0 + 1: path}, close_t=close_t)
    fills = sr.name_fills(series, cube)
    ctrl, s1d = fills[(sr.CONTROL, sr.BUY)], fills[(sr.DECISION_REFERENCE, sr.BUY)]
    assert ctrl.reached[t0]
    assert ctrl.price[t0] == pytest.approx(wiggle)
    assert not s1d.reached[t0]
    assert s1d.price[t0] == pytest.approx(path["close"][-1])
    assert s1d.active[t0]
    assert s1d.slot[t0] == -1
    # A deeper bar, under close(t) x 0.99, fills S1d there.
    deep = dict(path, close=_path(open_, b2=wiggle, b6=close_t * 0.985))
    f2 = sr.name_fills(*_scene({t0 + 1: deep}, close_t=close_t)[:2])
    assert f2[(sr.DECISION_REFERENCE, sr.BUY)].price[t0] == pytest.approx(
        close_t * 0.985
    )
    assert f2[(sr.DECISION_REFERENCE, sr.BUY)].slot[t0] == 6
    assert f2[(sr.CONTROL, sr.BUY)].slot[t0] == 2
    # The sigma guard: opening more than sigma over close(t) waits for the
    # close although the reference level is reached.
    gap = close_t * (1.0 + 1.5 * s)
    guarded = {
        "close": _path(gap, b3=close_t * 0.98),
        "open": np.full(SLOTS, gap),
    }
    f3 = sr.name_fills(*_scene({t0 + 1: guarded}, close_t=close_t)[:2])
    s1d3 = f3[(sr.DECISION_REFERENCE, sr.BUY)]
    assert s1d3.price[t0] == pytest.approx(guarded["close"][-1])
    assert not s1d3.reached[t0]
    assert s1d3.active[t0]
    assert f3[(sr.CONTROL, sr.BUY)].slot[t0] == 3
    # Opening under close(t): the reference is the open, the control to the bit.
    under = {"close": _path(97.0, b1=95.9), "open": np.full(SLOTS, 97.0)}
    f4 = sr.name_fills(*_scene({t0 + 1: under}, close_t=close_t)[:2])
    s1d4, c4 = f4[(sr.DECISION_REFERENCE, sr.BUY)], f4[(sr.CONTROL, sr.BUY)]
    assert s1d4.price[t0] == c4.price[t0]
    assert s1d4.slot[t0] == c4.slot[t0] == 1
    assert not s1d4.active[t0]
    # Without sigma (the first sessions) S1d is unpriced; the control is not.
    assert math.isnan(f4[(sr.DECISION_REFERENCE, sr.BUY)].price[5])
    assert np.isfinite(f4[(sr.CONTROL, sr.BUY)].price[5])


# The market-relative dip: a 1.2% fall with SPY down 0.5% is a 0.7% excess
# fall and does not trigger where the control does; a 0.8% fall with SPY up
# 0.5% is a 1.3% excess fall and triggers where the control does not; a
# name session SPY lacks, or no SPY cube, is the control.
def test_market_relative_trigger_with_and_without_spy():
    base = 100.0
    dates = _dates(T)
    spy_prices = np.full(T, 500.0)
    spy_path = {
        "close": _path(500.0, b2=500.0 * 0.995, b5=500.0 * 1.005),
        "open": np.full(SLOTS, 500.0),
    }
    spy = _cube(dates, spy_prices, paths={t0 + 1: spy_path})
    path = {
        "close": _path(base, b2=base * 0.988, b5=base * 0.992),
        "open": np.full(SLOTS, base),
    }
    series, cube, _ = _scene({t0 + 1: path})
    fills = sr.name_fills(series, cube, spy=spy)
    ctrl, s1e = fills[(sr.CONTROL, sr.BUY)], fills[(sr.MARKET_RELATIVE, sr.BUY)]
    assert ctrl.slot[t0] == 2
    assert ctrl.price[t0] == pytest.approx(base * 0.988)
    assert s1e.slot[t0] == 5
    assert s1e.price[t0] == pytest.approx(base * 0.992)
    assert s1e.reached[t0]
    assert s1e.active[t0]
    # SPY lacking the session, and no SPY at all: the control.
    missing = _cube(dates, spy_prices, drop=(t0 + 1,))
    for index in (missing, None):
        f = sr.name_fills(series, cube, spy=index)[(sr.MARKET_RELATIVE, sr.BUY)]
        assert f.price[t0] == ctrl.price[t0]
        assert f.slot[t0] == 2
        assert not f.active[t0]
    # A flat SPY is the control on every session too.
    flat = sr.name_fills(series, cube, spy=_cube(dates, spy_prices))
    np.testing.assert_allclose(
        flat[(sr.MARKET_RELATIVE, sr.BUY)].price, ctrl.price, equal_nan=True
    )
    assert flat[(sr.MARKET_RELATIVE, sr.BUY)].active[t0]
    # next_bar moves the trigger fill to bar 6's open.
    nb = sr.name_fills(series, cube, spy=spy, next_bar=True)
    assert nb[(sr.MARKET_RELATIVE, sr.BUY)].price[t0] == pytest.approx(
        cube.open[t0 + 1, 6]
    )


# A sell at the level: a bar whose high reaches L before the pop rule fires
# fills at L; the pop rule firing first leaves the control; a session that
# opens through L fills at the open; no level (the close over both) is the
# control; next_bar does not move the limit fill.
def test_a_sell_fills_at_the_level_unless_the_pop_came_first():
    _, _, level = _scene({})
    open_ = 99.0
    pop = open_ * (1 + fill_timing.DIP)
    assert open_ < level < pop
    close = _path(open_, b5=pop + 0.1)
    high = np.maximum(np.r_[close[0], close[:-1]], close)
    high[2] = level + 0.05
    path = {"close": close, "open": np.full(SLOTS, open_), "high": high}
    series, cube, lv = _scene({t0 + 1: path})
    fills = sr.name_fills(series, cube)
    ctrl, s1f = fills[(sr.CONTROL, sr.SELL)], fills[(sr.SELL_AT_LEVEL, sr.SELL)]
    assert ctrl.slot[t0] == 5
    assert ctrl.price[t0] == pytest.approx(pop + 0.1)
    assert s1f.price[t0] == pytest.approx(lv)
    assert s1f.slot[t0] == 2
    assert s1f.reached[t0]
    assert s1f.active[t0]
    assert s1f.tagged[t0]
    assert lab.gain(ctrl.price[t0 : t0 + 1], s1f.price[t0 : t0 + 1], "sell")[0] < 0
    nb = sr.name_fills(series, cube, next_bar=True)
    assert nb[(sr.SELL_AT_LEVEL, sr.SELL)].price[t0] == pytest.approx(lv)
    assert nb[(sr.CONTROL, sr.SELL)].price[t0] == pytest.approx(cube.open[t0 + 1, 6])
    # The pop first (bar 1, under L from a lower open), the level at bar 4:
    # the control's fill stands.
    open2 = 98.5
    pop2 = open2 * (1 + fill_timing.DIP)
    assert pop2 + 0.1 < level
    close2 = _path(open2, b1=pop2 + 0.1)
    high2 = np.maximum(np.r_[close2[0], close2[:-1]], close2)
    high2[4] = level + 0.05
    f2 = sr.name_fills(
        *_scene(
            {t0 + 1: {"close": close2, "open": np.full(SLOTS, open2), "high": high2}}
        )[:2]
    )
    s1f2, c2 = f2[(sr.SELL_AT_LEVEL, sr.SELL)], f2[(sr.CONTROL, sr.SELL)]
    assert s1f2.price[t0] == c2.price[t0] == pytest.approx(pop2 + 0.1)
    assert s1f2.slot[t0] == 1
    assert s1f2.active[t0]
    assert s1f2.tagged[t0]
    # A bar that closes over the pop level traded through L on its way:
    # the resting limit fills at L on that bar, ahead of the control's close.
    close3 = _path(open_, b1=pop + 0.1)
    f3 = sr.name_fills(
        *_scene({t0 + 1: {"close": close3, "open": np.full(SLOTS, open_)}})[:2]
    )
    assert f3[(sr.SELL_AT_LEVEL, sr.SELL)].price[t0] == pytest.approx(level)
    assert (
        f3[(sr.SELL_AT_LEVEL, sr.SELL)].slot[t0]
        == f3[(sr.CONTROL, sr.SELL)].slot[t0]
        == 1
    )
    # Opening through L: the limit fills at the open, bar 0, although the
    # pop rule never fires (the control is the official close).
    through = level + 1.0
    f3 = sr.name_fills(
        *_scene({t0 + 1: {"close": _path(through), "open": np.full(SLOTS, through)}})[
            :2
        ]
    )
    s1f3 = f3[(sr.SELL_AT_LEVEL, sr.SELL)]
    assert s1f3.price[t0] == pytest.approx(through)
    assert s1f3.slot[t0] == 0
    assert not f3[(sr.CONTROL, sr.SELL)].reached[t0]
    # No level: the close over both levels leaves the control.
    f4 = sr.name_fills(*_scene({t0 + 1: path}, close_t=101.0)[:2])
    assert (
        f4[(sr.SELL_AT_LEVEL, sr.SELL)].price[t0] == f4[(sr.CONTROL, sr.SELL)].price[t0]
    )
    assert not f4[(sr.SELL_AT_LEVEL, sr.SELL)].active[t0]
    # The buy side of the same session is untouched by the sell rule.
    assert (sr.SELL_AT_LEVEL, sr.BUY) not in fills


# The store's convention: the panel is split-adjusted and the cube raw. A
# 2-for-1 split between t and t+1 halves the raw bars; the level (adjusted)
# is compared with the scaled bars, so a rejected tag in raw terms is a
# rejected tag, and the fill is its adjusted price.
def test_split_between_t_and_t_plus_one_scales_the_level():
    dates = _dates(T)
    prices = np.full(T, 100.0)
    prices[t0:] = 98.0
    prices[t0 + 1] = 96.0  # the session's official close, agreeing with the cube
    split = np.where(np.arange(T) <= t0, 2.0, 1.0)
    series = _series(dates, prices)  # adjusted, flat then 98
    level = sr.levels(series).level[t0]
    raw_level = level  # after the split raw = adjusted
    first = _path(98.0, b0=97.5, b3=96.9)
    high = np.maximum(np.r_[first[0], first[:-1]], first)
    high[0] = raw_level
    day1 = {"close": first, "open": np.full(SLOTS, 98.0), "high": high, "auction": 96.0}
    cube = _cube(dates, prices * split, paths={t0 + 1: day1})
    np.testing.assert_allclose(lab.cube_scale(series, cube)[t0 + 1], 1.0)
    fills = sr.name_fills(series, cube)
    assert fills[(sr.RESISTANCE_DEFER, sr.BUY)].active[t0]
    assert fills[(sr.RESISTANCE_DEFER, sr.BUY)].price[t0] == pytest.approx(96.0)
    # Before the split raw bars are twice the adjusted price: a session
    # there tags at twice the level and fills at half its raw price.
    t1 = 30
    adjusted = np.full(T, 100.0)
    adjusted[t1] = 98.0
    adjusted[t1 + 1] = 96.0  # the official close 192 on the raw basis, halved
    series_b = _series(dates, adjusted)
    level_b = sr.levels(series_b).level[t1]
    first_b = _path(196.0, b0=195.0, b3=193.8)
    high_b = np.maximum(np.r_[first_b[0], first_b[:-1]], first_b)
    high_b[0] = level_b * 2.0
    day_b = {
        "close": first_b,
        "open": np.full(SLOTS, 196.0),
        "high": high_b,
        "auction": 192.0,
    }
    cube_b = _cube(dates, adjusted * split, paths={t1 + 1: day_b})
    np.testing.assert_allclose(lab.cube_scale(series_b, cube_b)[t1 + 1], 0.5)
    f = sr.name_fills(series_b, cube_b)
    assert f[(sr.RESISTANCE_DEFER, sr.BUY)].active[t1]
    assert f[(sr.RESISTANCE_DEFER, sr.BUY)].price[t1] == pytest.approx(96.0)
    assert f[(sr.CONTROL, sr.BUY)].price[t1] == pytest.approx(96.9)


# A grid where every key fills at `control`, nothing reached.
def _grid(rows, cols, next_bar=False, control=100.0) -> sr.Grid:
    return sr.Grid(
        next_bar=next_bar,
        price={k: np.full((rows, cols), control) for k in sr.KEYS},
        reached={k: np.zeros((rows, cols), dtype=bool) for k in sr.KEYS},
        active={k: np.zeros((rows, cols), dtype=bool) for k in sr.KEYS},
        slot={k: np.full((rows, cols), -1, dtype=np.int64) for k in sr.KEYS},
        wait={k: np.zeros((rows, cols), dtype=np.int64) for k in sr.KEYS},
        tagged={k: np.zeros((rows, cols), dtype=bool) for k in sr.KEYS},
    )


# A market over weekdays from 2023-12-01 with the given grids, grades A+,
# flat closes unless given, the oracle at 98 (buy) and 102 (sell).
def _market(dates, tickers, fills, next_bar=None, closes=None) -> sr.Market:
    rows, cols = len(dates), len(tickers)
    return sr.Market(
        dates=np.asarray(dates, dtype="datetime64[D]"),
        tickers=tuple(tickers),
        fills=fills,
        next_bar=next_bar if next_bar is not None else _grid(rows, cols, next_bar=True),
        oracle={
            "buy": np.full((rows, cols), 98.0),
            "sell": np.full((rows, cols), 102.0),
        },
        oracle_five={s: np.full((rows, cols), np.nan) for s in sr.SIDES},
        grades=np.full((rows, cols), so.A_PLUS),
        closes=np.full((rows, cols), 100.0) if closes is None else np.asarray(closes),
    )


# The book against the control on each side: g per order, 0 where either
# price is missing (counted), the wait from the grid and the drift
# adjustment a buy's g + mu x wait, the tag share, sells priced by S1f
# only; the fill grids from real cubes feed the grid name_fills' prices.
def test_book_accounting_on_both_sides():
    dates = _weekdays(date(2023, 12, 1), 40)
    tickers = ("AAA", "BBB")
    grid = _grid(40, 2)
    skip = (sr.RESISTANCE_SKIP, sr.BUY)
    grid.price[skip][3, 0] = 99.0  # pays less at t+2: +100.5 bp, wait 1
    grid.wait[skip][3, 0] = 1
    grid.active[skip][3, 0] = True
    grid.tagged[skip][3, 0] = True
    grid.reached[skip][3, 0] = True
    grid.slot[skip][3, 0] = 2
    grid.price[skip][5, 1] = np.nan  # unpriced (no t+2)
    grid.tagged[skip][5, 1] = True
    sell = (sr.SELL_AT_LEVEL, sr.SELL)
    grid.price[sell][3, 1] = 101.0  # receives more: +99.5 bp
    grid.active[sell][3, 1] = True
    grid.reached[sell][3, 1] = True
    grid.tagged[sell][3, 1] = True
    grid.price[(sr.CONTROL, sr.SELL)][9, 0] = np.nan
    market = _market(dates, tickers, grid)
    orders = _orders(
        [
            (3, 0, "buy", 0.10),
            (5, 1, "buy", 0.20),
            (7, 0, "buy", 0.05),
            (3, 1, "sell", 0.30),
            (9, 0, "sell", 0.10),
        ],
        tickers,
        start=0,
        stop=40,
    )
    book = sr.price_book(orders, market, "S1b")
    assert len(book.rows) == 3
    assert book.side == "buy"
    expect = 1e4 * np.log(np.array([100 / 99, 1.0, 1.0]))
    np.testing.assert_allclose(book.gain, expect)
    assert book.unpriced.tolist() == [False, True, False]
    assert book.wait.tolist() == [1, 0, 0]
    assert book.acted.tolist() == [True, False, False]
    assert book.tagged.tolist() == [True, False, False]
    assert book.reached.tolist() == [True, False, False]
    assert book.slot.tolist() == [2, -1, -1]
    assert book.column.tolist() == [0, 1, 0]
    mu = 8.0
    np.testing.assert_allclose(sd.drift_adjusted(book, mu), expect + mu * book.wait)
    stats = sr.summarize(book, market.dates, date(2023, 12, 1), date(2024, 1, 1), mu)
    assert stats["orders"] == 3
    assert stats["unpriced"] == 1
    assert stats["retimed"] == 1
    assert stats["waited"] == 1
    assert stats["mean_wait"] == 1.0
    assert stats["tagged"] == 1
    assert stats["tagged_share"] == 0.5
    assert stats["acted_share"] == 0.5
    assert stats["bars"][2] == 1
    series = sd.session_series(book, book.gain)
    assert stats["mean_bp"] == pytest.approx(series[:21].mean())
    assert stats["drift_mean_bp"] == pytest.approx(
        sd.session_series(book, sd.drift_adjusted(book, mu))[:21].mean()
    )
    assert stats["drift_mean_bp"] > stats["mean_bp"]
    assert stats["oracle_bp"] == pytest.approx(1e4 * math.log(100 / 98))
    sells = sr.price_book(orders, market, "S1f")
    assert sells.side == "sell"
    assert len(sells.rows) == 2
    np.testing.assert_allclose(sells.gain, [1e4 * math.log(101 / 100), 0.0])
    assert sells.unpriced.tolist() == [False, True]
    assert sells.oracle[0] == pytest.approx(1e4 * math.log(102 / 100))
    groups = sd.order_groups(orders, np.full(40, np.nan))
    spans = {"w": (date(2023, 12, 1), None)}
    split = sr.splits(sells, groups, market.dates, spans, {"w": mu})
    assert set(split) == {"grade", "detail"}
    assert set(split["grade"]) == set(sd.SELL_GRADES)
    assert split["grade"]["still_a"]["w"]["orders"] == 2
    with pytest.raises(ValueError, match="unknown candidate"):
        sr.price_book(orders, market, "S1z")
    # The grids from real cubes carry name_fills' prices, cell for cell,
    # with SPY threaded through.
    rng = np.random.default_rng(3)
    closes = 100.0 * np.exp(rng.normal(0, 0.02, size=(40, 3)).cumsum(axis=0))
    from backend.tests.test_stage4_decisions import _session_cube

    cubes = {
        t: _session_cube(t, dates, closes[:, j], rng) for j, t in enumerate(tickers)
    }
    spy = _session_cube("SPY", dates, closes[:, 2], rng)
    panel = type("P", (), {})()
    panel.dates, panel.tickers, panel.benchmark = dates, tickers + ("SPY",), "SPY"
    panel.close = panel.adj_close = panel.high = panel.low = closes
    fills, nb, oracle, oracle5, coverage = sr.fill_grids(panel, cubes, spy)
    assert coverage["names_with_cube"] == 2
    assert coverage["spy_sessions"] == 40
    assert nb.next_bar
    assert not fills.next_bar
    series = lab.name_series(
        dates, closes[:, 1], closes[:, 1], closes[:, 1], closes[:, 1]
    )
    own = sr.name_fills(series, cubes["BBB"], spy)
    for key in sr.KEYS:
        np.testing.assert_allclose(
            fills.price[key][:, 1], own[key].price, equal_nan=True
        )
        assert np.array_equal(fills.wait[key][:, 1], own[key].wait)
    assert np.isnan(fills.price[(sr.CONTROL, sr.BUY)][:, 2]).all()  # SPY never priced
    assert np.isfinite(oracle["sell"][20, 1])
    assert oracle5["sell"][20, 1] >= oracle["sell"][20, 1]
    with pytest.raises(ValueError, match="bar-close"):
        sr.build_market(panel, np.zeros((40, 3)), nb, fills, oracle, oracle5)
    market2 = sr.build_market(panel, np.zeros((40, 3)), fills, nb, oracle, oracle5)
    assert market2.tickers == ("AAA", "BBB", "SPY")


# A payload skeleton whose every candidate clears every criterion exactly
# at its edge, for the verdict tests.
def _passing_payload() -> dict:
    stats = {
        "mean_bp": 2.0,
        "hac_t": 2.0,
        "drift_mean_bp": 1.0,
        "drift_hac_t": 2.0,
        "retimed_bp": 20.0,
        "retimed_t": 4.0,
        "orders": 100,
        "retimed": 60,
        "reached_share": 0.4,
        "acted_share": 0.1,
        "tagged_share": 0.2,
        "waited_share": 0.1,
        "capture": 0.3,
    }
    later = dict(stats, mean_bp=0.0)
    results, dsr = {}, {}
    for c in sr.CANDIDATES:
        results[c] = {
            "default": {"model": dict(stats), "2024-2026": dict(later)},
            "next_bar": {"model": dict(stats), "2024-2026": dict(later)},
            "across_offsets": {"positive": 15, "offsets": 20},
        }
        dsr[c] = {"dsr": 0.95, "dsr_cumulative": 0.5, "passes": True}
    return {
        "results": results,
        "deflated": dsr,
        "offsets": {"registered": 20, "priced": 20, "median": 10, "smoke": False},
    }


# The verdict is the adaptive-entry judge: the passing skeleton REPLACES
# all six; a floor moved past its edge is RECORD; real but immaterial
# needs the failed floor and 25 bp at t 3; the lines name the side, the
# fire and tag shares and S1b's wait; the headline keeps both sides.
def test_verdict_lines_and_headline():
    base = _passing_payload()
    record = sr.verdict(base)
    assert record["replaces"] == list(sr.CANDIDATES)
    assert record["immaterial"] == []
    assert record["text"].startswith("REPLACES: S1a, S1b, S1c, S1d, S1e, S1f")
    lines = record["lines"]
    assert len(lines) == 6
    assert lines[0].startswith("S1a (resistance_defer, buy)")
    assert lines[5].startswith("S1f (sell_at_level, sell)")
    assert "fired 10%" in lines[0]
    assert "tagged 20%" in lines[0]
    assert "waited 10%" in lines[1]
    assert "waited" not in lines[0]
    assert "deflated Sharpe +0.95 at N = 7 (+0.50 at 464)" in lines[2]
    assert all(line.endswith("- REPLACES") for line in lines)
    payload = _passing_payload()
    payload["results"]["S1f"]["default"]["model"]["mean_bp"] = 1.0
    payload["results"]["S1f"]["default"]["model"]["retimed_bp"] = 25.0
    payload["results"]["S1f"]["default"]["model"]["retimed_t"] = 3.0
    payload["results"]["S1a"]["across_offsets"]["positive"] = 14
    record = sr.verdict(payload)
    assert record["candidates"]["S1f"]["label"] == sr.IMMATERIAL
    assert record["candidates"]["S1a"]["label"] == sr.RECORD
    assert record["immaterial"] == ["S1f"]
    assert "S1a" not in record["replaces"]
    assert "(kept for the manual book)" in record["text"]
    none = _passing_payload()
    for c in sr.CANDIDATES:
        none["results"][c]["default"]["model"]["mean_bp"] = 0.5
    text = sr.verdict(none)["text"]
    assert text.startswith("RECORD: no fill candidate")
    assert "both sides" in text
    none["offsets"].update(priced=2, smoke=True)
    assert sr.verdict(none)["text"].startswith("SMOKE RUN (2 of 20 offsets)")


# The deflated Sharpe at N = 7 and the cumulative 464 with the six fill
# candidates' across-candidate variance.
def test_deflated_sharpe_at_seven_trials():
    excess = {
        c: {"sharpe": s, "skew": 0.1, "kurtosis": 3.5, "length": 1500}
        for c, s in zip(
            sr.CANDIDATES, (0.12, 0.02, -0.03, 0.05, 0.0, 0.08), strict=True
        )
    }
    record = sr.deflated(excess, "S1a")
    variance = float(np.var([0.12, 0.02, -0.03, 0.05, 0.0, 0.08], ddof=1))
    assert record["trials"] == 7
    assert record["candidates"] == 6
    assert record["trial_variance"] == pytest.approx(variance)
    assert record["dsr"] == pytest.approx(
        candidate_stats.deflated_sharpe(0.12, 1500, 0.1, 3.5, 7, variance)
    )
    assert record["dsr_cumulative"] == pytest.approx(
        candidate_stats.deflated_sharpe(0.12, 1500, 0.1, 3.5, 464, variance)
    )
    # The adaptive-entry default is unchanged.
    three = {c: excess[c] for c in ("S1a", "S1b", "S1c")}
    assert ae.deflated(three, "S1a")["trials"] == 3


# A point-in-time scorecard payload with the rule line's median-offset
# daily returns, per-offset CAGRs, median CAGR and drawdown per window.
def _scorecard(daily: np.ndarray, dates, cagrs, cagr, drawdown, arm="x") -> dict:
    rows = []
    for window, (_lo, _hi) in (
        ("2016-2023", ("2016-01-01", "2024-01-01")),
        ("2024-2026", ("2024-01-01", None)),
    ):
        rows.append(
            {
                "line": sr.NOTCH_RULE_LINE,
                "window": window,
                "cost_bps": 25.0,
                "cagrs": list(cagrs),
                "median_cagr": cagr[window],
                "median_drawdown": drawdown[window],
            }
        )
    return {
        "arm": arm,
        "windows": {
            "2016-2023": ["2016-01-01", "2024-01-01"],
            "2024-2026": ["2024-01-01", None],
        },
        "rows": rows,
        "curves": {
            "25": {
                "offset": 10,
                "dates": [str(d) for d in dates],
                "lines": {sr.NOTCH_RULE_LINE: [float(v) for v in daily]},
            }
        },
    }


# S1g's verdict on two scorecard payloads: the return gate needs +2 bp a
# session at t 2 on 2016-2023, 2024-2026 not negative, 15 of 20 offsets
# and the deflated Sharpe; the drawdown route needs 3 points on both
# windows inside a 1-point CAGR band; a payload short of either is RECORD.
def test_notch_verdict_on_the_return_gate_and_the_drawdown_route():
    rng = np.random.default_rng(9)
    dates = _weekdays(date(2023, 6, 1), 400)
    control_daily = rng.normal(0.0005, 0.01, size=400)
    lift = np.where(dates < np.datetime64("2024-01-01"), 3e-4, 1e-4)
    notch_daily = control_daily + lift + rng.normal(0, 1e-5, size=400)
    cagr = {"2016-2023": 0.20, "2024-2026": 0.30}
    dd = {"2016-2023": -0.30, "2024-2026": -0.25}
    control = _scorecard(control_daily, dates, [0.2] * 20, cagr, dd, "control")
    better = _scorecard(notch_daily, dates, [0.21] * 20, cagr, dd, "notch")
    reading = sr.notch_verdict(control, better, trial_variance=1e-4)
    gate = reading["gate"]
    assert gate["1_floor"]
    assert gate["2_not_negative_2024_2026"]
    assert gate["3_offsets_positive"]
    assert reading["offsets_above"] == 20
    assert reading["paired"]["2016-2023"]["mean_daily_bp"] == pytest.approx(
        3.0, abs=0.1
    )
    assert reading["paired"]["2016-2023"]["hac_t"] > 2
    assert gate["4_deflated_sharpe"]
    assert reading["dsr"] >= 0.95
    assert reading["label"] == sr.REPLACES
    assert reading["replaces_on"] == ["return"]
    assert reading["lines"][0].startswith(
        "S1g (structure notch): paired 2016-2023 +3.0"
    )
    assert reading["lines"][-1].endswith("REPLACES (return)")
    # Without a trial variance the deflated Sharpe is unjudged: RECORD.
    unjudged = sr.notch_verdict(control, better)
    assert not unjudged["gate"]["4_deflated_sharpe"]
    assert unjudged["label"] == sr.RECORD
    assert math.isnan(unjudged["dsr"])
    # Fewer than 15 offsets above: RECORD.
    few = _scorecard(notch_daily, dates, [0.21] * 14 + [0.19] * 6, cagr, dd)
    assert sr.notch_verdict(control, few, 1e-4)["label"] == sr.RECORD
    # The drawdown route: three points better on both windows, CAGR inside
    # a point, with no return edge.
    dd_better = {"2016-2023": -0.269, "2024-2026": -0.22}
    cagr_close = {"2016-2023": 0.205, "2024-2026": 0.292}
    calm = _scorecard(control_daily, dates, [0.2] * 20, cagr_close, dd_better)
    reading = sr.notch_verdict(control, calm, 1e-4)
    assert reading["label"] == sr.REPLACES
    assert reading["replaces_on"] == ["drawdown"]
    assert not reading["gate"]["1_floor"]
    assert reading["drawdown_criterion"]
    assert reading["drawdown"]["2016-2023"]["drawdown_gain"] == pytest.approx(0.031)
    # 2.9 points, or a CAGR 1.1 points away: RECORD.
    short = _scorecard(
        control_daily,
        dates,
        [0.2] * 20,
        cagr_close,
        {"2016-2023": -0.271, "2024-2026": -0.22},
    )
    assert sr.notch_verdict(control, short, 1e-4)["label"] == sr.RECORD
    wide = _scorecard(
        control_daily,
        dates,
        [0.2] * 20,
        {"2016-2023": 0.211, "2024-2026": 0.29},
        dd_better,
    )
    assert sr.notch_verdict(control, wide, 1e-4)["label"] == sr.RECORD
    # A payload without the rule row is refused.
    broken = dict(control, rows=[])
    with pytest.raises(KeyError, match="rule / point-in-time"):
        sr.notch_verdict(broken, better, 1e-4)


# The command end to end on a stub loader: the synthetic book of the
# orders tests with a cube per name and a SPY cube, two of twenty offsets.
# The payload names the plan, the revision and the membership's sha256,
# prices every order of each side at the median offset, carries the
# per-order rows from which the model-window mean, its Newey-West t and
# the per re-timed order mean recompute exactly, and prints one verdict
# line per candidate; without a SPY cube S1e is the control and the
# payload says so; --notch judges two scorecard payloads; bad arguments
# are refused before the desk runs.
def test_command_end_to_end(tmp_path):  # noqa: C901 - one run, read from every side
    import hashlib
    import io as textio
    import json

    from backend.cli import market_structure_rules as cli
    from backend.tests.test_stage4_decisions import _session_cube
    from backend.tests.test_stage4_orders import _history, _report

    report = _report()
    panel = report.panel
    rng = np.random.default_rng(11)
    cubes = {
        t: _session_cube(t, panel.dates, panel.close[:, j], rng)
        for j, t in enumerate(panel.tickers)
        if t != panel.benchmark
    }
    spy = _session_cube("SPY", panel.dates, panel.close[:, panel.index("SPY")], rng)
    history = _history(tmp_path)
    calls = []

    # The stub loader: the synthetic report and its cubes.
    def loader(store, workers, log):
        calls.append(str(store.root))
        return report, cubes, {}

    # The stub SPY loader, and one that has no cube.
    def spy_loader(store, benchmark, log):
        assert benchmark == "SPY"
        return spy

    def no_spy(store, benchmark, log):
        log("no spy")
        return None

    out_path = tmp_path / "out" / "rules.json"
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--offsets",
            "20",
            "--max-offsets",
            "2",
            "--out",
            str(out_path),
        ]
    )
    text = textio.StringIO()
    assert cli.run(args, out=text, loader=loader, spy_loader=spy_loader) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["plan"] == sr.PLAN
    assert payload["study"] == sr.STUDY
    assert payload["offsets"] == {
        "registered": 20,
        "priced": 2,
        "median": 1,
        "smoke": True,
        "starts": [0, 1],
    }
    assert payload["windows"]["model"] == ["2018-01-02", "2024-01-01"]
    assert (
        payload["run"]["inputs"]["membership"]["sha256"]
        == hashlib.sha256(history.read_bytes()).hexdigest()
    )
    assert payload["run"]["cubes"]["names_with_cube"] == 6
    assert payload["run"]["cubes"]["spy_sessions"] == len(panel.dates)
    assert set(payload["results"]) == set(sr.CANDIDATES) == set(payload["deflated"])
    counts = payload["orders"]["median_by_window"]["model"]
    for c, (_, side) in sr.CANDIDATES.items():
        model = payload["results"][c]["default"]["model"]
        assert model["orders"] == counts["buys" if side == "buy" else "sells"] > 0
        assert set(payload["results"][c]["splits"]) == {"grade", "detail"}
        assert set(payload["results"][c]["splits"]["grade"]) == set(
            sd.BUY_GRADES if side == "buy" else sd.SELL_GRADES
        )
        assert sum(model["bars"]) == model["reached"]
        assert 0 <= model["tagged_share"] <= 1 or model["tagged_share"] is None
    assert payload["deflated"]["S1a"]["trials"] == 7
    assert payload["constants"]["TRIALS"] == {"registered": 7, "cumulative": 464}
    assert payload["constants"]["TAG_BAND"] == structure_panel.TAG_BAND
    labels = {c: v["label"] for c, v in payload["verdict"]["candidates"].items()}
    assert set(labels) == set(sr.CANDIDATES)
    printed = text.getvalue()
    assert "SMOKE RUN (2 of 20 offsets)" in printed
    assert printed.count("\n  S1") == 6
    assert "S1f (sell_at_level, sell)" in printed
    assert "SPY cube:" in printed
    assert f"wrote {out_path}" in printed
    assert calls == [str(tmp_path)]
    # The independent recomputation from the rows, per candidate on its
    # side's orders: the model-window mean, its Newey-West t and the per
    # re-timed order mean.
    rows = payload["rows"]
    orders = len(rows["date"])
    assert orders == payload["orders"]["per_offset"][1]["orders"]
    lo, hi = payload["windows"]["model"]
    sessions = [d for d in rows["sessions"] if lo <= d < hi]
    retimed_somewhere = set()
    for c, (_, side) in sr.CANDIDATES.items():
        block = rows["candidates"][c]
        mine = np.array(block["rows"])
        assert block["side"] == side
        assert all(rows["side"][k] == side for k in mine)
        g = np.array([v if v is not None else 0.0 for v in block["g_bp"]])
        assert len(g) == len(mine)
        per = dict.fromkeys(sessions, 0.0)
        for k, v in zip(mine, g, strict=True):
            d = rows["date"][k]
            if lo <= d < hi:
                per[d] += rows["weight"][k] * v
        series = np.array([per[d] for d in sessions])
        ref = payload["results"][c]["default"]["model"]
        assert len(series) == ref["sessions"]
        assert series.mean() == pytest.approx(ref["mean_bp"])
        t = candidate_stats.hac_t(series, 20)
        if ref["hac_t"] is None:
            assert math.isnan(t)
            assert (series == 0).all()
        else:
            assert t == pytest.approx(ref["hac_t"])
            retimed_somewhere.add(c)
        inside = np.array([lo <= rows["date"][k] < hi for k in mine])
        retimed = inside & (g != 0)
        assert int(retimed.sum()) == ref["retimed"]
        if retimed.any():
            assert g[retimed].mean() == pytest.approx(ref["retimed_bp"])
        waits = np.array(block["wait"])
        assert int((inside & (waits > 0)).sum()) == ref["waited"]
    assert retimed_somewhere  # the rules re-time something: not vacuous
    # Without a SPY cube S1e is the control on every order and the payload says so.
    args2 = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--max-offsets",
            "1",
            "--json",
            "--out",
            str(tmp_path / "j.json"),
        ]
    )
    text2 = textio.StringIO()
    assert cli.run(args2, out=text2, loader=loader, spy_loader=no_spy) == 0
    body = text2.getvalue()
    second = json.loads(body[body.index("{") : body.rindex("}") + 1])
    assert second["offsets"]["priced"] == 1
    assert "no spy" in body
    assert second["run"]["cubes"]["spy_sessions"] == 0
    e = second["results"]["S1e"]["default"]["model"]
    assert e["retimed"] == 0
    assert e["acted"] == 0
    # Bad arguments are refused before the desk runs.
    before = len(calls)
    for extra, code in (
        (["--membership", str(tmp_path / "none.csv")], 1),
        (["--offsets", "0"], 2),
    ):
        args = cli.build_parser().parse_args(
            ["--root", str(tmp_path), "--membership", str(history), *extra]
        )
        assert cli.run(args, out=textio.StringIO(), loader=loader) == code
    assert len(calls) == before
    # --notch: two scorecard payloads, the trial variance from this study's
    # payload; the verdict is written beside the notch payload.
    rng = np.random.default_rng(5)
    dates = _weekdays(date(2023, 6, 1), 300)
    daily = rng.normal(0.0005, 0.01, size=300)
    cagr = {"2016-2023": 0.20, "2024-2026": 0.30}
    dd = {"2016-2023": -0.30, "2024-2026": -0.25}
    control = tmp_path / "control.json"
    notch = tmp_path / "notch.json"
    control.write_text(json.dumps(_scorecard(daily, dates, [0.2] * 20, cagr, dd)))
    notch.write_text(json.dumps(_scorecard(daily + 1e-4, dates, [0.21] * 20, cagr, dd)))
    args = cli.build_parser().parse_args(
        ["--notch", str(control), str(notch), "--fills", str(out_path)]
    )
    text3 = textio.StringIO()
    assert cli.run(args, out=text3, loader=loader) == 0
    assert len(calls) == before
    written = json.loads((tmp_path / cli.NOTCH_FILE).read_text(encoding="utf-8"))
    assert written["label"] in (sr.RECORD, sr.REPLACES)
    assert (
        written["inputs"]["fills"]["sha256"]
        == hashlib.sha256(out_path.read_bytes()).hexdigest()
    )
    variance = payload["deflated"]["S1a"]["trial_variance"]
    assert written["trial_variance"] == pytest.approx(variance)
    assert "S1g (structure notch): paired 2016-2023" in text3.getvalue()
    args = cli.build_parser().parse_args(["--notch", str(control), str(tmp_path / "x")])
    assert cli.run(args, out=textio.StringIO()) == 1
