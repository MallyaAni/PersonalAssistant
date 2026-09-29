"""Stage 3's intraday block: every fifteen-minute input of the plan at the close of slot k.

`docs/research/stage3-plan-2026-09-29.md` ("Intraday block") fixes the rule
of the moment: a feature at the close of slot k reads the complete SIP bars
0..k-1 (open, high, low, close, volume) and only the close C_k of bar k.
Live, prices arrive in real time from IEX and consolidated bars fifteen
minutes late, so that is what the board can know; `test_stage3_intraday`
tampers with bar k's high, low and volume and every field of later bars and
asserts row k is unchanged.

Per name, everything is computed at once over its cube sessions as (S, 24)
arrays (slots 0..23, the bars closing 09:45..15:30) and returned as a
`NameBlock`; the export stacks the rows it keeps. Units: sigma_slot(j) is
the root mean square of the name's bar-j return over the prior 60 cube
sessions (r_0 = ln(C_0/O_0)); sigma_open(k) the standard deviation of
ln(C_k/O_0) at the same k over the prior 60 sessions; sigma15 the standard
deviation of all its 15-minute returns over the prior 60 sessions; ATR14 the
daily ATR fraction at t, the panel session before s. Every trailing window
ends the session before s.

Prices. Intraday comparisons are on the session's own raw basis (the cube's).
Daily levels are brought onto it by the prior close: scale_s = adj_close[t]
/ prior_close[s], so ln(C_k * scale_s / L_adj) is the distance to an
adjusted level L_adj and the prior day's close sits exactly at the gap.
Unlike `fill_timing.session_scale`, this never reads session s's own close.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from backend.market import sr_levels
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.market.stage3_features import lag, rolling_mean, rolling_std, wilder
from backend.market.stage3_io import INTRADAY_PREFIX, TI_SLOTS

# Trailing sessions of the per-slot scales and of relative volume.
SCALE_SESSIONS = 60
RVOL_SESSIONS = 20
# Cube sessions of warm-up before the 15-minute EMAs and RSI count.
EMA_WARMUP_SESSIONS = 3
# The hourly bars: the 15-minute slots whose close ends each hour (the
# last is the 15:30-16:00 half hour).
HOUR_END_SLOTS = (3, 7, 11, 15, 19, 23, 25)
# The IS family groups of the nearest support.
IS_GROUPS = {
    "intraday": ("opening_range", "vwap", "prior_day"),
    "swing": ("swing_20", "swing_60", "swing_250"),
    "average": ("sma_50", "sma_200", "wsma_21"),
    "range": ("range_52w", "prior_week"),
    "node": ("volume_node",),
}

SLOTS = np.arange(TI_SLOTS)


@dataclass(frozen=True)
class NameBlock:
    """One name's intraday columns over its cube sessions: (S, 24, F)."""

    dates: np.ndarray  # (S,) the cube's sessions
    names: tuple[str, ...]  # F, each with INTRADAY_PREFIX
    values: np.ndarray  # (S, 24, F) float32


@dataclass(frozen=True)
class Breadth:
    """Market breadth per (session, slot) across the eligible names."""

    dates: np.ndarray  # (D,) sessions
    up: np.ndarray  # (D, 26) share with C_k above the prior close
    above_vwap: np.ndarray  # (D, 26) share with C_k above their VWAP through k-1
    sign: np.ndarray  # (D, 26) mean sign of the bar-k return


# ---------------------------------------------------------------------------
# Per-session primitives.
# ---------------------------------------------------------------------------


# Log of a ratio, NaN where it is not a finite positive ratio.
def _log(x: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        out = np.log(np.asarray(x, dtype=float))
    return np.where(np.isfinite(out), out, np.nan)


# The (S, 26) bar log returns with slot 0 on the session's open.
def bar_returns(cube: SessionCube) -> np.ndarray:
    """Return r[s, j] = ln(C_j / C_{j-1}), r[s, 0] = ln(C_0 / O_0)."""
    previous = np.column_stack([cube.open[:, :1], cube.close[:, :-1]])
    return _log(cube.close / previous)


# The VWAP through each bar (the bar included), typical price weighted by
# volume: (S, 26), NaN before any volume.
def vwap_through(cube: SessionCube) -> np.ndarray:
    """Return VWAP_j over bars 0..j of each session."""
    typical = (cube.high + cube.low + cube.close) / 3.0
    volume = np.asarray(cube.volume, dtype=float)
    traded = np.cumsum(np.where(np.isfinite(typical) & np.isfinite(volume), typical * volume, 0.0), axis=1)
    shares = np.cumsum(np.where(np.isfinite(volume), volume, 0.0), axis=1)
    with np.errstate(all="ignore"):
        return np.where(shares > 0, traded / shares, np.nan)


# A (S, 26) array read at "through bar k-1" for each slot k: column k holds
# column k-1 of `through`, column 0 NaN.
def through_previous(through: np.ndarray) -> np.ndarray:
    """Return the value through bar k-1 at slot k."""
    out = np.full(through.shape, np.nan)
    out[:, 1:] = through[:, :-1]
    return out


# The running min (or max) over bars 0..k-1 at each slot k, NaN at k = 0.
def running_previous(values: np.ndarray, largest: bool) -> np.ndarray:
    """Return the extreme of bars 0..k-1 at slot k."""
    accumulate = np.fmax.accumulate if largest else np.fmin.accumulate
    return through_previous(accumulate(values, axis=1))


# A per-session trailing statistic of a per-session series, over the
# `n` cube sessions before each session (the session itself excluded).
def prior_sessions(values: np.ndarray, n: int, stat: str) -> np.ndarray:
    """Return the mean, std or rms of the n previous sessions' values."""
    if stat == "mean":
        return lag(rolling_mean(values, n), 1)
    if stat == "std":
        return lag(rolling_std(values, n), 1)
    if stat == "rms":
        return np.sqrt(lag(rolling_mean(values * values, n), 1))
    raise ValueError(f"unknown stat {stat!r}")


# An EMA over a 1-D series with the standard 2/(span+1) weight, NaN-free
# input assumed; seeded with the first value.
def _ema_1d(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty(len(values))
    state = np.nan
    for i, v in enumerate(values):
        if not np.isfinite(v):
            out[i] = state
            continue
        state = v if not np.isfinite(state) else alpha * v + (1.0 - alpha) * state
        out[i] = state
    return out


# ---------------------------------------------------------------------------
# Breadth, once for all names.
# ---------------------------------------------------------------------------


# Breadth per (session, slot) over every name eligible for that session:
# the share whose bar-k close is above its prior close, the share above its
# VWAP through bar k-1, and the mean sign of the bar-k return. `eligible`
# maps ticker -> (S,) bool over its cube sessions.
def breadth(cubes: Mapping[str, SessionCube], eligible: Mapping[str, np.ndarray]) -> Breadth:
    """Return the Breadth of the eligible names."""
    dates = np.unique(np.concatenate([c.dates for c in cubes.values() if len(c)] or [np.array([], dtype="datetime64[D]")]))
    count = np.zeros((len(dates), FULL_SESSION_SLOTS))
    up = np.zeros_like(count)
    above = np.zeros_like(count)
    vwap_count = np.zeros_like(count)
    sign = np.zeros_like(count)
    for ticker, cube in cubes.items():
        keep = eligible.get(ticker)
        if keep is None or len(cube) == 0 or not keep.any():
            continue
        rows = np.searchsorted(dates, cube.dates[keep])
        close = cube.close[keep]
        prior = cube.prior_close[keep][:, None]
        vwap = through_previous(vwap_through(cube))[keep]
        r = bar_returns(cube)[keep]
        live = np.isfinite(close) & np.isfinite(prior)
        np.add.at(count, rows, live.astype(float))
        np.add.at(up, rows, (live & (close > prior)).astype(float))
        known = np.isfinite(vwap) & np.isfinite(close)
        np.add.at(vwap_count, rows, known.astype(float))
        np.add.at(above, rows, (known & (close > vwap)).astype(float))
        np.add.at(sign, rows, np.where(np.isfinite(r), np.sign(r), 0.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        return Breadth(
            dates=dates,
            up=np.where(count > 0, up / count, np.nan),
            above_vwap=np.where(vwap_count > 0, above / vwap_count, np.nan),
            sign=np.where(count > 0, sign / count, np.nan),
        )


# ---------------------------------------------------------------------------
# One name.
# ---------------------------------------------------------------------------


# The row of each of `dates` in a benchmark cube, and whether it is there.
def _align(cube: SessionCube | None, dates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if cube is None or len(cube) == 0:
        return np.zeros(len(dates), dtype=np.int64), np.zeros(len(dates), dtype=bool)
    pos = np.searchsorted(cube.dates, dates)
    ok = (pos < len(cube)) & (cube.dates[np.minimum(pos, len(cube) - 1)] == dates)
    return np.minimum(pos, len(cube) - 1), ok


# A benchmark's (S, 26) array on the name's sessions, NaN where it lacks one.
def _bench(values: np.ndarray, pos: np.ndarray, ok: np.ndarray) -> np.ndarray:
    out = np.full((len(pos),) + values.shape[1:], np.nan)
    out[ok] = values[pos[ok]]
    return out


# The intraday block of one name. `daily` holds, per cube session s, the
# values at t = the panel session before s: ATR14 as a fraction ("atr"),
# the adjusted prior-day high, low and close ("pdh", "pdl", "pdc"), the
# adjusted close at t ("adj_close_t"), the 60-session betas to SPY and to
# the side ETF ("beta_spy", "beta_side") and the daily, weekly and monthly
# trend states ("trend_daily", "trend_weekly", "trend_monthly"); each (S,).
# `levels` is the name's sr_levels.DailyLevels view (levels in force during
# each cube session, adjusted, and the zone half-width), or None.
def name_block(
    cube: SessionCube,
    daily: Mapping[str, np.ndarray],
    spy: SessionCube | None,
    qqq: SessionCube | None,
    side: SessionCube | None,
    market: Breadth | None,
    levels: tuple[np.ndarray, np.ndarray] | None = None,
) -> NameBlock:
    """Return the NameBlock of one name's cube sessions."""
    sessions = len(cube)
    k_index = SLOTS[None, :]
    open0 = cube.open[:, 0]
    close = cube.close
    prior = cube.prior_close
    r = bar_returns(cube)
    since = _log(close / open0[:, None])
    gap = _log(open0 / prior)
    columns: dict[str, np.ndarray] = {}

    def slots(values: np.ndarray) -> np.ndarray:
        return np.asarray(values, dtype=float)[:, :TI_SLOTS]

    def each(values: np.ndarray) -> np.ndarray:
        return np.repeat(np.asarray(values, dtype=float)[:, None], TI_SLOTS, axis=1)

    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        # Scales from the prior 60 sessions.
        sigma_slot = np.column_stack([prior_sessions(r[:, j], SCALE_SESSIONS, "rms") for j in range(FULL_SESSION_SLOTS)])
        sigma_open = np.column_stack([prior_sessions(since[:, j], SCALE_SESSIONS, "std") for j in range(FULL_SESSION_SLOTS)])
        sigma_gap = prior_sessions(gap, SCALE_SESSIONS, "std")
        per_session_sq = np.nansum(r * r, axis=1)
        per_session_sum = np.nansum(r, axis=1)
        n_bars = FULL_SESSION_SLOTS * SCALE_SESSIONS
        mean15 = lag(rolling_mean(per_session_sum, SCALE_SESSIONS), 1) / FULL_SESSION_SLOTS
        meansq15 = lag(rolling_mean(per_session_sq, SCALE_SESSIONS), 1) / FULL_SESSION_SLOTS
        sigma15 = np.sqrt(np.maximum(meansq15 - mean15 * mean15, 0.0) * n_bars / (n_bars - 1))
        atr = np.asarray(daily["atr"], dtype=float)

        # I00 time.
        columns["slot"] = np.repeat(SLOTS[None, :].astype(float), sessions, axis=0)
        columns["minutes_to_close"] = 390.0 - 15.0 * (columns["slot"] + 1.0)
        # I01 gap.
        columns["gap"] = each(gap)
        columns["gap_z"] = each(gap / sigma_gap)
        # I02 since the open.
        columns["since_open"] = slots(since)
        columns["since_open_z"] = slots(since / sigma_open)
        # I03 slot-normalized returns, this bar and the two before.
        z = r / sigma_slot
        columns["z0"] = slots(z)
        columns["z1"] = slots(through_previous(z))
        z2 = np.full(z.shape, np.nan)
        z2[:, 2:] = z[:, :-2]
        columns["z2"] = slots(z2)
        # I04 opening range over 1 and 2 bars, from slot m on.
        for m in (1, 2):
            hi = np.max(cube.high[:, :m], axis=1)
            lo = np.min(cube.low[:, :m], axis=1)
            formed = k_index >= m
            span = (hi - lo)[:, None]
            c = slots(close)
            columns[f"or{m}_position"] = np.where(formed, np.where(span > 0, (c - lo[:, None]) / span, np.nan), np.nan)
            columns[f"or{m}_width"] = np.where(formed, each(_log(hi / lo) / atr), np.nan)
            columns[f"or{m}_above"] = np.where(formed, (c > hi[:, None]).astype(float), np.nan)
            columns[f"or{m}_below"] = np.where(formed, (c < lo[:, None]).astype(float), np.nan)
        # I05 VWAP through bar k-1.
        vwap = vwap_through(cube)
        vwap_prev = through_previous(vwap)
        columns["vwap_dist"] = slots(_log(close / vwap_prev) / sigma_open)
        above_vwap = np.where(np.isfinite(vwap), (close > vwap).astype(float), np.nan)
        share = np.cumsum(np.nan_to_num(above_vwap), axis=1) / np.arange(1, FULL_SESSION_SLOTS + 1)[None, :]
        columns["vwap_share_above"] = slots(through_previous(share))
        flips = np.zeros(close.shape)
        flips[:, 1:] = (np.nan_to_num(above_vwap[:, 1:]) != np.nan_to_num(above_vwap[:, :-1])).astype(float)
        columns["vwap_crosses"] = slots(through_previous(np.cumsum(flips, axis=1)))
        # I06 relative volume through bar k-1.
        volume = np.asarray(cube.volume, dtype=float)
        cumulative = np.cumsum(np.nan_to_num(volume), axis=1)
        typical_cum = np.column_stack([prior_sessions(cumulative[:, j], RVOL_SESSIONS, "mean") for j in range(FULL_SESSION_SLOTS)])
        rvol = _log(cumulative / typical_cum)
        columns["rvol"] = slots(through_previous(rvol))
        opening = _log(volume[:, 0] / prior_sessions(volume[:, 0], RVOL_SESSIONS, "mean"))
        columns["rvol_open"] = np.where(k_index >= 1, each(opening), np.nan)
        # I07-I09 the prior day's levels, on session s's raw basis.
        scale = np.asarray(daily["adj_close_t"], dtype=float) / prior
        pdh = np.asarray(daily["pdh"], dtype=float) / scale
        pdl = np.asarray(daily["pdl"], dtype=float) / scale
        pdc = prior
        c = slots(close)
        for name, level in (("pdh", pdh), ("pdl", pdl), ("pdc", pdc)):
            columns[f"{name}_dist"] = _log(c / level[:, None]) / atr[:, None]
        low_before = running_previous(cube.low, largest=False)
        high_before = running_previous(cube.high, largest=True)
        columns["broke_pdl"] = ((np.fmin(slots(low_before), c) <= pdl[:, None])).astype(float)
        columns["broke_pdh"] = ((np.fmax(slots(high_before), c) >= pdh[:, None])).astype(float)
        for name in ("broke_pdl", "broke_pdh"):
            columns[name] = np.where(np.isfinite(pdl)[:, None] & np.isfinite(c), columns[name], np.nan)
        pivot = (pdh + pdl + pdc) / 3.0
        spread = pdh - pdl
        floor = {
            "pivot_p": pivot, "pivot_r1": 2 * pivot - pdl, "pivot_s1": 2 * pivot - pdh,
            "pivot_r2": pivot + spread, "pivot_s2": pivot - spread,
            "cam_h3": pdc + 1.1 * spread / 4, "cam_l3": pdc - 1.1 * spread / 4,
            "cam_h4": pdc + 1.1 * spread / 2, "cam_l4": pdc - 1.1 * spread / 2,
        }
        for name, level in floor.items():
            columns[f"{name}_dist"] = _log(c / level[:, None]) / atr[:, None]
        # I10 drawdown and run-up since the open.
        lowest = np.fmin(np.fmin(slots(low_before), c), open0[:, None])
        highest = np.fmax(np.fmax(slots(high_before), c), open0[:, None])
        columns["drawdown"] = _log(lowest / open0[:, None]) / slots(sigma_open)
        columns["runup"] = _log(highest / open0[:, None]) / slots(sigma_open)
        columns["range_position"] = np.where(highest > lowest, (c - lowest) / (highest - lowest), np.nan)
        # I11 15-minute EMAs and RSI over the name's consecutive cube closes.
        flat = close.reshape(-1)
        ema9 = _ema_1d(flat, 9).reshape(close.shape)
        ema21 = _ema_1d(flat, 21).reshape(close.shape)
        warm = np.arange(sessions)[:, None] >= EMA_WARMUP_SESSIONS
        ema9 = np.where(warm, ema9, np.nan)
        ema21 = np.where(warm, ema21, np.nan)
        columns["ema9_15m_dist"] = slots(_log(close / ema9)) / sigma15[:, None]
        columns["ema21_15m_dist"] = slots(_log(close / ema21)) / sigma15[:, None]
        ema9_flat = ema9.reshape(-1)
        slope = np.full(ema9_flat.shape, np.nan)
        slope[3:] = _log(ema9_flat[3:] / ema9_flat[:-3])
        columns["ema9_15m_slope3"] = slots(slope.reshape(close.shape)) / sigma15[:, None]
        side_of_ema = np.where(np.isfinite(ema9), (close > ema9).astype(float), np.nan)
        crossed = np.zeros(close.shape)
        crossed[:, 1:] = (np.nan_to_num(side_of_ema[:, 1:]) != np.nan_to_num(side_of_ema[:, :-1])).astype(float)
        columns["ema9_15m_crosses"] = slots(np.where(np.isfinite(ema9), np.cumsum(crossed, axis=1), np.nan))
        change = np.diff(flat, prepend=np.nan)
        gain = wilder(np.where(np.isfinite(change), np.fmax(change, 0.0), np.nan), 14)
        loss = wilder(np.where(np.isfinite(change), np.fmax(-change, 0.0), np.nan), 14)
        rsi = np.where(loss > 0, 100.0 - 100.0 / (1.0 + gain / loss), np.where(gain > 0, 100.0, 50.0))
        rsi = np.where(np.isfinite(gain) & np.isfinite(loss), rsi, np.nan).reshape(close.shape)
        columns["rsi14_15m"] = slots(np.where(warm, rsi, np.nan))
        # I12 realized measures through bar k.
        zz = np.nan_to_num(z * z)
        rv = np.cumsum(zz, axis=1)
        columns["rv_intraday"] = slots(rv)
        columns["rs_minus_intraday"] = slots(np.where(rv > 0, np.cumsum(np.where(r < 0, zz, 0.0), axis=1) / rv, np.nan))
        columns["max_abs_z"] = slots(np.fmax.accumulate(np.abs(z), axis=1))
        known_z = np.isfinite(sigma_slot).all(axis=1)[:, None]
        for name in ("rv_intraday", "rs_minus_intraday", "max_abs_z"):
            columns[name] = np.where(known_z, columns[name], np.nan)
        # I13 and I14 against the market and the side ETF.
        dates = np.asarray(cube.dates, dtype="datetime64[D]")
        bench = {}
        for label, bcube in (("spy", spy), ("qqq", qqq), ("side", side)):
            pos, ok = _align(bcube, dates)
            if bcube is None or not ok.any():
                bench[label] = None
                continue
            bench[label] = {
                "open": _bench(bcube.open[:, 0], pos, ok),
                "close": _bench(bcube.close, pos, ok),
                "prior": _bench(bcube.prior_close, pos, ok),
                "vwap": _bench(through_previous(vwap_through(bcube)), pos, ok),
            }
        for label, beta_key in (("side", "beta_side"), ("spy", "beta_spy")):
            b = bench.get(label)
            if b is None:
                columns[f"rel_{label}"] = np.full((sessions, TI_SLOTS), np.nan)
                continue
            b_since = _log(b["close"] / b["open"][:, None])
            beta = np.asarray(daily[beta_key], dtype=float)[:, None]
            columns[f"rel_{label}"] = (slots(since) - beta * slots(b_since)) / slots(sigma_open)
        spy_b = bench.get("spy")
        if spy_b is not None:
            r1 = _log(spy_b["close"][:, 1] / spy_b["prior"])
            columns["spy_r1"] = np.where(k_index >= 1, each(r1), np.nan)
            columns["spy_since_open"] = slots(_log(spy_b["close"] / spy_b["open"][:, None]))
            columns["spy_vwap_dist"] = slots(_log(spy_b["close"] / spy_b["vwap"]))
            r12 = _log(spy_b["close"][:, 23] / spy_b["close"][:, 21])
            columns["spy_r12"] = np.where(k_index == 23, each(r12), np.nan)
        else:
            for name in ("spy_r1", "spy_since_open", "spy_vwap_dist", "spy_r12"):
                columns[name] = np.full((sessions, TI_SLOTS), np.nan)
        for label in ("qqq", "side"):
            b = bench.get(label)
            columns[f"{label}_since_open"] = (
                slots(_log(b["close"] / b["open"][:, None])) if b is not None else np.full((sessions, TI_SLOTS), np.nan)
            )
        # I15 breadth.
        if market is not None:
            pos = np.searchsorted(market.dates, dates)
            ok = (pos < len(market.dates)) & (market.dates[np.minimum(pos, len(market.dates) - 1)] == dates)
            for name, values in (("breadth_up", market.up), ("breadth_above_vwap", market.above_vwap), ("breadth_sign", market.sign)):
                out = np.full((sessions, TI_SLOTS), np.nan)
                out[ok] = values[pos[ok], :TI_SLOTS]
                columns[name] = out
        else:
            for name in ("breadth_up", "breadth_above_vwap", "breadth_sign"):
                columns[name] = np.full((sessions, TI_SLOTS), np.nan)
        # IS support and resistance at slot k from the 22 levels in force.
        columns.update(_support_resistance(cube, scale, atr, levels))
        # IT trend by timeframe and the five-timeframe alignment.
        state15 = _state(close, ema9, ema21)
        columns["trend_15m"] = slots(state15)
        state60 = _hourly_state(close)
        columns["trend_60m"] = slots(state60)
        align = columns["trend_15m"] + columns["trend_60m"]
        for key in ("trend_daily", "trend_weekly", "trend_monthly"):
            align = align + each(np.asarray(daily[key], dtype=float))
        columns["trend_align5"] = align

    names = tuple(f"{INTRADAY_PREFIX}{n}" for n in columns)
    values = np.stack([np.asarray(columns[n], dtype=float) for n in columns], axis=2)
    values = np.where(np.isfinite(values), values, np.nan).astype(np.float32)
    return NameBlock(dates=np.asarray(cube.dates, dtype="datetime64[D]"), names=names, values=values)


# +1 when the close is above the slow EMA and the fast EMA above the slow,
# -1 when both are reversed, 0 when mixed; NaN where an EMA is unknown.
def _state(close: np.ndarray, fast: np.ndarray, slow: np.ndarray) -> np.ndarray:
    known = np.isfinite(close) & np.isfinite(fast) & np.isfinite(slow)
    with np.errstate(invalid="ignore"):
        up = (close > slow) & (fast > slow)
        down = (close < slow) & (fast < slow)
    return np.where(known, np.where(up, 1.0, np.where(down, -1.0, 0.0)), np.nan)


# The 60-minute trend at every slot: EMA9 and EMA21 over the name's hourly
# closes (the closes of HOUR_END_SLOTS, across sessions), read at the last
# hour completed by the close of slot k, against the price C_k.
def _hourly_state(close: np.ndarray) -> np.ndarray:
    sessions = close.shape[0]
    hours = close[:, list(HOUR_END_SLOTS)].reshape(-1)
    fast = _ema_1d(hours, 9).reshape(sessions, len(HOUR_END_SLOTS))
    slow = _ema_1d(hours, 21).reshape(sessions, len(HOUR_END_SLOTS))
    warm = np.arange(sessions)[:, None] >= EMA_WARMUP_SESSIONS
    fast = np.where(warm, fast, np.nan)
    slow = np.where(warm, slow, np.nan)
    out = np.full(close.shape, np.nan)
    ends = np.array(HOUR_END_SLOTS)
    for k in range(FULL_SESSION_SLOTS):
        done = np.flatnonzero(ends <= k)
        if len(done):
            h = done[-1]
            f, s_ = fast[:, h], slow[:, h]
        else:
            # Before 10:30 the last completed hour is the previous session's last.
            f = np.concatenate([[np.nan], fast[:-1, -1]])
            s_ = np.concatenate([[np.nan], slow[:-1, -1]])
        out[:, k] = _state(close[:, k], f, s_)
    return out


# IS: at each slot, the nearest support below C_k and resistance above it
# among the levels in force during bar k (sr_levels' 22, on the adjusted
# basis), in ATR units, their zones' confluence, whether C_k is inside any
# zone, and the nearest support's family group.
def _support_resistance(
    cube: SessionCube,
    scale: np.ndarray,
    atr: np.ndarray,
    levels: tuple[np.ndarray, np.ndarray] | None,
) -> dict[str, np.ndarray]:
    sessions = len(cube)
    names = ("is_support_dist", "is_resistance_dist", "is_support_confluence", "is_resistance_confluence", "is_inside_zone")
    out = {n: np.full((sessions, TI_SLOTS), np.nan) for n in names}
    for group in IS_GROUPS:
        out[f"is_support_{group}"] = np.full((sessions, TI_SLOTS), np.nan)
    if levels is None:
        return out
    daily, width = levels
    session = sr_levels.session_levels(cube, scale, daily, width)
    conf = sr_levels.confluence(session)
    value = session.levels[:, :TI_SLOTS, :]  # (S, 24, 22)
    zone = conf[:, :TI_SLOTS, :].astype(float)
    price = (cube.close * scale[:, None])[:, :TI_SLOTS, None]
    atr_price = (atr * scale * cube.prior_close)[:, None]  # ATR fraction x the prior close, adjusted
    with np.errstate(invalid="ignore"):
        below = np.where(value < price, value, -np.inf)
        above = np.where(value > price, value, np.inf)
    s_kind = below.argmax(axis=2)
    r_kind = above.argmin(axis=2)
    support = np.take_along_axis(below, s_kind[:, :, None], axis=2)[:, :, 0]
    resistance = np.take_along_axis(above, r_kind[:, :, None], axis=2)[:, :, 0]
    has_s = np.isfinite(support)
    has_r = np.isfinite(resistance)
    p = price[:, :, 0]
    with np.errstate(all="ignore"):
        out["is_support_dist"] = np.where(has_s, (p - support) / atr_price, np.nan)
        out["is_resistance_dist"] = np.where(has_r, (resistance - p) / atr_price, np.nan)
    out["is_support_confluence"] = np.where(has_s, np.take_along_axis(zone, s_kind[:, :, None], axis=2)[:, :, 0], np.nan)
    out["is_resistance_confluence"] = np.where(has_r, np.take_along_axis(zone, r_kind[:, :, None], axis=2)[:, :, 0], np.nan)
    w = session.width[:, None, None]
    with np.errstate(invalid="ignore"):
        inside = (np.abs(value - price) <= w).any(axis=2)
    out["is_inside_zone"] = np.where(np.isfinite(session.width)[:, None], inside.astype(float), np.nan)
    family = np.array([sr_levels.FAMILY_OF[k] for k in sr_levels.KINDS])
    for group, members in IS_GROUPS.items():
        in_group = np.isin(family, members)
        out[f"is_support_{group}"] = np.where(has_s, in_group[s_kind].astype(float), np.nan)
    return out


# A cube's per-slot scales from its own prior sessions: sigma_slot (S, 26)
# and the gap's sigma (S,).
def slot_scales(cube: SessionCube) -> tuple[np.ndarray, np.ndarray]:
    """Return (sigma_slot, sigma_gap) from the prior SCALE_SESSIONS sessions."""
    r = bar_returns(cube)
    gap = _log(cube.open[:, 0] / cube.prior_close)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        sigma_slot = np.column_stack(
            [prior_sessions(r[:, j], SCALE_SESSIONS, "rms") for j in range(FULL_SESSION_SLOTS)]
        )
        sigma_gap = prior_sessions(gap, SCALE_SESSIONS, "std")
    return sigma_slot, sigma_gap


# The sequence model's 12 channels (stage3_io.SEQ_CHANNELS, in order) for
# every cube session of one name: (S, 27, 12), step 0 the overnight gap and
# steps 1..26 the bars. `daily` is `name_block`'s per-session mapping (ATR,
# prior-day levels, the adjusted close at t, the side beta). The volume
# channels (VWAP distance, RVOL) at bar k read bars < k, as in the tabular
# block; everything else at bar k reads prices up to C_k.
def sequence_channels(
    cube: SessionCube,
    daily: Mapping[str, np.ndarray],
    spy: SessionCube | None,
    side: SessionCube | None,
) -> np.ndarray:
    """Return (S, 27, 12) float32 sequence channels, NaN where undefined."""
    sessions = len(cube)
    out = np.full((sessions, FULL_SESSION_SLOTS + 1, 12), np.nan)
    open0 = cube.open[:, 0]
    close = cube.close
    prior = cube.prior_close
    r = bar_returns(cube)
    since = _log(close / open0[:, None])
    gap = _log(open0 / prior)
    sigma_slot, sigma_gap = slot_scales(cube)
    atr = np.asarray(daily["atr"], dtype=float)
    scale = np.asarray(daily["adj_close_t"], dtype=float) / prior
    pdh = np.asarray(daily["pdh"], dtype=float) / scale
    pdl = np.asarray(daily["pdl"], dtype=float) / scale
    beta = np.asarray(daily["beta_side"], dtype=float)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        sigma_open = np.column_stack(
            [prior_sessions(since[:, j], SCALE_SESSIONS, "std") for j in range(FULL_SESSION_SLOTS)]
        )
        per_session_sq = np.nansum(r * r, axis=1)
        per_session_sum = np.nansum(r, axis=1)
        n_bars = FULL_SESSION_SLOTS * SCALE_SESSIONS
        mean15 = lag(rolling_mean(per_session_sum, SCALE_SESSIONS), 1) / FULL_SESSION_SLOTS
        meansq15 = lag(rolling_mean(per_session_sq, SCALE_SESSIONS), 1) / FULL_SESSION_SLOTS
        sigma15 = np.sqrt(np.maximum(meansq15 - mean15 * mean15, 0.0) * n_bars / (n_bars - 1))
        vwap_prev = through_previous(vwap_through(cube))
        volume = np.asarray(cube.volume, dtype=float)
        cumulative = np.cumsum(np.nan_to_num(volume), axis=1)
        typical_cum = np.column_stack(
            [prior_sessions(cumulative[:, j], RVOL_SESSIONS, "mean") for j in range(FULL_SESSION_SLOTS)]
        )
        rvol_prev = through_previous(_log(cumulative / typical_cum))
        flat = close.reshape(-1)
        ema21 = _ema_1d(flat, 21).reshape(close.shape)
        ema21 = np.where(np.arange(sessions)[:, None] >= EMA_WARMUP_SESSIONS, ema21, np.nan)
        or_hi = np.max(cube.high[:, :2], axis=1)[:, None]
        or_lo = np.min(cube.low[:, :2], axis=1)[:, None]
        or_position = np.clip((close - or_lo) / (or_hi - or_lo), -2.0, 3.0)
        or_position[:, :2] = np.nan
        bars = slice(1, None)
        out[:, bars, 0] = r / sigma_slot
        out[:, 0, 0] = gap / sigma_gap
        out[:, bars, 1] = since / sigma_open
        out[:, 0, 1] = 0.0
        out[:, bars, 2] = _log(close / vwap_prev) / sigma_open
        out[:, 1, 2] = 0.0
        out[:, 0, 2] = 0.0
        for channel, level in ((3, prior), (4, pdh), (5, pdl)):
            out[:, bars, channel] = _log(close / level[:, None]) / atr[:, None]
            out[:, 0, channel] = _log(open0 / level) / atr
        out[:, bars, 6] = _log(close / ema21) / sigma15[:, None]
        out[:, 0, 6] = 0.0
        out[:, bars, 7] = np.where(np.arange(FULL_SESSION_SLOTS)[None, :] >= 1, rvol_prev, 0.0)
        out[:, 0, 7] = 0.0
        dates = np.asarray(cube.dates, dtype="datetime64[D]")
        for channel, bench, relative in ((8, side, True), (9, spy, False)):
            pos, ok = _align(bench, dates)
            if bench is None or not ok.any():
                continue
            b_r = _bench(bar_returns(bench), pos, ok)
            b_gap = _bench(_log(bench.open[:, 0] / bench.prior_close), pos, ok)
            b_sigma_slot, b_sigma_gap = slot_scales(bench)
            b_sigma_slot = _bench(b_sigma_slot, pos, ok)
            b_sigma_gap = _bench(b_sigma_gap, pos, ok)
            if relative:
                out[:, bars, channel] = (r - beta[:, None] * b_r) / sigma_slot
                out[:, 0, channel] = (gap - beta * b_gap) / sigma_gap
            else:
                out[:, bars, channel] = b_r / b_sigma_slot
                out[:, 0, channel] = b_gap / b_sigma_gap
        out[:, bars, 10] = np.where(np.isfinite(or_position), or_position, 0.0)
        out[:, 0, 10] = 0.0
        out[:, :, 11] = 0.0
        out[:, 0, 11] = 1.0
    return np.where(np.isfinite(out), out, np.nan).astype(np.float32)


__all__ = ["Breadth", "NameBlock", "breadth", "name_block", "sequence_channels", "slot_scales"]
