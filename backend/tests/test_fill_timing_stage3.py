"""The stage-3 T-I fill conventions in the fill-timing engine.

What has to hold (docs/research/stage3-plan-2026-09-29.md, "The two
questions" T-I and "Decision tests"):

- On hand-built bars:
  - `<family>_filter` buys at dip_or_close's trigger k* when the forecast
    there is above zero and at the official close when it is not (zero
    vetoes); only the first trigger is read; a trigger at slot 24 or 25
    fills at that close (a late trigger); no trigger fills at the close; a
    NaN at k* inside a vector with forecasts is no veto;
  - `<family>_free` buys at the first slot 0..23 whose forecast is above
    zero, else at the official close;
  - sells mirror;
  - a session with no vector, or an all-NaN one, fills exactly as
    dip_or_close and is counted;
  - `next_bar` moves every bar-close fill (the T-I pair, dip_or_close, the
    dip-rule level conventions, the SR pair) to the next bar's open and a
    fill at slot 25 to the official close; the open, the VWAPs, the close
    and the resting limit do not move.
- Every existing convention prices byte-identically to the engine before
  this change (its arithmetic frozen verbatim below), and the fill-timing
  trial's payload is unchanged with the T-I pair priced beside it.
- The engine reads each order's vector by (name, fill session) through
  `stage3_io.ti_lookup`; filing the forecast one session late moves the
  prices.
- The T-I block: the model window starts at each family's first forecast
  session; orders before it are no-forecast orders; candidate minus
  control per order matches a brute-force recomputation from the bars, its
  t clustered by date.
- A forecast that knows the session's close lets the filter clear the
  floor against dip_or_close; a noise forecast does not.
- The conventions a run prices, the refusals, and the command end to end:
  file paths and sha256 in the payload, the next-bar and seed runs' own
  files, and a verdict read off the runs it wrote.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from backend.cli import market_fill_timing as cli
from backend.market import fill_timing as ft
from backend.market import session_anatomy, sr_levels
from backend.market import stage3_io as s3
from backend.market import stage3_verdict as sv
from backend.market.session_anatomy import json_ready
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.tests import test_fill_timing as base

SLOTS = FULL_SESSION_SLOTS
K = s3.TI_SLOTS


# A hand-built session opening at 100 from its 26 bar closes: each bar
# opens 0.013 above the previous close (so the next bar's open is never the
# bar's own close), highs and lows 0.05 outside, flat volume.
def _row(close, auction: float = math.nan) -> dict:
    close = np.asarray(close, dtype=float)
    opens = np.concatenate([[100.0], close[:-1] + 0.013])
    return {
        "open": opens,
        "high": np.maximum(opens, close) + 0.05,
        "low": np.minimum(opens, close) - 0.05,
        "close": close,
        "volume": np.full(SLOTS, 100.0),
        "auction_open": auction,
    }


# Closes that never reach 99 (the 1% dip) or 101 (the 1% pop): 100.2 rising
# 0.02 a bar.
def _quiet() -> np.ndarray:
    return 100.2 + 0.02 * np.arange(SLOTS)


# A session whose close dips to 98.8 at each of `slots`, nothing else past 1%.
def _dip(*slots: int, auction: float = math.nan) -> dict:
    close = _quiet()
    for s in slots:
        close[s] = 98.8
    return _row(close, auction)


# A session whose close pops to 101.2 at each of `slots`, nothing else past 1%.
def _pop(*slots: int, auction: float = math.nan) -> dict:
    close = _quiet() - 0.4
    for s in slots:
        close[s] = 101.2
    return _row(close, auction)


# A (24,) forecast vector: `fill` everywhere but the given slots.
def _vec(values: dict[int, float] | None = None, fill: float = math.nan) -> np.ndarray:
    out = np.full(K, fill)
    for k, v in (values or {}).items():
        out[k] = v
    return out


# A cube of hand-built sessions on consecutive days.
def _cube_of(rows: list[dict]) -> SessionCube:
    n = len(rows)
    return SessionCube(
        ticker="X",
        dates=np.datetime64("2020-01-02", "D") + np.arange(n),
        open=np.stack([np.asarray(r["open"], dtype=float) for r in rows]),
        high=np.stack([np.asarray(r["high"], dtype=float) for r in rows]),
        low=np.stack([np.asarray(r["low"], dtype=float) for r in rows]),
        close=np.stack([np.asarray(r["close"], dtype=float) for r in rows]),
        volume=np.stack([np.asarray(r["volume"], dtype=float) for r in rows]),
        prior_close=np.full(n, np.nan),
        excluded={},
        auction_open=np.array([float(r["auction_open"]) for r in rows]),
        auction_volume=np.full(n, np.nan),
    )


# A T-I forecast file's rows for every panel name's cube sessions from
# `first` on: one row per (session, slot 0..23) valued fn(cube, i, k),
# dated the cube's session i + shift (shift 1 files each vector one session
# late); seed s's column is the value times (1 + s / 10) plus `seed_bias`.
def _ti_forecast(
    report,
    cubes,
    family: str,
    fn,
    first: int = 0,
    shift: int = 0,
    seed_bias: float = 0.0,
) -> s3.Stage3Forecast:
    days, names, slots, values = [], [], [], []
    for ticker in report.panel.tickers[:-1]:
        cube = cubes[ticker]
        for i in range(first, len(cube) - shift):
            for k in range(K):
                days.append(cube.dates[i + shift])
                names.append(ticker)
                slots.append(k)
                values.append(float(fn(cube, i, k)))
    days = np.array(days, dtype="datetime64[D]")
    names = np.array(names)
    slots = np.array(slots, dtype=np.int8)
    values = np.array(values, dtype=np.float32)
    order = np.lexsort((slots, names, days))
    seeds = np.stack(
        [values * (1.0 + s / 10.0) + seed_bias for s in range(len(s3.SEEDS))], axis=1
    )
    return s3.Stage3Forecast(
        kind=s3.TI,
        family=family,
        dates=days[order],
        tickers=names[order],
        slot=slots[order],
        yhat=values[order],
        yhat_seeds=seeds[order].astype(np.float32),
        yhat_configs=None,
        fold=np.zeros(len(order), dtype=np.int32),
        meta={"model": "synthetic", "family": family},
    )


# The true label of (session i, slot k): 1e4 ln(official close / bar k's close).
def _truth(cube: SessionCube, i: int, k: int) -> float:
    official = float(ft._official_close(cube)[i])
    return 1e4 * math.log(official / float(cube.close[i, k]))


# A noise forecast: a fixed draw per (ticker, session, slot), independent of
# the loop order, from a seed.
def _noise(seed: int):
    cache: dict[str, np.ndarray] = {}

    # The draw for (cube, i, k).
    def draw(cube: SessionCube, i: int, k: int) -> float:
        if cube.ticker not in cache:
            offset = sum(ord(c) for c in cube.ticker)
            cache[cube.ticker] = np.random.default_rng(seed * 1000 + offset).normal(
                0.0, 30.0, size=(len(cube), K)
            )
        return float(cache[cube.ticker][i, k])

    return draw


# The stage-3 constants: four conventions, two families, the board's rule
# as the control, the model window's end, the plan's numbers.
def test_ti_constants_are_the_plans():
    assert ft.TI_CONVENTIONS == ("lgbm_filter", "lgbm_free", "seq_filter", "seq_free")
    assert ft.TI_FAMILIES == ("lgbm", "seq")
    assert {c: (r.family, r.rule) for c, r in ft.TI_RULES.items()} == {
        "lgbm_filter": ("lgbm", "filter"),
        "lgbm_free": ("lgbm", "free"),
        "seq_filter": ("seq", "filter"),
        "seq_free": ("seq", "free"),
    }
    assert ft.TI_CONTROL == "dip_or_close" == ft.LEVEL_CONTROL
    assert date(2024, 1, 1) == ft.TI_MODEL_END
    assert ft.TI_WINDOWS == ("model", "2016-2023", "2024-2026")
    assert ft.PRICEABLE == ft.KNOWN_CONVENTIONS + ft.TI_CONVENTIONS
    assert set(ft.TI_CONVENTIONS) <= set(ft.WAITING)
    assert ft.TI_CONVENTIONS == sv.TI_CANDIDATES
    assert ft.DIP == 0.01 and K == 24
    assert (s3.FLOOR_BP, s3.FLOOR_T, s3.HAC_LAG, s3.OUTER_CANDIDATES) == (
        2.0,
        2.0,
        20,
        8,
    )


# The filter on hand-built buys: the board's trigger at slot 5 stands when
# the forecast there is above zero and waits for the official close when
# it is below or at zero; only the first trigger is read; a NaN at the
# trigger is no veto; a trigger at 24 or 25 fills as dip_or_close; no
# trigger fills at the close; no forecast is dip_or_close exactly.
def test_filter_buys_on_hand_built_paths():
    for convention in ("lgbm_filter", "seq_filter"):
        row = _dip(5)
        last = row["close"][-1]
        assert (
            ft.fill_price(row, convention, "buy", yhat=_vec({5: 3.0}, fill=-1.0))
            == 98.8
        )
        for veto in (-3.0, 0.0):
            assert (
                ft.fill_price(row, convention, "buy", yhat=_vec({5: veto}, fill=1.0))
                == last
            )
            assert (
                ft.fill_price(
                    _dip(5, auction=100.9), convention, "buy", yhat=_vec({5: veto})
                )
                == 100.9
            )
        # A veto at the first trigger is not rescued by a later dip the model likes.
        assert (
            ft.fill_price(_dip(5, 9), convention, "buy", yhat=_vec({5: -1.0, 9: 5.0}))
            == last
        )
        # A NaN at k* inside a vector with forecasts is no veto.
        assert (
            ft.fill_price(row, convention, "buy", yhat=_vec({4: -2.0, 6: -2.0})) == 98.8
        )
        # A trigger after 15:30 has no forecast slot and fills as dip_or_close.
        for late in (24, 25):
            late_row = _dip(late, auction=100.9)
            assert (
                ft.fill_price(late_row, convention, "buy", yhat=_vec(fill=-5.0)) == 98.8
            )
            assert ft.fill_price(late_row, "dip_or_close", "buy") == 98.8
        # No trigger: the official close, whatever the model says.
        quiet = _row(_quiet(), 100.9)
        assert ft.fill_price(quiet, convention, "buy", yhat=_vec(fill=9.0)) == 100.9
        assert (
            ft.fill_price(_row(_quiet()), convention, "buy", yhat=_vec(fill=9.0))
            == (_quiet()[-1])
        )
        # No forecast (all NaN): exactly dip_or_close, both sides.
        for side in ("buy", "sell"):
            for r in (
                row,
                _dip(5, auction=100.9),
                quiet,
                _pop(7),
                _pop(7, auction=99.1),
            ):
                assert ft.fill_price(r, convention, side, yhat=_vec()) == ft.fill_price(
                    r, "dip_or_close", side
                )
        with pytest.raises(ValueError, match="needs the T-I forecast"):
            ft.fill_price(row, convention, "buy")


# The free rule on hand-built buys: the first slot whose forecast is above
# zero (NaN, negatives and zero skipped); none above zero is the official
# close; slot 23 is the last it can pick; the 1% trigger plays no part; no
# forecast is dip_or_close.
def test_free_buys_at_the_first_agreeing_slot():
    for convention in ("lgbm_free", "seq_free"):
        row = _row(_quiet(), 100.9)
        close = row["close"]
        yhat = _vec({0: -1.0, 2: -2.0, 3: 0.0, 4: 0.5, 6: 3.0})
        assert ft.fill_price(row, convention, "buy", yhat=yhat) == close[4]
        assert (
            ft.fill_price(row, convention, "buy", yhat=_vec({3: 0.0}, fill=-1.0))
            == 100.9
        )
        assert (
            ft.fill_price(row, convention, "buy", yhat=_vec({23: 1.0}, fill=-1.0))
            == close[23]
        )
        dipped = _dip(2, auction=100.9)
        assert (
            ft.fill_price(dipped, convention, "buy", yhat=_vec({7: 1.0}, fill=-1.0))
            == dipped["close"][7]
        )
        assert ft.fill_price(dipped, convention, "buy", yhat=_vec()) == 98.8
        assert ft.fill_price(row, convention, "buy", yhat=_vec()) == 100.9


# Sells mirror: the filter sells at the 1% pop when the forecast there is
# below zero and waits for the close when it is above or at zero; a pop at
# slot 25 fills as dip_or_close; a dip never triggers a sell; the free rule
# sells at the first slot whose forecast is below zero.
def test_sells_mirror():
    for family in ("lgbm", "seq"):
        popped = _pop(7, auction=99.5)
        assert (
            ft.fill_price(
                popped, f"{family}_filter", "sell", yhat=_vec({7: -2.0}, fill=5.0)
            )
            == 101.2
        )
        for veto in (2.0, 0.0):
            assert (
                ft.fill_price(
                    popped, f"{family}_filter", "sell", yhat=_vec({7: veto}, fill=-5.0)
                )
                == 99.5
            )
        assert (
            ft.fill_price(
                _pop(25, auction=99.5), f"{family}_filter", "sell", yhat=_vec(fill=5.0)
            )
            == 101.2
        )
        assert (
            ft.fill_price(
                _dip(5, auction=99.5), f"{family}_filter", "sell", yhat=_vec(fill=-5.0)
            )
            == 99.5
        )
        quiet = _row(_quiet() - 0.4, 99.5)
        assert (
            ft.fill_price(
                quiet, f"{family}_free", "sell", yhat=_vec({1: 1.0, 3: -0.2, 8: -4.0})
            )
            == quiet["close"][3]
        )
        assert (
            ft.fill_price(quiet, f"{family}_free", "sell", yhat=_vec(fill=1.0)) == 99.5
        )
        assert ft.fill_price(popped, f"{family}_free", "sell", yhat=_vec()) == 101.2


# The per-session flags on a six-session cube: which orders filled at a bar
# before the close, which filter triggers were late, which sessions had no
# forecast; `waiting_fills` carries the same three; with next_bar a fill
# at slot 25 goes to the official close and is no longer before it.
def test_ti_fills_flag_fills_late_triggers_and_missing_forecasts():
    rows = [
        _dip(5),
        _dip(5, auction=100.9),
        _dip(24),
        _dip(25, auction=100.9),
        _row(_quiet()),
        _dip(5),
    ]
    yhat = np.stack(
        [
            _vec({5: 1.0}),
            _vec({5: -1.0}),
            _vec(fill=-1.0),
            _vec(fill=-1.0),
            _vec(fill=1.0),
            _vec(),
        ]
    )
    cube = _cube_of(rows)
    fills = ft.ti_fills(cube, "lgbm_filter", "buy", yhat)
    np.testing.assert_array_equal(
        fills.price, [98.8, 100.9, 98.8, 98.8, _quiet()[-1], 98.8]
    )
    np.testing.assert_array_equal(fills.hit, [True, False, True, True, False, True])
    np.testing.assert_array_equal(fills.late, [False, False, True, True, False, False])
    np.testing.assert_array_equal(fills.no_forecast, [False] * 5 + [True])
    price, hit, missing = ft.waiting_fills(cube, "lgbm_filter", "buy", yhat=yhat)
    assert price.tobytes() == fills.price.tobytes()
    np.testing.assert_array_equal(hit, fills.hit)
    np.testing.assert_array_equal(missing, fills.no_forecast)
    after = ft.ti_fills(cube, "lgbm_filter", "buy", yhat, next_bar=True)
    opens = cube.open
    np.testing.assert_array_equal(
        after.price,
        [opens[0, 6], 100.9, opens[2, 25], 100.9, _quiet()[-1], opens[5, 6]],
    )
    np.testing.assert_array_equal(after.hit, [True, False, True, False, False, True])
    np.testing.assert_array_equal(after.late, fills.late)
    free = ft.ti_fills(cube, "lgbm_free", "buy", yhat)
    assert not free.late.any()
    np.testing.assert_array_equal(free.no_forecast, fills.no_forecast)
    with pytest.raises(ValueError, match="forecast vectors have shape"):
        ft.ti_fills(cube, "lgbm_free", "buy", yhat[:, :5])
    with pytest.raises(ValueError, match="not a stage-3 T-I convention"):
        ft.ti_fills(cube, "dip_or_close", "buy", yhat)
    with pytest.raises(ValueError, match="side must be"):
        ft.ti_fills(cube, "lgbm_free", "hold", yhat)


# next_bar moves every fill made at a bar close to the next bar's open: the
# T-I pair, dip_or_close, the dip-rule level conventions and the SR pair; a
# fill at slot 25 goes to the official close, one at slot 24 to bar 25's
# open. The open, the VWAPs, the official close, the band gate and the
# resting limit are not bar-close fills and do not move.
def test_next_bar_moves_every_bar_close_fill():
    row = _dip(5, auction=100.9)
    opens = row["open"]
    assert ft.fill_price(row, "dip_or_close", "buy") == 98.8
    assert ft.fill_price(row, "dip_or_close", "buy", next_bar=True) == opens[6]
    for convention in ft.TI_CONVENTIONS:
        yhat = _vec({5: 1.0}, fill=-1.0)
        assert ft.fill_price(row, convention, "buy", yhat=yhat) == 98.8
        assert (
            ft.fill_price(row, convention, "buy", yhat=yhat, next_bar=True) == opens[6]
        )
    late = _dip(24, auction=100.9)
    assert ft.fill_price(late, "dip_or_close", "buy", next_bar=True) == late["open"][25]
    last = _dip(25, auction=100.9)
    assert ft.fill_price(last, "dip_or_close", "buy") == 98.8
    assert ft.fill_price(last, "dip_or_close", "buy", next_bar=True) == 100.9
    assert (
        ft.fill_price(last, "seq_filter", "buy", yhat=_vec(fill=-1.0), next_bar=True)
        == 100.9
    )
    popped = _pop(7, auction=99.5)
    assert (
        ft.fill_price(popped, "dip_or_close", "sell", next_bar=True)
        == popped["open"][8]
    )
    # The dip-rule level conventions (sigma 2%: the level is 1% under the open).
    for convention in ("vol_dip_0.5", "trail_dip"):
        deep = _dip(6, auction=100.9)
        assert ft.fill_price(deep, convention, "buy", sig=0.02) == 98.8
        assert (
            ft.fill_price(deep, convention, "buy", sig=0.02, next_bar=True)
            == deep["open"][7]
        )
    # The SR pair: a support zone at slot 5 under the open.
    support = np.zeros(SLOTS, dtype=np.int64)
    support[5] = 2
    zones = sr_levels.CloseZones(support, np.zeros(SLOTS, dtype=np.int64))
    for convention in ft.SR_CONVENTIONS:
        assert ft.fill_price(row, convention, "buy", zones=zones) == 98.8
        assert (
            ft.fill_price(row, convention, "buy", zones=zones, next_bar=True)
            == opens[6]
        )
    # Not bar-close fills: unchanged.
    through = _dip(5, auction=100.9)
    through["low"][4] = 90.0
    for side in ("buy", "sell"):
        for convention in (*ft.CONVENTIONS, "vol_limit_0.5"):
            if convention == "dip_or_close":
                continue
            kwargs = {"sig": 0.02} if convention == "vol_limit_0.5" else {}
            assert ft.fill_price(through, convention, side, **kwargs) == ft.fill_price(
                through, convention, side, next_bar=True, **kwargs
            ), (convention, side)


# The engine's fill arithmetic before the stage-3 change, frozen verbatim
# from fill_timing at 40639a77 (with the frozen constants written out):
# every existing convention must price exactly as it did.
_FROZEN_DIP = 0.01
_FROZEN_LEVELS = {
    "vol_dip_0.5": ("dip", 0.5),
    "vol_dip_1.0": ("dip", 1.0),
    "vol_limit_0.5": ("limit", 0.5),
    "trail_dip": ("dip", 0.5),
}
_FROZEN_SR = {"level_dip": 1, "level_dip_confluence": 2}
_FROZEN_WAITING = ("dip_or_close", *_FROZEN_LEVELS, *_FROZEN_SR)


# Frozen: the official close.
def _frozen_official_close(cube):
    last = cube.close[:, SLOTS - 1]
    auction = np.asarray(cube.auction_open, dtype=float)
    return np.where(np.isfinite(auction), auction, last)


# Frozen: the first bar close at or past a level, else the official close.
def _frozen_first_close_past(cube, side, level):
    if side == "buy":
        hit = cube.close <= level[:, None]
    else:
        hit = cube.close >= level[:, None]
    any_hit = hit.any(axis=1)
    first = np.argmax(hit, axis=1)
    picked = cube.close[np.arange(len(cube)), first]
    return np.where(any_hit, picked, _frozen_official_close(cube)), any_hit


# Frozen: dip_or_close's fill and whether the dip was reached.
def _frozen_dip_or_close_fill(cube, side):
    open0 = cube.open[:, 0]
    level = (
        open0 * (1.0 - _FROZEN_DIP) if side == "buy" else open0 * (1.0 + _FROZEN_DIP)
    )
    return _frozen_first_close_past(cube, side, level)


# Frozen: the resting limit.
def _frozen_resting_limit(cube, side, level):
    if side == "buy":
        hit = (cube.low < level[:, None]).any(axis=1)
    else:
        hit = (cube.high > level[:, None]).any(axis=1)
    return np.where(hit, level, _frozen_official_close(cube)), hit


# Frozen: the level k sigma from the open.
def _frozen_entry_level(open0, sig, k, side):
    sign = -1.0 if side == "buy" else 1.0
    return np.asarray(open0, dtype=float) * np.exp(
        sign * k * np.asarray(sig, dtype=float)
    )


# Frozen: the SR fill.
def _frozen_sr_fills(cube, convention, side, zones):
    grid = np.asarray(zones.support if side == "buy" else zones.resistance)
    open0 = cube.open[:, :1]
    beyond = cube.close < open0 if side == "buy" else cube.close > open0
    late_enough = np.arange(SLOTS) >= sr_levels.FIRST_SLOT
    hit = (grid >= _FROZEN_SR[convention]) & beyond & late_enough[None, :]
    any_hit = hit.any(axis=1)
    first = np.argmax(hit, axis=1)
    picked = cube.close[np.arange(len(cube)), first]
    return np.where(any_hit, picked, _frozen_official_close(cube)), any_hit


# Frozen: the waiting conventions' fill, reached flag and no-sigma flag.
def _frozen_waiting_fills(cube, convention, side, sig=None, zones=None):
    if convention in _FROZEN_SR:
        price, hit = _frozen_sr_fills(cube, convention, side, zones)
        return price, hit, np.zeros(len(cube), dtype=bool)
    base_price, base_hit = _frozen_dip_or_close_fill(cube, side)
    if convention == "dip_or_close":
        return base_price, base_hit, np.zeros(len(cube), dtype=bool)
    rule, k = _FROZEN_LEVELS[convention]
    sig = np.asarray(sig, dtype=float)
    no_sigma = ~(np.isfinite(sig) & (sig > 0))
    level = _frozen_entry_level(cube.open[:, 0], np.where(no_sigma, 0.0, sig), k, side)
    if rule == "dip":
        price, hit = _frozen_first_close_past(cube, side, level)
    else:
        price, hit = _frozen_resting_limit(cube, side, level)
    return (
        np.where(no_sigma, base_price, price),
        np.where(no_sigma, base_hit, hit),
        no_sigma,
    )


# Frozen: every convention's session prices.
def _frozen_session_prices(cube, convention, side, sig=None, zones=None):
    if len(cube) == 0:
        return np.zeros(0)
    if convention in _FROZEN_LEVELS or convention in _FROZEN_SR:
        return _frozen_waiting_fills(cube, convention, side, sig, zones)[0]
    if convention in ("next_open", "breakout_gate"):
        return np.asarray(cube.open[:, 0], dtype=float)
    if convention == "first_hour_vwap":
        return session_anatomy._vwap(cube.close[:, :4], cube.volume[:, :4])
    if convention == "session_vwap":
        return session_anatomy._vwap(cube.close, cube.volume)
    if convention == "next_close":
        return _frozen_official_close(cube)
    if convention == "dip_or_close":
        return _frozen_dip_or_close_fill(cube, side)[0]
    if convention == "late_day":
        slots = [22, 23, 24, 25]
        return session_anatomy._vwap(cube.close[:, slots], cube.volume[:, slots])
    raise ValueError(convention)


# Frozen: the panel-aligned prices and detail of one convention.
def _frozen_cube_prices(cubes, panel, convention, sig=None, zones=None):
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    rows, names = panel.adj_close.shape
    buy = np.full((rows, names), np.nan)
    sell = np.full((rows, names), np.nan)
    available = np.zeros((rows, names), dtype=bool)
    waiting = convention in _FROZEN_WAITING
    hits = {side: np.zeros((rows, names), dtype=bool) for side in ("buy", "sell")}
    gains = {side: np.full((rows, names), np.nan) for side in ("buy", "sell")}
    no_sigma = np.zeros((rows, names), dtype=bool)
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None or len(cube) == 0:
            continue
        pos, ok, per_session = ft.session_scale(cube, dates, panel.adj_close[:, j])
        scale = per_session[ok]
        if not waiting:
            buy[pos[ok], j] = (
                _frozen_session_prices(cube, convention, "buy")[ok] * scale
            )
            sell[pos[ok], j] = (
                _frozen_session_prices(cube, convention, "sell")[ok] * scale
            )
            available[pos[ok], j] = np.isfinite(scale)
            continue
        cube_sig = None
        if convention in _FROZEN_LEVELS:
            cube_sig = np.full(len(cube), np.nan)
            cube_sig[ok] = np.asarray(sig, dtype=float)[pos[ok], j]
        cube_zones = zones.get(ticker) if convention in _FROZEN_SR else None
        close = _frozen_official_close(cube)
        for side, out in (("buy", buy), ("sell", sell)):
            price, hit, missing = _frozen_waiting_fills(
                cube, convention, side, cube_sig, cube_zones
            )
            out[pos[ok], j] = price[ok] * scale
            hits[side][pos[ok], j] = hit[ok]
            with np.errstate(all="ignore"):
                better = (close - price) if side == "buy" else (price - close)
                gain = np.where(close > 0, better / close * 1e4, np.nan)
            gains[side][pos[ok], j] = gain[ok]
            no_sigma[pos[ok], j] |= missing[ok]
        available[pos[ok], j] = np.isfinite(scale)
    detail = (hits["buy"], hits["sell"], gains["buy"], gains["sell"], no_sigma)
    return buy, sell, available, detail if waiting else None


# Assert every existing convention prices one cube's sessions as the frozen
# engine did, byte for byte, both sides, with next_bar left out and passed
# False; and that the waiting conventions' reached and no-sigma flags match.
def _assert_sessions_unchanged(cube: SessionCube, sig: np.ndarray, zones) -> None:
    for convention in ft.KNOWN_CONVENTIONS:
        own_sig = sig if convention in ft.LEVELS else None
        own_zones = zones if convention in ft.SR_CONVENTIONS else None
        for side in ("buy", "sell"):
            frozen = _frozen_session_prices(cube, convention, side, own_sig, own_zones)
            for kwargs in ({}, {"next_bar": False}):
                ours = ft.session_prices(
                    cube, convention, side, own_sig, own_zones, **kwargs
                )
                assert ours.tobytes() == frozen.tobytes(), (convention, side)
            if convention in ft.WAITING:
                old = _frozen_waiting_fills(cube, convention, side, own_sig, own_zones)
                new = ft.waiting_fills(cube, convention, side, own_sig, own_zones)
                for a, b in zip(new, old, strict=True):
                    assert a.tobytes() == b.tobytes(), (convention, side)


# Every existing convention prices each session byte-identically to the
# frozen engine, on cubes that drift, dip and lack auction prints, with
# sigmas that are missing, zero, negative or infinite and random zones.
def test_existing_session_prices_are_byte_identical():
    _, _, cubes = base._world(t=200, n=6, seed=8)
    _, _, dipped = base._world(t=90, n=4, seed=9, shape="dip", dip=0.02)
    holes = {}
    for ticker, cube in dipped.items():
        auction = cube.auction_open.copy()
        auction[::3] = np.nan
        holes[ticker] = replace(cube, auction_open=auction)
    rng = np.random.default_rng(3)
    for cube in [*cubes.values(), *dipped.values(), *holes.values()]:
        sig = rng.uniform(0.002, 0.03, size=len(cube))
        sig[::5] = np.nan
        sig[1::7] = 0.0
        sig[2::11] = -0.01
        sig[3::13] = np.inf
        support = rng.integers(0, 3, size=(len(cube), SLOTS))
        resistance = rng.integers(0, 3, size=(len(cube), SLOTS))
        _assert_sessions_unchanged(cube, sig, sr_levels.CloseZones(support, resistance))


# Every existing convention's panel-aligned prices, availability and
# waiting detail are byte-identical to the frozen engine's, with the
# volatility grid and the SR zones the engine builds, and carry no late
# flags.
def test_existing_cube_prices_are_byte_identical():
    report, _, cubes = base._world(t=200, n=6, seed=8)
    rng = np.random.default_rng(3)
    panel = report.panel
    grid = np.log(rng.uniform(0.002, 0.03, size=panel.adj_close.shape)) * 2.0
    grid[::4] = np.nan
    aligned = ft.Aligned(
        np.asarray(panel.dates, dtype="datetime64[D]"),
        tuple(panel.tickers),
        grid,
        grid.copy(),
        None,
    )
    zones = ft.sr_zones(cubes, panel)
    for convention in ft.KNOWN_CONVENTIONS:
        sig = ft.fill_sigma(aligned, convention) if convention in ft.LEVELS else None
        own_zones = zones if convention in ft.SR_CONVENTIONS else None
        ours = ft.cube_prices(cubes, panel, convention, sig, own_zones)
        buy, sell, available, detail = _frozen_cube_prices(
            cubes, panel, convention, sig, own_zones
        )
        assert ours.buy.tobytes() == buy.tobytes(), convention
        assert ours.sell.tobytes() == sell.tobytes(), convention
        assert ours.available.tobytes() == available.tobytes(), convention
        if detail is None:
            assert ours.detail is None
            continue
        fields = (
            ours.detail.buy_hit,
            ours.detail.sell_hit,
            ours.detail.buy_gain_bp,
            ours.detail.sell_gain_bp,
            ours.detail.no_sigma,
        )
        for a, b in zip(fields, detail, strict=True):
            assert a.tobytes() == b.tobytes(), convention
        assert ours.detail.buy_late is None and ours.detail.sell_late is None


# The fill-timing trial's payload is unchanged with the T-I pair priced
# beside it: every row of the seven, the best, the verdict and the gap are
# the same; a run without T-I conventions carries no T-I block and no
# next-bar flag; one with them says it is not a next-bar run.
def test_payloads_are_unchanged_beside_the_ti_conventions():
    report, mask, cubes = base._world(t=200, n=6, seed=8)
    plain = ft.study(report, cubes, mask, offsets=3)
    ti = {
        family: ft.ti_forecast(_ti_forecast(report, cubes, family, _noise(i), first=40))
        for i, family in enumerate(ft.TI_FAMILIES)
    }
    both = ft.study(
        report,
        cubes,
        mask,
        offsets=3,
        conventions=ft.CONVENTIONS + ft.TI_CONVENTIONS,
        ti_forecasts=ti,
    )
    assert "stage3_ti" not in plain and "next_bar" not in plain
    assert both["next_bar"] is False
    assert both["conventions"] == list(ft.CONVENTIONS + ft.TI_CONVENTIONS)
    by_key = {(r["convention"], r["window"]): r for r in both["rows"]}
    for r in plain["rows"]:
        twin = by_key[(r["convention"], r["window"])]
        assert json.dumps(json_ready(twin), sort_keys=True) == json.dumps(
            json_ready(r), sort_keys=True
        )
    for key in (
        "best",
        "verdict",
        "adopted",
        "criteria",
        "breakout_gate",
        "simulator_gap",
    ):
        assert json.dumps(json_ready(both[key]), sort_keys=True) == json.dumps(
            json_ready(plain[key]), sort_keys=True
        )
    assert set(both["criteria"]) == set(ft.CONVENTIONS) - {"next_open"}


# The engine reads each order's vector by (name, fill session) through the
# saved file's `stage3_io.ti_lookup`: cube_prices is `ti_fills` on the
# looked-up vectors times the split-safe scale, exactly; the detail flags
# follow; and the same file dated one session late gives other prices.
def test_cube_prices_read_the_fill_session_vector(tmp_path):
    factor = np.array([1.0, 0.5, 2.0, 0.9, 1.0])
    report, _, cubes = base._world(t=120, n=5, seed=4, factor=factor[None, :])
    panel = report.panel
    forecast = _ti_forecast(report, cubes, s3.LGBM, _noise(7), first=10)
    loaded = s3.load_forecast(s3.save_forecast(tmp_path / "ti.npz", forecast))
    lookup = s3.ti_lookup(loaded)
    ti = ft.ti_forecast(loaded)
    late = ft.ti_forecast(
        _ti_forecast(report, cubes, s3.LGBM, _noise(7), first=10, shift=1)
    )
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    for convention in ("lgbm_filter", "lgbm_free"):
        prices = ft.cube_prices(cubes, panel, convention, ti=ti.lookup)
        moved = ft.cube_prices(cubes, panel, convention, ti=late.lookup)
        assert not np.array_equal(prices.buy, moved.buy, equal_nan=True)
        for j, ticker in enumerate(panel.tickers[:-1]):
            cube = cubes[ticker]
            pos, ok, scale = ft.session_scale(cube, dates, panel.adj_close[:, j])
            vectors = np.stack(
                [
                    lookup.get((ticker, np.datetime64(d, "D")), np.full(K, np.nan))
                    for d in cube.dates
                ]
            )
            np.testing.assert_array_equal(
                ft.ti_grid(ti.lookup, ticker, cube.dates), vectors
            )
            for side, grid, hits in (
                ("buy", prices.buy, prices.detail.buy_hit),
                ("sell", prices.sell, prices.detail.sell_hit),
            ):
                fills = ft.ti_fills(cube, convention, side, vectors)
                assert (
                    grid[pos[ok], j].tobytes()
                    == (fills.price[ok] * scale[ok]).tobytes()
                )
                np.testing.assert_array_equal(hits[pos[ok], j], fills.hit[ok])
            np.testing.assert_array_equal(
                prices.detail.no_sigma[pos[ok], j], np.arange(len(cube))[ok] < 10
            )
        with pytest.raises(ValueError, match="T-I forecast lookup"):
            ft.cube_prices(cubes, panel, convention)


# A seed column reads that column of `yhat_seeds`; the forecast is refused
# for another question or family and for a column the file lacks; the
# first session and the coverage count only vectors with a forecast, and a
# partial vector is counted.
def test_ti_forecast_helpers():
    report, _, cubes = base._world(t=40, n=3, seed=2)
    forecast = _ti_forecast(report, cubes, s3.SEQ, _noise(1), first=5, seed_bias=1.0)
    ensemble = ft.ti_forecast(forecast, identity={"file": "x.npz"})
    third = ft.ti_forecast(forecast, seed_column=3)
    assert ensemble.identity == {"file": "x.npz", "family": "seq", "seed_column": None}
    assert third.identity["seed_column"] == 3
    key = next(iter(ensemble.lookup))
    np.testing.assert_allclose(
        third.lookup[key],
        ensemble.lookup[key].astype(np.float32) * 1.3 + 1.0,
        rtol=1e-6,
    )
    for bad in (5, -1):
        with pytest.raises(ValueError, match="seed column"):
            ft.ti_forecast(forecast, seed_column=bad)
    with pytest.raises(ValueError, match="T-I forecast is needed"):
        ft.ti_forecast(replace(forecast, kind=s3.S1))
    with pytest.raises(ValueError, match="not one of"):
        ft.ti_forecast(replace(forecast, family=s3.CNN_I5))
    dates = report.panel.dates
    assert ft.ti_first_session(ensemble.lookup) == dates[5].astype(object)
    lookup = dict(ensemble.lookup)
    first_key = min(lookup, key=lambda k: k[1])
    lookup[first_key] = np.full(K, np.nan)
    partial = next(k for k in lookup if k != first_key)
    lookup[partial] = lookup[partial].copy()
    lookup[partial][3] = np.nan
    coverage = ft.ti_coverage(lookup)
    assert coverage["vectors"] == len(lookup)
    assert coverage["vectors_with_forecast"] == len(lookup) - 1
    assert coverage["partial_vectors"] == 1
    assert coverage["last_forecast_session"] == str(dates[-1])
    assert (
        ft.ti_first_session({("A", np.datetime64("2020-01-02")): np.full(K, np.nan)})
        is None
    )


# The conventions a run prices: the T-I pair of each family whose forecast
# is given (with dip_or_close and next_open), by default or by name; the
# old defaults unchanged; refused: a T-I convention without its family's
# forecast, a forecast none of whose conventions is priced, an unknown
# family or convention.
def test_select_conventions_with_ti_families():
    assert ft.select_conventions(None, False) == ft.CONVENTIONS
    assert ft.select_conventions(None, True) == ft.ALL_CONVENTIONS
    assert ft.select_conventions(["lgbm_filter"], False, ["lgbm"]) == (
        "next_open",
        "dip_or_close",
        "lgbm_filter",
    )
    assert ft.select_conventions(None, False, ["seq"]) == ft.CONVENTIONS + (
        "seq_filter",
        "seq_free",
    )
    assert ft.select_conventions(
        ["seq_filter", "lgbm_free", "dip_or_close"], False, ["lgbm", "seq"]
    ) == ("next_open", "dip_or_close", "lgbm_free", "seq_filter")
    for only, families, message in (
        (["seq_free"], ["lgbm"], "need their family's forecast"),
        (["lgbm_filter"], [], "need their family's forecast"),
        (["lgbm_filter"], ["lgbm", "seq"], "none of its conventions is priced"),
        (["lgbm_filter"], ["lgbm", "cnn_i5"], "unknown T-I family"),
        (["tea_leaves"], ["lgbm"], "unknown convention"),
    ):
        with pytest.raises(ValueError, match=message):
            ft.select_conventions(only, False, families)


# `study` refuses a forecast in the wrong family's slot and two families
# read at different seed columns.
def test_study_refuses_mismatched_ti_inputs():
    report, mask, cubes = base._world(t=60, n=4, seed=1)
    lgbm = _ti_forecast(report, cubes, s3.LGBM, _noise(1))
    seq = _ti_forecast(report, cubes, s3.SEQ, _noise(2))
    with pytest.raises(ValueError, match="slot holds a"):
        ft.study(
            report, cubes, mask, offsets=1, ti_forecasts={"lgbm": ft.ti_forecast(seq)}
        )
    with pytest.raises(ValueError, match="same seed column"):
        ft.study(
            report,
            cubes,
            mask,
            offsets=1,
            ti_forecasts={
                "lgbm": ft.ti_forecast(lgbm, seed_column=1),
                "seq": ft.ti_forecast(seq),
            },
        )


# The T-I block's windows: the model window of each family starts at its
# own first forecast session and ends before 2024; its paired statistics
# cover every session in it; before that session the candidate is
# dip_or_close to the bit, every order there is a no-forecast order and
# none after is; the rows carry buy and sell sides apart.
def test_ti_block_windows_start_at_the_first_forecast_session():
    report, mask, cubes = base._world(t=420, n=6, seed=5, start=date(2023, 1, 2))
    panel = report.panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    firsts = {"lgbm": 150, "seq": 200}
    ti = {
        family: ft.ti_forecast(
            _ti_forecast(report, cubes, family, _noise(i + 3), first=row)
        )
        for i, (family, row) in enumerate(firsts.items())
    }
    payload = ft.study(
        report, cubes, mask, offsets=2, conventions=ft.TI_CONVENTIONS, ti_forecasts=ti
    )
    block = payload["stage3_ti"]
    assert block["conventions"] == list(ft.TI_CONVENTIONS)
    assert block["control"] == "dip_or_close" and block["hac_lag"] == 20
    assert block["next_bar"] is False and block["seed_column"] is None
    assert len(block["rows"]) == 4 * 3
    end = np.datetime64("2024-01-01")
    for family, row0 in firsts.items():
        first = str(dates[row0])
        assert block["families"][family]["first_forecast_session"] == first
        assert block["windows"][family] == {
            "model": [first, "2024-01-01"],
            "2016-2023": ["2016-01-01", "2024-01-01"],
            "2024-2026": ["2024-01-01", None],
        }
        for rule in ("filter", "free"):
            rows = {
                r["window"]: r
                for r in block["rows"]
                if r["family"] == family and r["rule"] == rule
            }
            model = rows["model"]
            assert model["start"] == first and model["end"] == "2024-01-01"
            assert model["sessions"] == int(
                ((dates >= dates[row0]) & (dates < end)).sum()
            )
            assert rows["2024-2026"]["sessions"] == int((dates >= end).sum())
            assert model["orders"]["all"]["no_forecast"] == 0
            assert rows["2016-2023"]["orders"]["all"]["no_forecast"] > 0
            for window in ("model", "2016-2023", "2024-2026"):
                orders = rows[window]["orders"]
                assert (
                    orders["all"]["orders"]
                    == orders["buy"]["orders"] + orders["sell"]["orders"]
                )
                versus = rows[window]["versus_control"]
                assert versus["all"]["differing"] == (
                    versus["buy"]["differing"] + versus["sell"]["differing"]
                )
            assert rows["model"]["orders"]["all"]["late_triggers"] >= 0
    # The priced series: the candidate is dip_or_close to the bit before its
    # first forecast session, and the order log marks exactly those orders.
    priced, _ = ft._price_all(
        report,
        cubes,
        mask,
        ("next_open", "dip_or_close", "seq_filter"),
        None,
        2,
        10.0,
        ti=ti,
    )
    for at, control in zip(priced["seq_filter"], priced["dip_or_close"], strict=True):
        np.testing.assert_array_equal(at.returns[:200], control.returns[:200])
        assert not np.array_equal(at.returns, control.returns, equal_nan=True)
        np.testing.assert_array_equal(at.waits.no_sigma, at.waits.session < 200)
    reading = block["reading"]
    assert set(reading) == set(ft.TI_CONVENTIONS)
    assert set(block["deflated"]) == set(ft.TI_CONVENTIONS)
    assert all(
        d["trials"] == 8 and d["candidates"] <= 4 for d in block["deflated"].values()
    )


# A brute-force t of a mean clustered by group, written as the definition:
# the per-cluster sums of residuals, their squares, G / (G - 1) over n^2.
def _brute_clustered_t(values, clusters) -> float:
    values = [float(v) for v in values]
    mean = sum(values) / len(values)
    sums: dict = {}
    for v, c in zip(values, clusters, strict=True):
        sums[c] = sums.get(c, 0.0) + (v - mean)
    g = len(sums)
    variance = g / (g - 1.0) * sum(s * s for s in sums.values()) / len(values) ** 2
    return mean / math.sqrt(variance)


# The clustered t by hand: one value per cluster is the ordinary t; two
# clusters of two give 1.4 exactly; NaN is dropped; one cluster or one value
# is undefined.
def test_clustered_t_by_hand():
    x = np.array([1.0, 2.0, 4.0, 7.0])
    assert ft.clustered_t(x, np.arange(4)) == pytest.approx(
        x.mean() / (x.std(ddof=1) / 2.0)
    )
    assert ft.clustered_t([1.0, 3.0, 10.0, 14.0], [0, 0, 1, 1]) == pytest.approx(1.4)
    assert ft.clustered_t(
        [1.0, 3.0, np.nan, 10.0, 14.0], [0, 0, 0, 1, 1]
    ) == pytest.approx(1.4)
    assert _brute_clustered_t([1.0, 3.0, 10.0, 14.0], [0, 0, 1, 1]) == pytest.approx(
        1.4
    )
    assert math.isnan(ft.clustered_t([1.0, 2.0], [5, 5]))
    assert math.isnan(ft.clustered_t([1.0], [0]))
    assert math.isnan(ft.clustered_t([], []))


# Candidate minus control per order, recomputed by brute force from each
# logged order's own bars with `fill_price`: the orders in the window, the
# ones the two conventions fill differently, the mean difference over those
# (positive = a cheaper buy or a dearer sell than dip_or_close) and its t
# clustered by fill session, for all orders and for buys and sells apart.
def test_versus_control_per_order_by_brute_force():
    report, mask, cubes = base._world(t=320, n=7, seed=11, start=date(2023, 1, 2))
    panel = report.panel
    forecast = _ti_forecast(report, cubes, s3.SEQ, _noise(5), first=40)
    ti = ft.ti_forecast(forecast)
    lookup = s3.ti_lookup(forecast)
    targets = ft.target_path(report, mask, ft.since_offset(panel, 1))
    control = ft.cube_prices(cubes, panel, "dip_or_close")
    keep = np.ones(len(panel.dates), dtype=bool)
    keep[:60] = False
    for convention in ("seq_filter", "seq_free"):
        prices = ft.cube_prices(cubes, panel, convention, ti=ti.lookup)
        log = ft.price_book(targets, report, prices, convention, 10.0).waits
        fields = ft._ti_versus(log, prices, control, keep)
        expected = {"all": ([], [], 0), "buy": ([], [], 0), "sell": ([], [], 0)}
        for s, j, buying in zip(log.session, log.column, log.buy, strict=True):
            if not keep[s]:
                continue
            ticker = panel.tickers[j]
            cube = cubes[ticker]
            i = int(np.searchsorted(cube.dates, panel.dates[s]))
            row = {
                k: getattr(cube, k)[i]
                for k in ("open", "high", "low", "close", "volume")
            }
            row["auction_open"] = float(cube.auction_open[i])
            side = "buy" if buying else "sell"
            vector = lookup.get(
                (ticker, np.datetime64(cube.dates[i], "D")), np.full(K, np.nan)
            )
            ours = ft.fill_price(row, convention, side, yhat=vector)
            theirs = ft.fill_price(row, "dip_or_close", side)
            close = (
                row["auction_open"]
                if math.isfinite(row["auction_open"])
                else row["close"][-1]
            )
            for key in ("all", side):
                diffs, days, count = expected[key]
                expected[key] = (diffs, days, count + 1)
                if ours != theirs:
                    diffs.append(
                        ((theirs - ours) if buying else (ours - theirs)) / close * 1e4
                    )
                    days.append(int(s))
        for key, (diffs, days, count) in expected.items():
            assert fields[key]["orders"] == count
            assert fields[key]["differing"] == len(diffs)
            assert fields[key]["differing_sessions"] == len(set(days))
            if len(diffs) > 1 and len(set(days)) > 1:
                assert fields[key]["bp_per_differing_order"] == pytest.approx(
                    np.mean(diffs), rel=1e-9, abs=1e-9
                )
                assert fields[key]["clustered_t"] == pytest.approx(
                    _brute_clustered_t(diffs, days), rel=1e-7
                )
        assert fields["all"]["differing"] > 5


# A world whose every session dips 1.5% at the first bar and then either
# keeps falling to -5% ("a knife") or recovers to +5.3%: the board's 1% dip
# buys every knife early, and its 1% pop sells every recovery early.
def _knife_world(
    t: int = 700, n: int = 8, seed: int = 3, start: date = date(2021, 9, 1)
):
    rng = np.random.default_rng(seed)
    dates = base._dates(t, start)
    knife = rng.random((t, n)) < 0.5
    end = np.where(knife, math.log(0.95), -math.log(0.95))
    gap = rng.normal(0.0, 0.002, size=(t, n))
    open_, close = np.empty((t, n)), np.empty((t, n))
    price = np.full(n, 100.0)
    for i in range(t):
        open_[i] = price * np.exp(gap[i])
        close[i] = open_[i] * np.exp(end[i])
        price = close[i]
    report = base._report(dates, open_, close, base._grades(rng, t, n))
    mask = np.ones((t, n), dtype=bool)
    mask[:, -1] = False
    first = np.log([0.985, 0.975, 0.97])
    cubes = {}
    for j, name in enumerate(report.panel.tickers[:-1]):
        finish = np.log(close[:, j] / open_[:, j])
        rest = first[-1] + (np.arange(3, SLOTS) - 2)[None, :] / (SLOTS - 3.0) * (
            finish[:, None] - first[-1]
        )
        path = np.hstack([np.tile(first, (t, 1)), rest])
        bar_close = open_[:, j][:, None] * np.exp(path)
        bar_open = np.column_stack([open_[:, j], bar_close[:, :-1]])
        cubes[name] = SessionCube(
            ticker=name,
            dates=dates,
            open=bar_open,
            high=np.maximum(bar_open, bar_close),
            low=np.minimum(bar_open, bar_close),
            close=bar_close,
            volume=np.full((t, SLOTS), 1000.0),
            prior_close=np.full(t, np.nan),
            excluded={},
            auction_open=close[:, j].copy(),
            auction_volume=np.full(t, np.nan),
        )
    return report, mask, cubes


# A forecast that knows each session's close lets the filter veto every
# knife buy and every early sell: it clears the floor against dip_or_close
# on the model window with a large t, is not worse on 2024-2026, gains on
# every order it fills differently, and its reading says so. The same
# filter fed noise on bridge noise does not clear the floor.
def test_informed_filter_clears_the_floor_and_noise_does_not():
    report, mask, cubes = _knife_world()
    ti = {
        "lgbm": ft.ti_forecast(_ti_forecast(report, cubes, s3.LGBM, _truth, first=60))
    }
    payload = ft.study(
        report, cubes, mask, offsets=3, conventions=["lgbm_filter"], ti_forecasts=ti
    )
    block = payload["stage3_ti"]
    rows = {r["window"]: r for r in block["rows"]}
    model = rows["model"]
    assert model["mean_daily_bp_vs_dip"] >= s3.FLOOR_BP
    assert model["hac_t_vs_dip"] >= s3.FLOOR_T
    assert model["offsets_above_dip"] == 3
    assert rows["2024-2026"]["mean_daily_bp_vs_dip"] > 0
    versus = model["versus_control"]
    assert versus["all"]["differing"] > 20
    assert versus["buy"]["bp_per_differing_order"] > 300
    assert versus["sell"]["bp_per_differing_order"] > 300
    assert (
        model["orders"]["buy"]["gain_bp_per_order"]
        > model["control_orders"]["buy"]["gain_bp_per_order"]
    )
    reading = block["reading"]["lgbm_filter"]
    assert reading["passes_floor"] and reading["not_worse_reported"]
    assert not reading["real_but_immaterial"]
    noise_report, noise_mask, noise_cubes = base._world(
        t=620, n=6, seed=2, start=date(2021, 9, 1)
    )
    noisy = {
        "lgbm": ft.ti_forecast(
            _ti_forecast(noise_report, noise_cubes, s3.LGBM, _noise(9), first=60)
        )
    }
    quiet = ft.study(
        noise_report,
        noise_cubes,
        noise_mask,
        offsets=3,
        conventions=["lgbm_filter", "lgbm_free"],
        ti_forecasts=noisy,
    )["stage3_ti"]
    for convention, reading in quiet["reading"].items():
        assert not reading["passes_floor"], convention


# The command prices the T-I trial from two forecast files: dip_or_close
# is added, the payload goes to its own file per cost, fill mode and seed
# (or --out), with each file's path and sha256, the T-I block and this
# run's reading in the text; the runs it wrote give a verdict. Refused
# before the desk runs: a T-I convention without its family's file, a file
# of another family, an unused family, a malformed or repeated option, a
# seed column without files or outside the file, a missing file.
def test_cli_prices_the_ti_trial(tmp_path):
    membership, fake_desk, sessions, names, calls = base._sip_store(tmp_path)
    dates = np.array(sessions, dtype="datetime64[D]")
    rng = np.random.default_rng(5)
    paths = {}
    for family in ft.TI_FAMILIES:
        rows = [(d, t, k) for d in dates[20:] for t in names for k in range(K)]
        values = rng.normal(0.0, 20.0, size=len(rows)).astype(np.float32)
        forecast = s3.Stage3Forecast(
            kind=s3.TI,
            family=family,
            dates=np.array([r[0] for r in rows], dtype="datetime64[D]"),
            tickers=np.array([r[1] for r in rows]),
            slot=np.array([r[2] for r in rows], dtype=np.int8),
            yhat=values,
            yhat_seeds=np.stack([values * (1 + s) for s in range(5)], axis=1),
            yhat_configs=None,
            fold=np.zeros(len(rows), dtype=np.int32),
            meta={"model": "synthetic"},
        )
        paths[family] = s3.save_forecast(tmp_path / f"ti_{family}.npz", forecast)
    common = [
        "--root",
        str(tmp_path),
        "--membership",
        str(membership),
        "--workers",
        "1",
        "--offsets",
        "2",
        "--stage3-forecast",
        f"lgbm={paths['lgbm']}",
        "--stage3-forecast",
        f"seq={paths['seq']}",
        "--only",
        "dip_or_close,lgbm_filter,lgbm_free,seq_filter,seq_free",
    ]
    out = io.StringIO()
    assert cli.run(cli.build_parser().parse_args(common), out, desk_run=fake_desk) == 0
    target = tmp_path / "desk" / "stage3_ti_fill_10bp.json"
    assert target.exists()
    assert not (tmp_path / "desk" / cli.FILE).exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["conventions"] == ["next_open", "dip_or_close", *ft.TI_CONVENTIONS]
    assert payload["next_bar"] is False
    for family, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert payload["stage3_forecasts"][family] == {
            "file": str(path),
            "sha256": digest,
            "seed_column": None,
        }
        info = payload["stage3_ti"]["families"][family]
        assert info["sha256"] == digest and info["file"] == str(path)
        assert info["first_forecast_session"] == str(dates[20])
    block = payload["stage3_ti"]
    assert len(block["rows"]) == 4 * 3
    assert set(block["reading"]) == set(ft.TI_CONVENTIONS)
    assert payload["verdict"].startswith("NOT JUDGED")
    text = out.getvalue()
    assert "stage-3 T-I trial" in text and "this run's reading" in text
    # The runs the verdict reads, each to its own file.
    runs = {}
    for extra, name in (
        (["--cost", "16"], "stage3_ti_fill_16bp.json"),
        (["--cost", "25"], "stage3_ti_fill_25bp.json"),
        (["--next-bar"], "stage3_ti_fill_10bp_next_bar.json"),
        *(
            (["--seed-column", str(k)], f"stage3_ti_fill_10bp_seed{k}.json")
            for k in range(5)
        ),
    ):
        out = io.StringIO()
        assert (
            cli.run(
                cli.build_parser().parse_args([*common, *extra]),
                out,
                desk_run=fake_desk,
            )
            == 0
        )
        runs[name] = json.loads((tmp_path / "desk" / name).read_text(encoding="utf-8"))
    assert runs["stage3_ti_fill_10bp_next_bar.json"]["stage3_ti"]["next_bar"] is True
    assert runs["stage3_ti_fill_10bp_seed3.json"]["stage3_ti"]["seed_column"] == 3
    assert (
        runs["stage3_ti_fill_10bp_seed3.json"]["stage3_forecasts"]["lgbm"][
            "seed_column"
        ]
        == 3
    )
    record = sv.ti_verdict(
        [payload, runs["stage3_ti_fill_16bp.json"], runs["stage3_ti_fill_25bp.json"]],
        next_bar=[runs["stage3_ti_fill_10bp_next_bar.json"]],
        seeds=[runs[f"stage3_ti_fill_10bp_seed{k}.json"] for k in range(5)],
    )
    assert set(record["candidates"]) == set(ft.TI_CONVENTIONS)
    for info in record["candidates"].values():
        assert info["label"] in (sv.REPLACES, sv.RECORD, sv.IMMATERIAL)
        assert info["seeds"]["complete"]
    out = io.StringIO()
    elsewhere = tmp_path / "elsewhere" / "ti.json"
    assert (
        cli.run(
            cli.build_parser().parse_args([*common, "--out", str(elsewhere)]),
            out,
            desk_run=fake_desk,
        )
        == 0
    )
    assert json.loads(elsewhere.read_text(encoding="utf-8"))["stage3_ti"]["conventions"]
    before = len(calls)
    plain = ["--root", str(tmp_path), "--membership", str(membership), "--workers", "1"]
    for extra, code, message in (
        (["--only", "lgbm_filter"], 2, "need their family's forecast"),
        (
            ["--stage3-forecast", f"lgbm={paths['lgbm']}", "--only", "seq_free"],
            2,
            "need their",
        ),
        (["--stage3-forecast", f"lgbm={paths['seq']}"], 2, "holds a seq forecast"),
        (
            [
                "--stage3-forecast",
                f"lgbm={paths['lgbm']}",
                "--stage3-forecast",
                f"seq={paths['seq']}",
                "--only",
                "lgbm_filter",
            ],
            2,
            "none of its conventions",
        ),
        (["--stage3-forecast", "lgbm"], 2, "FAMILY=NPZ"),
        (
            [
                "--stage3-forecast",
                f"lgbm={paths['lgbm']}",
                "--stage3-forecast",
                f"lgbm={paths['lgbm']}",
            ],
            2,
            "twice",
        ),
        (["--seed-column", "1"], 2, "--seed-column picks"),
        (
            ["--stage3-forecast", f"lgbm={paths['lgbm']}", "--seed-column", "7"],
            2,
            "seed column 7",
        ),
        (["--stage3-forecast", f"lgbm={tmp_path / 'missing.npz'}"], 1, "not found"),
    ):
        out = io.StringIO()
        assert (
            cli.run(
                cli.build_parser().parse_args([*plain, *extra]), out, desk_run=fake_desk
            )
            == code
        )
        assert message in out.getvalue(), (extra, out.getvalue())
    assert len(calls) == before
