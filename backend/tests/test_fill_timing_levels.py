"""The entry-level trial: volatility-scaled buy/sell levels in the fill-timing engine.

What has to hold (docs/research/ml-entry-level-plan-2026-09-28.md):

- Each level convention fills at the plan's price on hand-built bars: a
  close exactly on the level triggers the dip rule and a close one ulp
  short does not; the resting limit needs a low strictly under it and
  fills at the limit; no trigger fills at the official close; sells mirror.
- The order decided at t's close reads the forecast row dated t for its
  fill on t + 1. Shifting the file one session changes the result, and
  altering every row from session s on leaves every return through s
  bit-identical.
- A missing sigma fills exactly as dip_or_close and is counted. trail_dip
  falls back on the same cells as the model.
- The controls are untouched: dip_or_close's prices are byte-identical to
  the code before this change, and the fill-timing trial's rows, best and
  verdict are the same with the level trial priced beside it.
- A world where the forecast knows each session's dip depth makes the
  model REPLACE the board's rule; an uninformative forecast records.
- The command runs the level trial end to end from a forecasts npz and
  records the file's sha256.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import replace

import numpy as np
import pytest

from backend.cli import market_fill_timing as cli
from backend.market import fill_timing as ft
from backend.market import vol_forecast as vf
from backend.market.session_anatomy import json_ready
from backend.market.sip_cube import SessionCube
from backend.tests import test_fill_timing as base

SLOTS = base.SLOTS
LEVEL_FIELDS = {
    "median_cagr_vs_dip",
    "offsets_above_dip",
    "mean_daily_bp_vs_dip",
    "hac_t_vs_dip",
    "mean_daily_bp_vs_twin",
    "hac_t_vs_twin",
    "dip_orders",
    "dip_fills",
    "dip_fill_rate",
    "gain_bp_per_dip_fill",
    "gain_bp_per_order",
    "sigma_fallbacks",
    "sigma_fallback_share",
}


# A hand-built session opening at 100 whose bar closes drift up a tenth a
# bar from 100.3, so nothing dips unless a test puts a close there; highs
# and lows a tenth either side of each close; flat volume.
def _flat(auction: float = math.nan) -> dict:
    close = 100.3 + 0.1 * np.arange(SLOTS)
    return {
        "open": np.concatenate([[100.0], close[:-1]]),
        "high": close + 0.1,
        "low": close - 0.1,
        "close": close,
        "volume": np.full(SLOTS, 100.0),
        "auction_open": auction,
    }


# A session opening at 100 whose bar closes fall a tenth a bar from 99.7,
# the mirror of `_flat` for sells.
def _falling(auction: float = math.nan) -> dict:
    close = 99.7 - 0.1 * np.arange(SLOTS)
    return {
        "open": np.concatenate([[100.0], close[:-1]]),
        "high": close + 0.1,
        "low": close - 0.1,
        "close": close,
        "volume": np.full(SLOTS, 100.0),
        "auction_open": auction,
    }


# A one-session cube from a hand-built row.
def _one_session(row: dict) -> SessionCube:
    return SessionCube(
        ticker="X",
        dates=np.array(["2020-01-02"], dtype="datetime64[D]"),
        open=np.asarray(row["open"], dtype=float)[None, :],
        high=np.asarray(row["high"], dtype=float)[None, :],
        low=np.asarray(row["low"], dtype=float)[None, :],
        close=np.asarray(row["close"], dtype=float)[None, :],
        volume=np.asarray(row["volume"], dtype=float)[None, :],
        prior_close=np.array([math.nan]),
        excluded={},
        auction_open=np.array([float(row["auction_open"])]),
        auction_volume=np.array([math.nan]),
    )


# The panel's (dates, tickers) grid with a forecast and a baseline grid.
def _aligned(report, forecast: np.ndarray, baseline: np.ndarray) -> vf.Aligned:
    panel = report.panel
    return vf.Aligned(
        np.asarray(panel.dates, dtype="datetime64[D]"),
        tuple(panel.tickers),
        np.asarray(forecast, dtype=float),
        np.asarray(baseline, dtype=float),
        None,
    )


# Random log variances with a wide spread (sigma from 0.2% to 3%), NaN in
# the benchmark's column, as a grid on the report's panel.
def _random_logvar(report, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rows, names = report.panel.adj_close.shape
    grid = 2.0 * np.log(rng.uniform(0.002, 0.03, size=(rows, names)))
    grid[:, -1] = np.nan
    return grid


# Rows of a Forecasts file from a (sessions, names) grid: one row per cell
# whose baseline is finite, dated `dates[t + shift]` (shift 1 files every
# forecast one session late), for the named columns.
def _file_rows(
    dates: np.ndarray,
    tickers: tuple[str, ...],
    forecast: np.ndarray,
    baseline: np.ndarray,
    shift: int = 0,
) -> vf.Forecasts:
    days, names, fc, bl = [], [], [], []
    for t in range(len(dates) - shift):
        for j, ticker in enumerate(tickers):
            if not np.isfinite(baseline[t, j]):
                continue
            days.append(dates[t + shift])
            names.append(ticker)
            fc.append(forecast[t, j])
            bl.append(baseline[t, j])
    return vf.Forecasts(
        np.array(days, dtype="datetime64[D]"),
        np.array(names),
        np.array(fc, dtype=float),
        np.array(bl, dtype=float),
        meta={"model": "synthetic"},
    )


# The level trial's registered constants, fixed before any run, and the
# fill-timing trial's own set left as it was.
def test_level_constants_are_the_plans():
    assert ft.LEVEL_CONVENTIONS == (
        "vol_dip_0.5",
        "vol_dip_1.0",
        "vol_limit_0.5",
        "trail_dip",
    )
    assert {
        "vol_dip_0.5": ft.Level("dip", 0.5, "forecast"),
        "vol_dip_1.0": ft.Level("dip", 1.0, "forecast"),
        "vol_limit_0.5": ft.Level("limit", 0.5, "forecast"),
        "trail_dip": ft.Level("dip", 0.5, "trailing"),
    } == ft.LEVELS
    assert ft.LEVEL_CONTROL == "dip_or_close"
    assert ft.LEVEL_TWIN == "trail_dip"
    assert ft.REPLACE_BP == 2.0
    assert ft.REPLACE_T == 2.0
    assert ft.LEVEL_TRIALS == 4
    assert ft.HAC_LAG == 20
    assert len(ft.CONVENTIONS) == 7
    assert ft.TRIALS == 7
    assert ft.ALL_CONVENTIONS == ft.CONVENTIONS + ft.LEVEL_CONVENTIONS


# The level is k sigma below (buy) or above (sell) the open, in log terms.
def test_entry_level():
    assert ft.entry_level(100.0, 0.02, 0.5, "buy") == pytest.approx(
        100.0 * math.exp(-0.01)
    )
    assert ft.entry_level(100.0, 0.02, 1.0, "sell") == pytest.approx(
        100.0 * math.exp(0.02)
    )
    np.testing.assert_allclose(
        ft.entry_level(np.array([50.0, 200.0]), np.array([0.01, 0.04]), 0.5, "buy"),
        [50.0 * math.exp(-0.005), 200.0 * math.exp(-0.02)],
    )
    with pytest.raises(ValueError, match="side must be"):
        ft.entry_level(100.0, 0.02, 0.5, "hold")


# The dip rule on hand-built bars: a close exactly on the level fills
# there, one ulp short of it fills at the close; the first crossing wins,
# not the lowest; k = 1.0 waits deeper than k = 0.5; sells mirror; no
# sigma is dip_or_close; trail_dip is the same rule on the same sigma.
def test_vol_dip_fill_prices_on_hand_built_paths():
    sig = 0.02
    level = float(ft.entry_level(100.0, sig, 0.5, "buy"))
    row = _flat()
    row["close"][5] = level  # exactly on the boundary
    assert ft.fill_price(row, "vol_dip_0.5", "buy", sig=sig) == level
    short = _flat()
    short["close"][5] = np.nextafter(level, np.inf)  # one ulp above: never at or below
    assert ft.fill_price(short, "vol_dip_0.5", "buy", sig=sig) == short["close"][-1]
    assert ft.fill_price(_flat(auction=101.7), "vol_dip_0.5", "buy", sig=sig) == 101.7
    # The first close past the level is the fill, not the deepest.
    first = _flat()
    first["close"][3], first["close"][9] = 98.9, 97.0
    assert ft.fill_price(first, "vol_dip_0.5", "buy", sig=sig) == 98.9
    # A 1.5% dip: past k = 0.5's level (-1%) but not k = 1.0's (-2%).
    dip = _flat()
    dip["close"][3] = 98.5
    assert ft.fill_price(dip, "vol_dip_0.5", "buy", sig=sig) == 98.5
    assert ft.fill_price(dip, "vol_dip_1.0", "buy", sig=sig) == dip["close"][-1]
    # Sells mirror: a close exactly on open * exp(+k sigma) fills there.
    up = float(ft.entry_level(100.0, sig, 0.5, "sell"))
    rise = _falling()
    rise["close"][7] = up
    assert ft.fill_price(rise, "vol_dip_0.5", "sell", sig=sig) == up
    rise["close"][7] = np.nextafter(up, -np.inf)
    assert ft.fill_price(rise, "vol_dip_0.5", "sell", sig=sig) == rise["close"][-1]
    # No usable sigma: exactly dip_or_close's price, both sides.
    for missing in (math.nan, 0.0, -0.01, math.inf):
        for side in ("buy", "sell"):
            assert ft.fill_price(
                dip, "vol_dip_1.0", side, sig=missing
            ) == ft.fill_price(dip, "dip_or_close", side)
    # trail_dip is vol_dip_0.5's rule; only where its sigma comes from differs.
    for side in ("buy", "sell"):
        assert ft.fill_price(dip, "trail_dip", side, sig=sig) == ft.fill_price(
            dip, "vol_dip_0.5", side, sig=sig
        )


# The resting limit: a low exactly on the limit is a touch and does not
# fill (the order goes to the close); a low one ulp under it fills at the
# limit price itself, not the low and not the close; sells mirror on the
# highs; no sigma is dip_or_close.
def test_vol_limit_is_strict_and_fills_at_the_limit():
    sig = 0.03
    limit = float(ft.entry_level(100.0, sig, 0.5, "buy"))
    touch = _flat(auction=100.9)
    touch["low"][4] = limit
    assert ft.fill_price(touch, "vol_limit_0.5", "buy", sig=sig) == 100.9
    through = _flat(auction=100.9)
    through["low"][4] = np.nextafter(limit, -np.inf)
    assert ft.fill_price(through, "vol_limit_0.5", "buy", sig=sig) == limit
    # A bar trading far through the limit still fills at the limit.
    deep = _flat()
    deep["low"][4] = 90.0
    assert ft.fill_price(deep, "vol_limit_0.5", "buy", sig=sig) == limit
    # The dip rule on the same bars reads closes, not lows: no fill there.
    assert ft.fill_price(deep, "vol_dip_0.5", "buy", sig=sig) == deep["close"][-1]
    up = float(ft.entry_level(100.0, sig, 0.5, "sell"))
    high = _falling(auction=97.3)
    high["high"][6] = up
    assert ft.fill_price(high, "vol_limit_0.5", "sell", sig=sig) == 97.3
    high["high"][6] = np.nextafter(up, np.inf)
    assert ft.fill_price(high, "vol_limit_0.5", "sell", sig=sig) == up
    for side in ("buy", "sell"):
        assert ft.fill_price(
            deep, "vol_limit_0.5", side, sig=math.nan
        ) == ft.fill_price(deep, "dip_or_close", side)
    # A level convention asked for prices without a sigma is refused.
    with pytest.raises(ValueError, match="needs a sigma"):
        ft.session_prices(_one_session(deep), "vol_limit_0.5", "buy")
    with pytest.raises(ValueError, match="does not wait"):
        ft.waiting_fills(_one_session(deep), "next_open", "buy")


# The grid read: an order filling on session s reads exp(F / 2) of the
# row dated s - 1 (row 0 has nothing before it); trail_dip reads the
# baseline there, and only on cells where the forecast exists.
def test_fill_sigma_reads_the_decision_row():
    report, _, _ = base._world(t=40, n=4, seed=5)
    forecast = _random_logvar(report, 1)
    forecast[10:15, 1] = np.nan
    baseline = _random_logvar(report, 2)
    aligned = _aligned(report, forecast, baseline)
    model = ft.fill_sigma(aligned, "vol_dip_0.5")
    assert np.isnan(model[0]).all()
    np.testing.assert_array_equal(model[1:], np.exp(forecast[:-1] / 2.0))
    np.testing.assert_array_equal(ft.fill_sigma(aligned, "vol_limit_0.5"), model)
    trailing = ft.fill_sigma(aligned, "trail_dip")
    covered = np.isfinite(forecast[:-1])
    np.testing.assert_array_equal(
        trailing[1:][covered], np.exp(baseline[:-1][covered] / 2.0)
    )
    assert np.isnan(trailing[1:][~covered]).all()
    assert np.isnan(trailing[11:16, 1]).all()
    assert np.isfinite(baseline[10:15, 1]).all()
    with pytest.raises(ValueError, match="not a level convention"):
        ft.fill_sigma(aligned, "dip_or_close")


# Alignment and no lookahead, through the file the command reads. The
# forecasts saved and aligned by `vol_forecast` put each fill's sigma on the
# decision row; the same file dated one session late gives a different
# result; every fill equals the single-session price at sigma from row
# s - 1; and altering every forecast from session s0 on leaves every
# return through s0 bit-identical while later returns move.
def test_alignment_and_no_lookahead(tmp_path):
    report, mask, cubes = base._world(t=260, n=6, seed=4)
    panel = report.panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    tickers = tuple(panel.tickers)
    forecast = _random_logvar(report, 7)
    baseline = _random_logvar(report, 8)
    right = vf.save_forecasts(
        tmp_path / "right.npz", _file_rows(dates, tickers, forecast, baseline)
    )
    late = vf.save_forecasts(
        tmp_path / "late.npz", _file_rows(dates, tickers, forecast, baseline, shift=1)
    )
    aligned = vf.aligned_to_panel(right, panel)
    shifted = vf.aligned_to_panel(late, panel)
    np.testing.assert_array_equal(aligned.forecast, forecast)
    targets = ft.target_path(report, mask, ft.since_offset(panel, 3))
    for convention in ("vol_dip_0.5", "vol_limit_0.5", "trail_dip"):
        prices = ft.cube_prices(
            cubes, panel, convention, ft.fill_sigma(aligned, convention)
        )
        wrong = ft.cube_prices(
            cubes, panel, convention, ft.fill_sigma(shifted, convention)
        )
        ours = ft.price_book(targets, report, prices, convention, 10.0)
        off = ft.price_book(targets, report, wrong, convention, 10.0)
        assert ours.fills > 0
        assert ours.fills == off.fills
        assert not np.allclose(ours.returns, off.returns, equal_nan=True)
    # Every cube-priced fill of the aligned book is the one-session price
    # at the decision row's sigma - and for most, not the fill row's own.
    convention = "vol_dip_0.5"
    prices = ft.cube_prices(
        cubes, panel, convention, ft.fill_sigma(aligned, convention)
    )
    checked = lookahead_differs = 0
    for j, ticker in enumerate(tickers[:-1]):
        cube = cubes[ticker]
        for s in range(1, len(dates), 7):
            i = int(np.searchsorted(cube.dates, dates[s]))
            row = {
                k: getattr(cube, k)[i]
                for k in ("open", "high", "low", "close", "volume")
            }
            row["auction_open"] = float(cube.auction_open[i])
            scale = panel.adj_close[s, j] / row["auction_open"]
            for side, grid in (("buy", prices.buy), ("sell", prices.sell)):
                expected = ft.fill_price(
                    row, convention, side, sig=math.exp(forecast[s - 1, j] / 2)
                )
                assert grid[s, j] == pytest.approx(expected * scale, rel=1e-12)
                ahead = ft.fill_price(
                    row, convention, side, sig=math.exp(forecast[s, j] / 2)
                )
                lookahead_differs += ahead != expected
                checked += 1
    assert checked > 100
    assert lookahead_differs > 0
    # No lookahead: rows from s0 on altered, returns through s0 unchanged.
    s0 = 150
    ours = ft.price_book(targets, report, prices, convention, 10.0)
    altered = forecast.copy()
    altered[s0:] += 4.0
    moved = ft.cube_prices(
        cubes,
        panel,
        convention,
        ft.fill_sigma(_aligned(report, altered, baseline), convention),
    )
    later = ft.price_book(targets, report, moved, convention, 10.0)
    np.testing.assert_array_equal(later.returns[: s0 + 1], ours.returns[: s0 + 1])
    assert not np.array_equal(later.returns[s0 + 1 :], ours.returns[s0 + 1 :])


# Where the forecast is missing (here, every decision row before H) each
# level convention fills exactly as dip_or_close, so every return through
# H is bit-identical to it; the orders filling by H are logged as having no
# sigma and none after; trail_dip falls back on the same cells although its
# baseline covers all of them; and the study counts it per window.
def test_missing_forecast_falls_back_to_dip_or_close_and_is_counted():
    report, mask, cubes = base._world(t=300, n=6, seed=6)
    panel = report.panel
    horizon = 120
    forecast = _random_logvar(report, 3)
    forecast[:horizon] = np.nan
    baseline = _random_logvar(report, 4)
    aligned = _aligned(report, forecast, baseline)
    targets = ft.target_path(report, mask, None)
    control = ft.price_book(
        targets,
        report,
        ft.cube_prices(cubes, panel, "dip_or_close"),
        "dip_or_close",
        10.0,
    )
    assert control.waits is not None
    assert not control.waits.no_sigma.any()
    for convention in ft.LEVEL_CONVENTIONS:
        prices = ft.cube_prices(
            cubes, panel, convention, ft.fill_sigma(aligned, convention)
        )
        priced = ft.price_book(targets, report, prices, convention, 10.0)
        np.testing.assert_array_equal(
            priced.returns[: horizon + 1], control.returns[: horizon + 1]
        )
        waits = priced.waits
        assert waits is not None
        assert len(waits.session) == priced.fills
        np.testing.assert_array_equal(waits.no_sigma, waits.session <= horizon)
        assert waits.no_sigma.any()
        assert not waits.no_sigma.all()
    payload = ft.study(
        report,
        cubes,
        mask,
        offsets=2,
        conventions=ft.LEVEL_CONVENTIONS,
        forecasts=aligned,
    )
    rows = {(r["convention"], r["window"]): r for r in payload["rows"]}
    median = ft.price_book(
        ft.target_path(report, mask, ft.since_offset(panel, 1)),
        report,
        ft.cube_prices(
            cubes, panel, "vol_dip_0.5", ft.fill_sigma(aligned, "vol_dip_0.5")
        ),
        "vol_dip_0.5",
        10.0,
    ).waits
    row = rows[("vol_dip_0.5", "all")]
    assert row["dip_orders"] == len(median.session)
    assert row["sigma_fallbacks"] == int(median.no_sigma.sum()) > 0
    assert row["sigma_fallback_share"] == pytest.approx(median.no_sigma.mean())
    assert row["dip_fills"] == int(median.hit.sum())
    for convention in ("vol_dip_1.0", "vol_limit_0.5", "trail_dip"):
        assert rows[(convention, "all")]["sigma_fallbacks"] == row["sigma_fallbacks"]
    assert rows[("dip_or_close", "all")]["sigma_fallbacks"] == 0
    assert math.isnan(rows[("next_open", "all")]["dip_fill_rate"])


# The order fields read the log alone: counts, the rate, the gains per dip
# fill and per order, and the fallbacks inside the window.
def test_wait_fields_arithmetic():
    log = ft.OrderLog(
        session=np.array([2, 3, 5, 8, 9]),
        buy=np.array([True, False, True, True, False]),
        hit=np.array([True, False, True, False, True]),
        gain_bp=np.array([30.0, 0.0, -10.0, 0.0, 50.0]),
        no_sigma=np.array([True, True, False, False, False]),
    )
    keep = np.zeros(10, dtype=bool)
    keep[:6] = True  # sessions 0-5: the first three orders
    fields = ft._wait_fields(log, keep)
    assert fields["dip_orders"] == 3
    assert fields["dip_fills"] == 2
    assert fields["dip_fill_rate"] == pytest.approx(2 / 3)
    assert fields["gain_bp_per_dip_fill"] == pytest.approx(10.0)
    assert fields["gain_bp_per_order"] == pytest.approx(20.0 / 3)
    assert fields["sigma_fallbacks"] == 2
    assert fields["sigma_fallback_share"] == pytest.approx(2 / 3)
    none = ft._wait_fields(None, keep)
    assert none["dip_orders"] == 0
    assert math.isnan(none["dip_fill_rate"])
    empty = ft._wait_fields(log, np.zeros(10, dtype=bool))
    assert empty["dip_orders"] == 0
    assert math.isnan(empty["gain_bp_per_order"])


# The pre-change dip_or_close, frozen verbatim from fill_timing before the
# level conventions (DIP 0.01): the controls must stay byte-identical.
def _frozen_dip_or_close(cube: SessionCube, side: str) -> np.ndarray:
    open0 = cube.open[:, 0][:, None]
    if side == "buy":
        hit = cube.close <= open0 * (1.0 - 0.01)
    else:
        hit = cube.close >= open0 * (1.0 + 0.01)
    any_hit = hit.any(axis=1)
    first = np.argmax(hit, axis=1)
    picked = cube.close[np.arange(len(cube)), first]
    last = cube.close[:, SLOTS - 1]
    auction = np.asarray(cube.auction_open, dtype=float)
    return np.where(any_hit, picked, np.where(np.isfinite(auction), auction, last))


# The controls are unchanged. dip_or_close's session prices are
# byte-identical to the frozen pre-change function and next_open is bar 0's
# open, on cubes that dip, drift and lack auctions. The fill-timing trial's
# rows, best, verdict and simulator gap are the same whether or not the
# level trial is priced beside it. A run without forecasts carries no level
# fields at all.
def test_controls_are_unchanged():
    report, mask, cubes = base._world(t=200, n=6, seed=8)
    _, _, dipped = base._world(t=60, n=4, seed=9, shape="dip", dip=0.02)
    holes = dict(dipped)
    first = next(iter(holes))
    auction = holes[first].auction_open.copy()
    auction[::3] = np.nan
    holes[first] = replace(holes[first], auction_open=auction)
    for cube in [*cubes.values(), *dipped.values(), *holes.values()]:
        for side in ("buy", "sell"):
            ours = ft.session_prices(cube, "dip_or_close", side)
            assert ours.tobytes() == _frozen_dip_or_close(cube, side).tobytes()
            assert (
                ft.session_prices(cube, "next_open", side).tobytes()
                == np.asarray(cube.open[:, 0], dtype=float).tobytes()
            )
    plain = ft.study(report, cubes, mask, offsets=3)
    forecast = _random_logvar(report, 11)
    forecast[:30] = np.nan
    both = ft.study(
        report,
        cubes,
        mask,
        offsets=3,
        forecasts=_aligned(report, forecast, _random_logvar(report, 12)),
    )
    assert "level" not in plain
    assert all(not LEVEL_FIELDS & set(r) for r in plain["rows"])
    assert plain["conventions"] == list(ft.CONVENTIONS)
    assert both["conventions"] == list(ft.ALL_CONVENTIONS)
    by_key = {(r["convention"], r["window"]): r for r in both["rows"]}
    for r in plain["rows"]:
        twin = by_key[(r["convention"], r["window"])]
        assert json.dumps(
            json_ready({k: twin[k] for k in r}), sort_keys=True
        ) == json.dumps(json_ready(r), sort_keys=True)
        assert set(twin) >= LEVEL_FIELDS
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
    # The fill-timing verdict never judges a level convention.
    assert set(both["criteria"]) == set(ft.CONVENTIONS) - {"next_open"}


# One session's bars that fall linearly from the open to `depth` below it
# over the first six bars and then climb linearly to the day's close - the
# shape of a session whose low an informed forecast could know.
def _ramp_cube(ticker, dates, open_, close, depth) -> SessionCube:
    n = len(dates)
    bottom = np.log1p(-depth)
    down = bottom[:, None] * (np.arange(1, 7) / 6.0)[None, :]
    rise = np.log(close / open_) - bottom
    up = (
        bottom[:, None]
        + (np.arange(1, SLOTS - 5) / (SLOTS - 6.0))[None, :] * rise[:, None]
    )
    path = np.hstack([down, up])
    bar_close = open_[:, None] * np.exp(path)
    bar_open = np.column_stack([open_, bar_close[:, :-1]])
    return SessionCube(
        ticker=ticker,
        dates=dates,
        open=bar_open,
        high=np.maximum(bar_open, bar_close),
        low=np.minimum(bar_open, bar_close),
        close=bar_close,
        volume=np.full((n, SLOTS), 1000.0),
        prior_close=np.full(n, np.nan),
        excluded={"early_close": 0, "incomplete": 0, "no_prior_close": 0},
        auction_open=close.copy(),
        auction_volume=np.full(n, np.nan),
    )


# A world whose every session ramps down 2-8% before recovering, with a
# forecast that knows each session's depth (sigma 0.95 of the fall, on the
# decision row before it) after a warm-up, and an uninformative trailing
# baseline (sigma 1.5% everywhere).
def _informed_world(t: int = 620, n: int = 9, seed: int = 3):
    rng = np.random.default_rng(seed)
    dates = base._dates(t)
    open_, close = base._daily(rng, t, n)
    report = base._report(dates, open_, close, base._grades(rng, t, n))
    mask = np.ones((t, n), dtype=bool)
    mask[:, -1] = False
    depth = rng.uniform(0.02, 0.08, size=(t, n))
    cubes = {
        name: _ramp_cube(name, dates, open_[:, j], close[:, j], depth[:, j])
        for j, name in enumerate(report.panel.tickers[:-1])
    }
    forecast = np.full((t, n), np.nan)
    forecast[:-1] = 2.0 * np.log(0.95 * -np.log1p(-depth[1:]))
    forecast[:40] = np.nan
    forecast[:, -1] = np.nan
    baseline = np.full((t, n), 2.0 * math.log(0.015))
    baseline[:, -1] = np.nan
    return report, mask, cubes, _aligned(report, forecast, baseline)


# A forecast that knows how deep each session will fall lets vol_dip_1.0
# buy at the low where the fixed 1% buys early: it beats dip_or_close by
# more than the floor with a large t, is not worse later, beats the
# uninformed trailing twin, and the verdict is REPLACES; its dip fills
# gain more over the close than the board's rule's do.
def test_informed_forecast_replaces_the_board_rule():
    report, mask, cubes, aligned = _informed_world()
    payload = ft.study(
        report,
        cubes,
        mask,
        offsets=3,
        conventions=ft.LEVEL_CONVENTIONS,
        forecasts=aligned,
    )
    rows = {(r["convention"], r["window"]): r for r in payload["rows"]}
    model = rows[("vol_dip_1.0", ft.CHOOSING)]
    assert model["mean_daily_bp_vs_dip"] >= ft.REPLACE_BP
    assert model["hac_t_vs_dip"] >= ft.REPLACE_T
    assert model["mean_daily_bp_vs_twin"] > 0
    assert model["offsets_above_dip"] == 3
    assert rows[("vol_dip_1.0", ft.REPORTED)]["mean_daily_bp_vs_dip"] > 0
    assert (
        model["gain_bp_per_dip_fill"]
        > rows[("dip_or_close", ft.CHOOSING)]["gain_bp_per_dip_fill"]
    )
    level = payload["level"]
    assert "vol_dip_1.0" in level["replaces"]
    assert level["verdict"].startswith(ft.REPLACES)
    assert level["criteria"]["trail_dip"]["label"] != ft.REPLACES
    assert level["best"][ft.CHOOSING]["trials"] == ft.LEVEL_TRIALS
    assert 0.0 <= level["best"][ft.CHOOSING]["deflated_sharpe"] <= 1.0
    assert level["first_forecast_session"] == str(report.panel.dates[40])
    assert "vol_dip_0.5 - trail_dip" in level["twin_line"]
    # A run of only the level trial does not judge the fill-timing seven.
    assert payload["verdict"].startswith("NOT JUDGED")
    assert payload["criteria"] == {}


# An uninformative forecast on iid intraday noise: no level convention
# clears the floors against dip_or_close and the verdict is RECORD.
def test_uninformed_forecast_records():
    report, mask, cubes = base._world(t=620, n=6, seed=2)
    aligned = _aligned(report, _random_logvar(report, 21), _random_logvar(report, 22))
    payload = ft.study(
        report,
        cubes,
        mask,
        offsets=3,
        conventions=ft.LEVEL_CONVENTIONS,
        forecasts=aligned,
    )
    level = payload["level"]
    assert level["replaces"] == []
    assert level["verdict"].startswith(ft.RECORD)
    for convention, criteria in level["criteria"].items():
        assert criteria["label"] == ft.RECORD, convention
        assert not criteria["passes_choosing"]
    assert len(payload["rows"]) == 6 * 3


# The criteria on hand-built rows: each floor at its edge, the reported
# window's sign, the twin's strict edge, trail_dip never replacing, and
# the vol-scaling reading.
def test_level_verdict_applies_the_criteria():
    # A payload with vol_dip_1.0's choosing bp, t, reported bp and bp over
    # the twin, and trail_dip's (bp, t, reported bp) beside it.
    def payload(bp, t, later, twin, trail=(0.0, 0.0, 0.0)):
        rows = []
        for convention, (b, s, reported, w) in {
            "vol_dip_1.0": (bp, t, later, twin),
            "trail_dip": (*trail, math.nan),
        }.items():
            rows.append(
                {
                    "convention": convention,
                    "window": ft.CHOOSING,
                    "mean_daily_bp_vs_dip": b,
                    "hac_t_vs_dip": s,
                    "mean_daily_bp_vs_twin": w,
                    "hac_t_vs_twin": 1.0,
                }
            )
            rows.append(
                {
                    "convention": convention,
                    "window": ft.REPORTED,
                    "mean_daily_bp_vs_dip": reported,
                    "hac_t_vs_dip": 0.0,
                    "mean_daily_bp_vs_twin": 0.0,
                    "hac_t_vs_twin": 0.0,
                }
            )
        return {
            "conventions": ["next_open", "dip_or_close", "vol_dip_1.0", "trail_dip"],
            "rows": rows,
        }

    at_floor = ft.level_verdict(payload(2.0, 2.0, 0.0, 0.01))
    assert at_floor["replaces"] == ["vol_dip_1.0"]
    assert at_floor["verdict"].startswith(ft.REPLACES)
    assert at_floor["criteria"]["vol_dip_1.0"]["label"] == ft.REPLACES
    assert ft.level_verdict(payload(1.99, 3.0, 0.5, 1.0))["replaces"] == []
    assert ft.level_verdict(payload(3.0, 1.99, 0.5, 1.0))["replaces"] == []
    assert ft.level_verdict(payload(3.0, 3.0, -0.01, 1.0))["replaces"] == []
    assert ft.level_verdict(payload(3.0, 3.0, math.nan, 1.0))["replaces"] == []
    assert ft.level_verdict(payload(math.nan, 3.0, 1.0, 1.0))["replaces"] == []
    # The floors without beating the twin: vol-scaling, not the model.
    scaling = ft.level_verdict(payload(3.0, 3.0, 0.5, 0.0))
    assert scaling["replaces"] == []
    assert scaling["criteria"]["vol_dip_1.0"]["label"] == ft.VOL_SCALING
    assert scaling["verdict"].startswith(ft.RECORD)
    assert "vol-scaling" in scaling["verdict"]
    # trail_dip clearing the floors is vol-scaling too; it never replaces.
    trail = ft.level_verdict(payload(0.5, 0.5, 0.0, 1.0, trail=(5.0, 4.0, 1.0)))
    assert trail["criteria"]["trail_dip"]["label"] == ft.VOL_SCALING
    assert trail["replaces"] == []
    quiet = ft.level_verdict(payload(0.5, 0.5, 0.0, 1.0))
    assert quiet["verdict"].startswith(ft.RECORD)
    assert "keeps dip_or_close" in quiet["verdict"]
    assert quiet["criteria"]["vol_dip_1.0"]["label"] == ft.RECORD
    assert "not priced" in quiet["twin_line"]
    # A payload read back from JSON (NaN written as null) is judged the same.
    nulls = payload(3.0, 3.0, 0.5, 1.0)
    for r in nulls["rows"]:
        if r["window"] == ft.REPORTED:
            r["mean_daily_bp_vs_dip"] = None
    assert ft.level_verdict(nulls)["replaces"] == []


# The conventions a run prices: the registered set by default, the level
# four with forecasts, `only` plus the controls the verdicts read, and a
# refusal for an unknown name or a level convention without forecasts.
def test_select_conventions():
    assert ft.select_conventions(None, False) == ft.CONVENTIONS
    assert ft.select_conventions(None, True) == ft.ALL_CONVENTIONS
    assert ft.select_conventions(["vol_dip_1.0"], True) == (
        "next_open",
        "dip_or_close",
        "vol_dip_1.0",
        "trail_dip",
    )
    assert ft.select_conventions(["late_day"], False) == ("next_open", "late_day")
    assert ft.select_conventions(["late_day", " next_open "], True) == (
        "next_open",
        "late_day",
    )
    with pytest.raises(ValueError, match="unknown convention"):
        ft.select_conventions(["midnight"], True)
    with pytest.raises(ValueError, match="need the volatility forecasts"):
        ft.select_conventions(["vol_dip_0.5"], False)
    with pytest.raises(ValueError, match="need the volatility forecasts"):
        ft.select_conventions(["trail_dip"], False)


# Forecasts on any grid but the report's own are refused before a price is read.
def test_study_refuses_forecasts_off_the_grid():
    report, mask, cubes = base._world(t=60, n=4, seed=1)
    good = _aligned(report, _random_logvar(report, 1), _random_logvar(report, 2))
    ft.check_grid(good, report.panel)
    for bad in (
        vf.Aligned(
            good.dates[1:], good.tickers, good.forecast[1:], good.baseline[1:], None
        ),
        vf.Aligned(good.dates, good.tickers[::-1], good.forecast, good.baseline, None),
        vf.Aligned(
            good.dates + np.timedelta64(1, "D"),
            good.tickers,
            good.forecast,
            good.baseline,
            None,
        ),
    ):
        with pytest.raises(ValueError, match="not on the report's panel grid"):
            ft.study(report, cubes, mask, offsets=1, forecasts=bad)
    with pytest.raises(ValueError, match="sigma grid"):
        ft.cube_prices(cubes, report.panel, "vol_dip_0.5", np.zeros((3, 3)))


# The command prices the level trial from a forecasts npz: `--only` adds
# the controls and the twin, the payload goes to ml_entry_level.json (the
# fill-timing file is left alone) with the file's sha256 and metadata,
# every row carries the order fields, the fallback before the first
# forecast is counted, and the text holds both verdict lines. A level
# convention without --forecasts, an unknown name and a missing file are
# refused before the desk runs.
def test_cli_prices_the_level_trial(tmp_path):
    membership, fake_desk, sessions, names, calls = base._sip_store(tmp_path)
    dates = np.array(sessions, dtype="datetime64[D]")
    rng = np.random.default_rng(4)
    tickers = (*names, "SPY")
    forecast = 2.0 * np.log(rng.uniform(0.003, 0.02, size=(len(dates), len(tickers))))
    forecast[:20] = np.nan
    baseline = np.full(forecast.shape, 2.0 * math.log(0.01))
    baseline[:, -1] = np.nan
    path = vf.save_forecasts(
        tmp_path / "vol.npz", _file_rows(dates, tickers, forecast, baseline)
    )
    common = [
        "--root",
        str(tmp_path),
        "--membership",
        str(membership),
        "--workers",
        "1",
    ]
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            *common,
            "--offsets",
            "2",
            "--forecasts",
            str(path),
            "--only",
            "vol_dip_0.5,vol_limit_0.5",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    target = tmp_path / "desk" / "ml_entry_level.json"
    assert target.exists()
    assert not (tmp_path / "desk" / "fill_timing.json").exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["conventions"] == [
        "next_open",
        "dip_or_close",
        "vol_dip_0.5",
        "vol_limit_0.5",
        "trail_dip",
    ]
    assert payload["forecast_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert payload["forecast_file"] == str(path)
    assert payload["forecast_meta"] == {"model": "synthetic"}
    level = payload["level"]
    assert level["conventions"] == ["vol_dip_0.5", "vol_limit_0.5", "trail_dip"]
    assert level["verdict"].startswith((ft.REPLACES, ft.RECORD))
    assert set(level["criteria"]) == {"vol_dip_0.5", "vol_limit_0.5", "trail_dip"}
    assert level["first_forecast_session"] == str(dates[20])
    assert level["constants"]["LEVEL_TRIALS"] == 4
    assert len(payload["rows"]) == 5 * 3
    rows = {(r["convention"], r["window"]): r for r in payload["rows"]}
    for convention in ("vol_dip_0.5", "vol_limit_0.5", "trail_dip"):
        row = rows[(convention, "all")]
        assert row["dip_orders"] > 0
        assert 0.0 <= row["dip_fill_rate"] <= 1.0
        assert row["sigma_fallbacks"] > 0
    assert rows[("dip_or_close", "all")]["sigma_fallbacks"] == 0
    assert rows[("next_open", "all")]["dip_fill_rate"] is None
    assert payload["verdict"].startswith("NOT JUDGED")
    text = out.getvalue()
    assert "entry-level trial" in text
    assert "entry-level verdict:" in text
    assert "fill-timing verdict: NOT JUDGED" in text
    assert "vol_limit_0.5" in text
    assert calls == [str(tmp_path)]
    # Refusals, each before the desk runs.
    for extra, code, message in (
        (["--only", "vol_dip_0.5"], 2, "need the volatility forecasts"),
        (["--only", "midnight", "--forecasts", str(path)], 2, "unknown convention"),
        (["--forecasts", str(tmp_path / "missing.npz")], 1, "forecast file not found"),
    ):
        out = io.StringIO()
        args = cli.build_parser().parse_args([*common, *extra])
        assert cli.run(args, out, desk_run=fake_desk) == code
        assert message in out.getvalue()
    assert calls == [str(tmp_path)]
