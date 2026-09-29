"""Stage 4's fills and timing target, from the SIP cubes.

`docs/research/stage4-plan-2026-09-29.md` registers everything here; this
module computes nothing the plan did not fix.

**Prices.** Every price is on the panel's adjusted basis, so a level set at
t's close compares with a bar five sessions later even across a split. The
cubes are complete 26-bar sessions on the raw basis
(`sip_cube.SessionCube`). A cube price in session s is multiplied by
`cube_scale`: the panel's adjusted close over the cube's own official close
that session (`fill_timing.session_scale`, stage 3's rule). The daily
store's `close`, `high` and `low` are already split-adjusted, so
`adj_close / close` is a dividend factor only: it puts the panel's high and
low on the adjusted basis, and it must never scale a cube price (a raw
price before a split would then meet an adjusted level).

**The conventions.** Each applies to an order decided at session t's close
on one name, a buy or a sell. W is the plan's five sessions.

- `CONTROL`: the board's `dip_or_close` in session t+1, from
  `fill_timing._dip_or_close_fill`. A buy fills at the first bar whose close
  is at or below the open × 0.99, a sell at or above the open × 1.01, else
  at the official close.
- `LEVEL` (D0): rest at C_t·exp(−σ_t) for a buy or C_t·exp(+σ_t) for a
  sell, through sessions t+1..t+W. σ_t is the standard deviation (ddof 1)
  of the last 20 daily log close-to-close returns through t. The order fills
  at the first bar close at or past the level, else at the official close of
  t+W. All 26 bars can trigger, as the control's can.
- `TURN` (D2):
  - A buy acts only when C_t < EMA10_t. It fills at the official close of
    the first session in t+1..t+W that closes above the prior session's
    high, else at the close of t+W.
  - A sell acts only when C_t > EMA10_t, and mirrors this with the prior
    session's low.
  - An inactive order fills as the control.
- `SQUEEZE` (D3):
  - It acts only when the 20-day Bollinger bandwidth (4·sd₂₀/SMA20,
    ddof 0) at t is at or below the 10% quantile of its last 126 values.
  - A buy fills at the official close of the first session closing above
    that session's upper band (SMA20 + 2·sd₂₀, through the session), a sell
    below the lower band, else at the close of t+W.
  - An inactive order fills as the control.

**Validity.** A convention can price an order only if every session it may
need (t+1 for the control, t+1..t+W otherwise) is a complete cube session.
Otherwise its price is NaN. With `next_bar`, a fill at a bar's close moves
to the next bar's open, and a fill at the last bar or at the official close
stays at the official close.

**The timing target.** For each row, D0's gain over the control:

    g_buy  = 1e4 · ln(control_buy / level_buy)
    g_sell = 1e4 · ln(level_sell / control_sell)

It is NaN where either convention cannot be priced.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.market import fill_timing, stage3_features, technical
from backend.market import stage3_io as io
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

PLAN = "docs/research/stage4-plan-2026-09-29.md"
WINDOW = 5
SIGMA_SESSIONS = 20
EMA_SPAN = 10
BAND_SESSIONS = 20
BAND_WIDTH = 2.0
SQUEEZE_LOOKBACK = 126
SQUEEZE_QUANTILE = 0.10
CONTROL = "control"
LEVEL = "level"
TURN = "turn"
SQUEEZE = "squeeze"
CONVENTIONS = (CONTROL, LEVEL, TURN, SQUEEZE)
SIDES = ("buy", "sell")


@dataclass(frozen=True)
class Fills:
    """One convention's fills for every decision session t of one name."""

    price: np.ndarray  # (T,) adjusted fill price, NaN where it cannot be priced
    days: np.ndarray  # (T,) int: the session of the fill after t (1..W), 0 where NaN
    reached: np.ndarray  # (T,) bool: filled at its trigger rather than a fallback
    active: np.ndarray  # (T,) bool: the rule acted (always true for control and level)


@dataclass(frozen=True)
class NameSeries:
    """One name's panel columns (adjusted) and indicators, T sessions."""

    dates: np.ndarray  # (T,) datetime64[D]
    factor: np.ndarray  # (T,) adj_close / close: the dividend factor of the panel's high and low
    close: np.ndarray  # (T,) adjusted close
    high: np.ndarray  # (T,) adjusted high
    low: np.ndarray  # (T,) adjusted low
    sigma: np.ndarray  # (T,) sd of the last 20 log returns through t
    ema10: np.ndarray  # (T,)
    upper: np.ndarray  # (T,) SMA20 + 2 sd20 through t
    lower: np.ndarray  # (T,) SMA20 - 2 sd20 through t
    squeeze: np.ndarray  # (T,) bool


# The indicators the rules read, from one name's adjusted closes: sigma,
# EMA10, the Bollinger bands and the squeeze flag. Every value at row t
# reads rows through t only.
def name_series(
    dates: np.ndarray, close_raw: np.ndarray, adj_close: np.ndarray, high_raw: np.ndarray, low_raw: np.ndarray
) -> NameSeries:
    """Return the NameSeries of one name's panel columns."""
    close_raw = np.asarray(close_raw, dtype=float)
    adj = np.asarray(adj_close, dtype=float)
    with np.errstate(all="ignore"):
        factor = np.where(close_raw > 0, adj / close_raw, np.nan)
        logret = np.log(adj / stage3_features.lag(adj, 1))
    column = adj[:, None]
    sigma = stage3_features.rolling_std(logret[:, None], SIGMA_SESSIONS)[:, 0]
    ema10 = technical.ema(column, EMA_SPAN)[:, 0]
    mid = stage3_features.rolling_mean(column, BAND_SESSIONS)[:, 0]
    sd = stage3_features.rolling_std(column, BAND_SESSIONS, ddof=0)[:, 0]
    upper = mid + BAND_WIDTH * sd
    lower = mid - BAND_WIDTH * sd
    with np.errstate(all="ignore"):
        width = np.where(mid > 0, 2 * BAND_WIDTH * sd / mid, np.nan)
    return NameSeries(
        dates=np.asarray(dates, dtype="datetime64[D]"),
        factor=factor,
        close=adj,
        high=np.asarray(high_raw, dtype=float) * factor,
        low=np.asarray(low_raw, dtype=float) * factor,
        sigma=sigma,
        ema10=ema10,
        upper=upper,
        lower=lower,
        squeeze=squeeze_flag(width),
    )


# True at t when the bandwidth is at or below the 10% quantile of its last
# 126 values (t included), all finite; False otherwise.
def squeeze_flag(width: np.ndarray) -> np.ndarray:
    """Return the (T,) squeeze flag of a bandwidth series."""
    width = np.asarray(width, dtype=float)
    out = np.zeros(len(width), dtype=bool)
    n = SQUEEZE_LOOKBACK
    if len(width) < n:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(width, n)
    complete = np.isfinite(windows).all(axis=1)
    with np.errstate(all="ignore"):
        cut = np.quantile(np.where(complete[:, None], windows, 0.0), SQUEEZE_QUANTILE, axis=1)
    out[n - 1 :] = complete & (width[n - 1 :] <= cut)
    return out


# The scale that moves each panel session's cube prices onto the adjusted
# basis: the panel's adjusted close over the cube's own official close that
# session (`fill_timing.session_scale`), NaN where the cube has no session.
# On the adjusted basis a session's official close is its adjusted close.
def cube_scale(series: NameSeries, cube: SessionCube) -> np.ndarray:
    """Return the (T,) adjusted/raw scale of each panel session's cube prices."""
    out = np.full(len(series.dates), np.nan)
    if not len(cube):
        return out
    pos, ok, scale = fill_timing.session_scale(cube, series.dates, series.close)
    out[pos[ok]] = scale[ok]
    return out


# Each panel session's row in the cube, -1 where the cube has no complete
# session on that date.
def cube_rows(dates: np.ndarray, cube: SessionCube) -> np.ndarray:
    """Return the (T,) cube row of every panel session."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    days = np.asarray(cube.dates, dtype="datetime64[D]")
    at = np.clip(np.searchsorted(days, dates), 0, max(len(days) - 1, 0))
    hit = (len(days) > 0) & (days[at] == dates) if len(days) else np.zeros(len(dates), dtype=bool)
    return np.where(hit, at, -1).astype(np.int64)


# The price of a fill at bar `slot` of cube row `row`: the bar's close, or
# with `next_bar` the next bar's open (the official close past the last bar).
def _bar_fill(cube: SessionCube, official: np.ndarray, row: np.ndarray, slot: np.ndarray, next_bar: bool) -> np.ndarray:
    if not next_bar:
        return cube.close[row, slot]
    later = slot + 1
    return np.where(
        later < FULL_SESSION_SLOTS,
        cube.open[row, np.minimum(later, FULL_SESSION_SLOTS - 1)],
        official[row],
    )


# The control and the three rules for every decision session of one name,
# both sides, on the adjusted basis. `window` is W.
def name_fills(
    series: NameSeries, cube: SessionCube, window: int = WINDOW, next_bar: bool = False
) -> dict[tuple[str, str], Fills]:
    """Return {(convention, side): Fills} for one name."""
    T = len(series.dates)
    if not len(cube):
        empty = Fills(np.full(T, np.nan), np.zeros(T, dtype=np.int64), np.zeros(T, dtype=bool), np.ones(T, dtype=bool))
        return {(c, s): empty for c in CONVENTIONS for s in SIDES}
    rows = cube_rows(series.dates, cube)
    official_raw = fill_timing._official_close(cube)
    ahead = np.full((T, window), -1, dtype=np.int64)
    for j in range(1, window + 1):
        ahead[: T - j, j - 1] = rows[j:]
    full = (ahead >= 0).all(axis=1)
    first_ok = ahead[:, 0] >= 0
    scale = cube_scale(series, cube)
    scale_ahead = np.full((T, window), np.nan)
    for j in range(1, window + 1):
        scale_ahead[: T - j, j - 1] = scale[j:]
    official_ahead = np.where(ahead >= 0, official_raw[np.maximum(ahead, 0)], np.nan) * scale_ahead
    out: dict[tuple[str, str], Fills] = {}
    t_all = np.arange(T)
    for side in SIDES:
        sign = -1.0 if side == "buy" else 1.0
        # The control, session t+1.
        raw, hit = fill_timing._dip_or_close_fill(cube, side, next_bar)
        price = np.full(T, np.nan)
        reached = np.zeros(T, dtype=bool)
        ok = first_ok & np.isfinite(scale_ahead[:, 0])
        price[ok] = raw[ahead[ok, 0]] * scale_ahead[ok, 0]
        reached[ok] = hit[ahead[ok, 0]]
        control = Fills(price, np.where(ok, 1, 0), reached, np.ones(T, dtype=bool))
        out[(CONTROL, side)] = control
        # D0: the multi-day level.
        level = series.close * np.exp(sign * series.sigma)
        lv_price = np.full(T, np.nan)
        lv_days = np.zeros(T, dtype=np.int64)
        lv_reached = np.zeros(T, dtype=bool)
        valid = full & np.isfinite(level) & np.isfinite(scale_ahead).all(axis=1)
        pending = valid.copy()
        for j in range(window):
            idx = t_all[pending]
            if not len(idx):
                break
            crow = ahead[idx, j]
            closes = cube.close[crow] * scale_ahead[idx, j][:, None]
            touch = closes <= level[idx, None] if side == "buy" else closes >= level[idx, None]
            anyhit = touch.any(axis=1)
            slot = np.argmax(touch, axis=1)
            filled = idx[anyhit]
            lv_price[filled] = (
                _bar_fill(cube, official_raw, crow[anyhit], slot[anyhit], next_bar) * scale_ahead[filled, j]
            )
            lv_days[filled] = j + 1
            lv_reached[filled] = True
            pending[filled] = False
        rest = t_all[pending]
        lv_price[rest] = official_ahead[rest, window - 1]
        lv_days[rest] = window
        out[(LEVEL, side)] = Fills(lv_price, lv_days, lv_reached, np.ones(T, dtype=bool))
        # D2 (turn) and D3 (squeeze): daily closes against a daily trigger.
        with np.errstate(invalid="ignore"):
            turn_active = series.close < series.ema10 if side == "buy" else series.close > series.ema10
        prior_high = np.full((T, window), np.nan)
        prior_low = np.full((T, window), np.nan)
        band = np.full((T, window), np.nan)
        for j in range(window):
            # Session t+1+j's prior session is t+j.
            prior_high[: T - j, j] = series.high[j:]
            prior_low[: T - j, j] = series.low[j:]
            src = series.upper if side == "buy" else series.lower
            band[: T - j - 1, j] = src[j + 1 :]
        with np.errstate(invalid="ignore"):
            if side == "buy":
                turn_trigger = official_ahead > prior_high
                squeeze_trigger = official_ahead > band
            else:
                turn_trigger = official_ahead < prior_low
                squeeze_trigger = official_ahead < band
        for name, active, trigger in (
            (TURN, turn_active & np.isfinite(series.ema10), turn_trigger),
            (SQUEEZE, series.squeeze, squeeze_trigger),
        ):
            out[(name, side)] = _daily_rule(control, active, trigger, official_ahead, full, window)
    return out


# A rule that, when active at t, fills at the official close of the first
# session in t+1..t+W whose trigger holds, else at the close of t+W; an
# inactive order fills as the control. An active order needs all W
# sessions.
def _daily_rule(
    control: Fills,
    active: np.ndarray,
    trigger: np.ndarray,
    official_ahead: np.ndarray,
    full: np.ndarray,
    window: int,
) -> Fills:
    T = len(active)
    active = np.asarray(active, dtype=bool)
    price = control.price.copy()
    days = control.days.copy()
    reached = control.reached.copy()
    on = active & full & np.isfinite(official_ahead).all(axis=1)
    price[active] = np.nan
    days[active] = 0
    reached[active] = False
    trig = np.asarray(trigger, dtype=bool)
    anyhit = trig.any(axis=1)
    first = np.argmax(trig, axis=1)
    rows = np.flatnonzero(on)
    hit_rows = rows[anyhit[rows]]
    miss_rows = rows[~anyhit[rows]]
    price[hit_rows] = official_ahead[hit_rows, first[hit_rows]]
    days[hit_rows] = first[hit_rows] + 1
    reached[hit_rows] = True
    price[miss_rows] = official_ahead[miss_rows, window - 1]
    days[miss_rows] = window
    return Fills(price, days, reached, active & np.ones(T, dtype=bool))


# The per-order gain of a candidate fill over the control, in bp of the
# order: a buy gains when it pays less, a sell when it receives more.
def gain(control: np.ndarray, candidate: np.ndarray, side: str) -> np.ndarray:
    """Return 1e4 * ln(control / candidate) for buys, ln(candidate / control) for sells."""
    control = np.asarray(control, dtype=float)
    candidate = np.asarray(candidate, dtype=float)
    with np.errstate(all="ignore"):
        ratio = control / candidate if side == "buy" else candidate / control
        return 1e4 * np.log(ratio)


@dataclass(frozen=True)
class Labels:
    """The timing target for a T-S1 dataset's rows, in its row order."""

    g_buy: np.ndarray  # (R,) bp, NaN where not priced
    g_sell: np.ndarray  # (R,)
    meta: dict[str, Any]


# The two labels for every row of a T-S1 dataset: D0 against the control,
# per side, from the panel columns and the cubes. `panel` needs dates,
# tickers, close, adj_close, high and low; a ticker without a cube gets NaN.
def label_rows(
    data: io.Stage3Data,
    panel: Any,
    cubes: Mapping[str, SessionCube],
    log: Callable[[str], None] | None = None,
) -> Labels:
    """Return the Labels of `data`'s rows."""
    if data.kind != io.S1:
        raise ValueError(f"stage 4 labels T-S1 rows, not {data.kind!r}")
    began = time.perf_counter()
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    column = {str(t): j for j, t in enumerate(panel.tickers)}
    row_dates = np.asarray(data.dates, dtype="datetime64[D]")
    row_tickers = np.asarray(data.tickers).astype(str)
    g_buy = np.full(len(data), np.nan)
    g_sell = np.full(len(data), np.nan)
    counts = {"rows": int(len(data)), "no_cube": 0, "not_on_panel": 0}
    reached = {"buy": [0, 0], "sell": [0, 0]}
    for ticker in np.unique(row_tickers):
        mine = np.flatnonzero(row_tickers == ticker)
        j = column.get(ticker)
        cube = cubes.get(ticker)
        if j is None:
            counts["not_on_panel"] += len(mine)
            continue
        if cube is None or not len(cube):
            counts["no_cube"] += len(mine)
            continue
        series = name_series(dates, panel.close[:, j], panel.adj_close[:, j], panel.high[:, j], panel.low[:, j])
        fills = name_fills(series, cube)
        at = np.searchsorted(dates, row_dates[mine])
        on_panel = (at < len(dates)) & (dates[np.minimum(at, len(dates) - 1)] == row_dates[mine])
        counts["not_on_panel"] += int((~on_panel).sum())
        rows = mine[on_panel]
        t = at[on_panel]
        for side, target in (("buy", g_buy), ("sell", g_sell)):
            ctrl = fills[(CONTROL, side)].price[t]
            cand = fills[(LEVEL, side)].price[t]
            target[rows] = gain(ctrl, cand, side)
            lv = fills[(LEVEL, side)]
            priced = np.isfinite(cand)
            reached[side][0] += int(priced.sum())
            reached[side][1] += int((lv.reached[t] & priced).sum())
        if log is not None:
            log(f"  {ticker:<6} {len(rows):>5} rows ({time.perf_counter() - began:.0f} s)")
    meta = {
        "plan": PLAN,
        "window": WINDOW,
        "counts": counts,
        "priced": {s: int(np.isfinite(v).sum()) for s, v in (("buy", g_buy), ("sell", g_sell))},
        "level_reached_share": {s: (v[1] / v[0] if v[0] else float("nan")) for s, v in reached.items()},
        "seconds": time.perf_counter() - began,
    }
    return Labels(g_buy, g_sell, meta)
