"""Stage 3's daily block: every daily input of the plan, known at session t's close.

`docs/research/stage3-plan-2026-09-29.md` ("Inputs, and the moment each is
known") lists the columns; the IDs in the comments below are the plan's.
Every column is computed from the desk's adjusted daily panel (highs, lows
and opens scaled by `adj_close / close`, as `levels.py` does), from the SIP
cubes' completed sessions, and from the stored EDGAR, tone and macro layers,
and every value in row t uses nothing dated after t: a test tampers with
every input after t and asserts the rows up to t are unchanged.

The block is a (T, N, F) float32 array over the panel's dates and tickers
plus the column names (each starts with `stage3_io.DAILY_PREFIX`) and a
per-column flag saying whether the column is a *date-level* input (the
same for every name on a date: regime, VIX, calendar, breadth). The T-S1
export rank-Gausses every name-level column per date and leaves the
date-level ones raw; the T-I export uses the columns as they are.

Units. sigma20 is the 20-session standard deviation of daily log returns;
ATR14 is Wilder's average true range over 14 sessions as a fraction of the
close. Windows are strict: a value needs its whole window of finite inputs,
else it is NaN, so an early or newly listed name is missing rather than
estimated from a short window.

Two conventions stated rather than hidden. The daily support/resistance
block (DS) reads `sr_levels.daily_levels`, whose row d holds the levels in
force during session d from rows <= d-1; the value known at t's close is
therefore its row t+1, and the panel's last row (whose next session is not
on file) is NaN there. The side ETF (SMH or IGV) and QQQ enter as daily log
returns from their SIP cubes, official close over prior close, which are
split-safe by the cube's construction; the ~21 early-close sessions the
cubes exclude count as a zero return, a small, stated approximation.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.market import levels as levels_module
from backend.market import sr_levels, technical
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.market.stage3_io import DAILY_PREFIX

# Sessions of the trailing windows the plan names.
SIGMA_WINDOW = 20
ATR_WINDOW = 14
KELTNER_ATR = 10
BAND_WINDOW = 20
BANDWIDTH_RANK = 126
YEAR = 252
PROFILE_SESSIONS = 20
PROFILE_BIN = math.log(1.0025)
VALUE_AREA = 0.70
CGO_WEEKS = 260
EMA_SPANS = (9, 21, 50, 200)
SMA_LENGTHS = (3, 5, 10, 20, 50, 100, 200, 400)
DONCHIAN = (20, 55, 252)
BREAKOUT = (20, 55)
RETURN_HORIZONS = (1, 5, 10, 20, 60)
THEME_HORIZONS = (20, 60, 120)
# The Baz MACD columns already in `technical`, reused by name.
BAZ_MACD = ("macd_8_24", "macd_16_48", "macd_32_96", "macd_composite")
CANDLES = ("hammer", "shooting_star", "bullish_engulfing", "bearish_engulfing", "reversal_net_3")
# The desk's grade ordinals: A+ 3, A 2, B 1, C 0.
GRADE_ORDINALS = (3, 2, 1, 0)
GRADE_LABELS = ("ap", "a", "b", "c")
REGIME_NAMES = (
    "regime_exposure",
    "regime_confidence",
    "regime_participation_pct",
    "regime_ai_drawdown",
    "regime_leader_ai",
    "regime_tightening",
)
# The support/resistance family groups a nearest level is reported in.
DS_GROUPS = {
    "swing": ("swing_20", "swing_60", "swing_250"),
    "average": ("sma_50", "sma_200", "wsma_21"),
    "range": ("range_52w", "prior_week"),
    "prior": ("prior_day",),
}


@dataclass(frozen=True)
class DailyBlock:
    """Every daily input per (panel session, panel name), known at the close."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    names: tuple[str, ...]  # F column names, each with DAILY_PREFIX
    values: np.ndarray  # (T, N, F) float32
    date_level: np.ndarray  # (F,) bool: the same for every name on a date

    # The position of a column by name.
    def column(self, name: str) -> int:
        """Return the index of column `name`."""
        return self.names.index(name)


# ---------------------------------------------------------------------------
# Rolling helpers over the time axis (axis 0), NaN-strict.
# ---------------------------------------------------------------------------


# A natural log that is NaN wherever the ratio is not a positive finite number.
def _log(x: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        out = np.log(np.asarray(x, dtype=float))
    return np.where(np.isfinite(out), out, np.nan)


# `x` shifted down `k` rows along time, NaN in the rows that have no past.
def lag(x: np.ndarray, k: int) -> np.ndarray:
    """Return x[t - k] at row t (NaN for t < k)."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if k == 0:
        return x.copy()
    if k < len(x):
        out[k:] = x[:-k]
    return out


# Rolling sums over `n` rows with the count of finite entries, from
# cumulative sums, so a window is O(1) whatever its length.
def _window_sums(x: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    finite = np.isfinite(x)
    filled = np.where(finite, x, 0.0)
    zeros = np.zeros((1,) + x.shape[1:])
    csum = np.concatenate([zeros, np.cumsum(filled, axis=0)])
    ccount = np.concatenate([zeros, np.cumsum(finite, axis=0)])
    total = np.full(x.shape, np.nan)
    count = np.zeros(x.shape)
    if n <= len(x):
        total[n - 1 :] = csum[n:] - csum[:-n]
        count[n - 1 :] = ccount[n:] - ccount[:-n]
    return total, count


# The rolling mean over `n` rows, NaN unless all `n` entries are finite.
def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Return the strict rolling mean of `x` over `n` rows."""
    total, count = _window_sums(x, n)
    return np.where(count == n, total / n, np.nan)


# The rolling standard deviation (ddof = 1 unless `ddof` says otherwise),
# NaN unless all `n` entries are finite.
def rolling_std(x: np.ndarray, n: int, ddof: int = 1) -> np.ndarray:
    """Return the strict rolling standard deviation of `x` over `n` rows."""
    x = np.asarray(x, dtype=float)
    total, count = _window_sums(x, n)
    squares, _ = _window_sums(x * x, n)
    with np.errstate(all="ignore"):
        variance = (squares - total * total / n) / (n - ddof)
    return np.where(count == n, np.sqrt(np.maximum(variance, 0.0)), np.nan)


# The rolling max or min over `n` rows, NaN unless all entries are finite.
def rolling_extreme(x: np.ndarray, n: int, largest: bool) -> np.ndarray:
    """Return the strict rolling max (or min) of `x` over `n` rows."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if n > len(x):
        return out
    windows = np.lib.stride_tricks.sliding_window_view(x, n, axis=0)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        extreme = windows.max(axis=-1) if largest else windows.min(axis=-1)
    complete = np.isfinite(windows).all(axis=-1)
    out[n - 1 :] = np.where(complete, extreme, np.nan)
    return out


# Rows since the rolling max (or min) of the last `n` rows was set: 0 when
# row t itself is the extreme; NaN unless the window is complete.
def rows_since_extreme(x: np.ndarray, n: int, largest: bool) -> np.ndarray:
    """Return the age in rows of the window's extreme."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if n > len(x):
        return out
    windows = np.lib.stride_tricks.sliding_window_view(x, n, axis=0)
    filled = np.where(np.isfinite(windows), windows, -np.inf if largest else np.inf)
    # The latest position of the extreme: argmax on the reversed window.
    reversed_windows = filled[..., ::-1]
    position = reversed_windows.argmax(axis=-1) if largest else reversed_windows.argmin(axis=-1)
    complete = np.isfinite(windows).all(axis=-1)
    out[n - 1 :] = np.where(complete, position.astype(float), np.nan)
    return out


# Wilder's smoothing (alpha = 1/n) along time, seeded with the mean of the
# first n finite values of each column; a NaN input breaks the chain and
# restarts it.
def wilder(x: np.ndarray, n: int) -> np.ndarray:
    """Return Wilder's running average of `x` with period `n`."""
    x = np.asarray(x, dtype=float)
    squeeze = x.ndim == 1
    values = x[:, None] if squeeze else x
    out = np.full(values.shape, np.nan)
    state = np.full(values.shape[1], np.nan)
    run = np.zeros(values.shape[1], dtype=int)
    seed = np.zeros(values.shape[1])
    for t in range(len(values)):
        v = values[t]
        ok = np.isfinite(v)
        run = np.where(ok, run + 1, 0)
        seed = np.where(ok, np.where(run == 1, v, seed + v), 0.0)
        ready = ok & (run == n)
        state = np.where(ready, seed / n, state)
        going = ok & (run > n)
        state = np.where(going, state + (v - state) / n, state)
        state = np.where(ok, state, np.nan)
        out[t] = np.where(run >= n, state, np.nan)
    return out[:, 0] if squeeze else out


# The adjusted OHLC of the panel: opens, highs and lows on the adjusted
# close's basis.
def adjusted_ohlc(panel) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (open, high, low, close) on the panel's adjusted basis."""
    with np.errstate(all="ignore"):
        factor = np.where(panel.close > 0, panel.adj_close / panel.close, np.nan)
    close = np.asarray(panel.adj_close, dtype=float)
    return panel.open * factor, panel.high * factor, panel.low * factor, close


# Wilder's average true range in price units.
def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    """Return (T, N) Wilder ATR over `n` sessions, in price."""
    prev = lag(close, 1)
    with np.errstate(invalid="ignore"):
        true_range = np.fmax(high - low, np.fmax(np.abs(high - prev), np.abs(low - prev)))
    true_range = np.where(np.isfinite(high) & np.isfinite(low) & np.isfinite(prev), true_range, np.nan)
    return wilder(true_range, n)


# Wilder RSI over `n` sessions, 0..100.
def rsi(close: np.ndarray, n: int) -> np.ndarray:
    """Return (T, N) Wilder RSI."""
    change = np.asarray(close, dtype=float) - lag(close, 1)
    gain = wilder(np.where(np.isfinite(change), np.fmax(change, 0.0), np.nan), n)
    loss = wilder(np.where(np.isfinite(change), np.fmax(-change, 0.0), np.nan), n)
    with np.errstate(all="ignore"):
        value = 100.0 - 100.0 / (1.0 + gain / loss)
    value = np.where(loss == 0, np.where(gain > 0, 100.0, 50.0), value)
    return np.where(np.isfinite(gain) & np.isfinite(loss), value, np.nan)


# Wilder's ADX with the directional indicators, 0..100.
def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (ADX, +DI, -DI) over `n` sessions."""
    up = high - lag(high, 1)
    down = lag(low, 1) - low
    with np.errstate(invalid="ignore"):
        plus_dm = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    known = np.isfinite(up) & np.isfinite(down)
    plus_dm = np.where(known, plus_dm, np.nan)
    minus_dm = np.where(known, minus_dm, np.nan)
    range_ = atr(high, low, close, n)
    with np.errstate(all="ignore"):
        plus_di = 100.0 * wilder(plus_dm, n) / range_
        minus_di = 100.0 * wilder(minus_dm, n) / range_
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    dx = np.where(np.isfinite(dx), dx, np.nan)
    return wilder(dx, n), plus_di, minus_di


# Columns derived from completed calendar periods (weeks or months): the
# period-end rows, a per-period series, and the value of the last period
# completed at or before each row. A period ends on the last session on
# file of the week (Friday, or the session before a Friday holiday) or of
# the month; the exchange calendar is known in advance, so a period ending
# at t's close counts at t.
def period_ends(dates: np.ndarray, kind: str) -> np.ndarray:
    """Return (T,) bool: row t is the last session of its week or month."""
    days = np.asarray(dates, dtype="datetime64[D]")
    if kind == "week":
        key = (days.astype(np.int64) + 3) // 7
        friday = (days.astype(np.int64) + 3) % 7 == 4
    elif kind == "month":
        key = days.astype("datetime64[M]").astype(np.int64)
        friday = np.zeros(len(days), dtype=bool)
    else:
        raise ValueError(f"kind must be week or month, not {kind!r}")
    nxt = np.concatenate([key[1:] != key[:-1], [False]])
    ends = nxt | friday
    if kind == "month" and len(days):
        # The newest row closes its month only if it is the month's last
        # business day; the calendar says so without a future row.
        next_month = (days[-1].astype("datetime64[M]") + np.timedelta64(1, "M")).astype("datetime64[D]")
        last = np.busday_offset(next_month, -1, roll="backward")
        ends[-1] = ends[-1] or bool(days[-1] >= last)
    elif kind == "week" and len(days):
        ends[-1] = ends[-1] or bool(friday[-1])
    return ends


# Carry per-period values (one row per completed period, in order) forward
# onto the daily rows: row t gets the latest period ending at or before t.
def carry(ends: np.ndarray, per_period: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    """Return the daily array of the last completed period's value."""
    out = np.full(shape, np.nan)
    rows = np.flatnonzero(ends)
    for i, t in enumerate(rows):
        stop = rows[i + 1] if i + 1 < len(rows) else shape[0]
        out[t:stop] = per_period[i]
    return out


# ---------------------------------------------------------------------------
# The families.
# ---------------------------------------------------------------------------


# D01-D15, D19 and the multi-timeframe trend block T: location and trend
# from the adjusted daily bars.
def location_trend(panel) -> dict[str, np.ndarray]:
    """Return the D and T columns keyed by name (without prefix)."""
    open_, high, low, close = adjusted_ohlc(panel)
    volume = np.asarray(panel.volume, dtype=float)
    logret = _log(close / lag(close, 1))
    sigma = rolling_std(logret, SIGMA_WINDOW)
    out: dict[str, np.ndarray] = {}
    with np.errstate(all="ignore"):
        emas = {n: technical.ema(close, n) for n in EMA_SPANS}
        for n in EMA_SPANS:
            out[f"ema{n}_dist"] = _log(close / emas[n]) / sigma  # D01
        smas = {n: technical.sma(close, n) for n in SMA_LENGTHS}
        out["mad"] = technical.sma(close, 21) / smas[200] - 1.0  # D02
        for n in SMA_LENGTHS:
            out[f"sma{n}_dist"] = _log(close / smas[n]) / sigma  # D03
        for n in EMA_SPANS:
            out[f"ema{n}_slope5"] = _log(emas[n] / lag(emas[n], 5))  # D04
        tech = technical.technical_features(panel)
        names = technical.TECHNICAL_NAMES
        out["stack"] = tech[:, :, names.index("stack_order")].astype(float)
        out["cross_9_21"] = tech[:, :, names.index("cross_9_21")].astype(float)
        out["cross_50_200"] = tech[:, :, names.index("cross_50_200")].astype(float)
        # D05 Bollinger(20, 2) on closes.
        mid = smas[20]
        price_sd = rolling_std(close, BAND_WINDOW, ddof=0)
        out["bb_z"] = (close - mid) / price_sd
        width = 4.0 * price_sd / mid
        out["bb_width"] = width
        out["bb_width_pct126"] = _trailing_percentile(width, BANDWIDTH_RANK)
        # D06 Keltner.
        atr10 = atr(high, low, close, KELTNER_ATR)
        ema20 = technical.ema(close, 20)
        out["keltner"] = (close - ema20) / atr10
        squeeze = ((mid + 2 * price_sd) < (ema20 + 1.5 * atr10)) & (
            (mid - 2 * price_sd) > (ema20 - 1.5 * atr10)
        )
        out["squeeze"] = np.where(np.isfinite(price_sd) & np.isfinite(atr10), squeeze.astype(float), np.nan)
        # D07 volatility from ranges.
        atr14 = atr(high, low, close, ATR_WINDOW)
        out["atr14"] = atr14 / close
        hl = _log(high / low)
        co = _log(close / open_)
        out["parkinson20"] = np.sqrt(rolling_mean(hl * hl / (4.0 * math.log(2.0)), SIGMA_WINDOW))
        gk = 0.5 * hl * hl - (2.0 * math.log(2.0) - 1.0) * co * co
        out["garman_klass20"] = np.sqrt(np.maximum(rolling_mean(gk, SIGMA_WINDOW), 0.0))
        rs = _log(high / close) * _log(high / open_) + _log(low / close) * _log(low / open_)
        out["rogers_satchell20"] = np.sqrt(np.maximum(rolling_mean(rs, SIGMA_WINDOW), 0.0))
        # D08 Donchian.
        for n in DONCHIAN:
            top = rolling_extreme(high, n, True)
            bottom = rolling_extreme(low, n, False)
            out[f"donchian{n}"] = (close - bottom) / (top - bottom)
        for n in BREAKOUT:
            prior_top = lag(rolling_extreme(high, n, True), 1)
            out[f"breakout{n}"] = np.where(np.isfinite(prior_top), (close > prior_top).astype(float), np.nan)
        # D09 52-week high and low.
        high52 = rolling_extreme(high, YEAR, True)
        low52 = rolling_extreme(low, YEAR, False)
        out["high52_dist"] = _log(close / high52)
        out["low52_dist"] = _log(close / low52)
        out["new_high52_5"] = tech[:, :, names.index("new_52w_high")].astype(float)
        out["since_high52"] = np.log1p(rows_since_extreme(high, YEAR, True))
        # D10 oscillators.
        out["rsi14"] = rsi(close, 14)
        out["rsi2"] = rsi(close, 2)
        high14 = rolling_extreme(high, 14, True)
        low14 = rolling_extreme(low, 14, False)
        stoch = 100.0 * (close - low14) / (high14 - low14)
        out["stoch_k14"] = stoch
        out["stoch_d3"] = rolling_mean(stoch, 3)
        # D11 MACD: the Baz set, and the classic 12/26/9 in sigma units.
        for name in BAZ_MACD:
            out[name] = tech[:, :, names.index(name)].astype(float)
        macd = (technical.ema(close, 12) - technical.ema(close, 26)) / close / sigma
        signal = technical.ema(macd, 9)
        out["macd"] = macd
        out["macd_signal"] = signal
        out["macd_hist"] = macd - signal
        # D12 ADX.
        adx14, plus_di, minus_di = adx(high, low, close, 14)
        out["adx14"] = adx14
        out["pdi14"] = plus_di
        out["mdi14"] = minus_di
        # D13 the desk's own level features.
        level_values = levels_module.level_features(panel)
        for i, name in enumerate(levels_module.LEVEL_NAMES):
            out[f"lvl_{name}"] = level_values[:, :, i].astype(float)
        # D14 weekly and monthly timeframes.
        weekly = _period_trend(panel.dates, close, "week", fast=9, slow=21, slope=4, ema=True)
        out["w_ema9_dist"] = _log(close / weekly["fast"]) / sigma
        out["w_ema21_dist"] = _log(close / weekly["slow"]) / sigma
        out["w_stack"] = weekly["stack"]
        out["w_ema21_slope4"] = weekly["slope"]
        monthly = _period_trend(panel.dates, close, "month", fast=None, slow=10, slope=3, ema=False)
        out["m_sma10_dist"] = _log(close / monthly["slow"]) / sigma
        out["m_sma10_slope3"] = monthly["slope"]
        # T: the trend state per timeframe and their alignment.
        daily_state = _state(close, emas[21], out["ema21_slope5"])
        weekly_state = _state(close, weekly["slow"], weekly["slope"])
        monthly_state = _state(close, monthly["slow"], monthly["slope"])
        out["trend_daily"] = daily_state
        out["trend_weekly"] = weekly_state
        out["trend_monthly"] = monthly_state
        out["trend_align"] = daily_state + weekly_state + monthly_state
        # D15 momentum, raw and residual.
        out["mom12_1"] = _log(lag(close, 21) / lag(close, 252))
        out["resid_mom12_1"] = _residual_momentum(logret, panel)
        # D19 candles, a negative control.
        for name in CANDLES:
            out[name] = tech[:, :, names.index(name)].astype(float)
    out["_sigma20"] = sigma
    out["_atr14"] = out["atr14"]
    out["_volume"] = volume
    return out


# The share of the trailing `n` rows (today included) whose value is at or
# below today's: a percentile rank in [1/n, 1]; NaN unless the window is full.
def _trailing_percentile(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if n > len(x):
        return out
    windows = np.lib.stride_tricks.sliding_window_view(x, n, axis=0)
    today = x[n - 1 :][..., None]
    with np.errstate(invalid="ignore"):
        share = (windows <= today).mean(axis=-1)
    complete = np.isfinite(windows).all(axis=-1)
    out[n - 1 :] = np.where(complete, share, np.nan)
    return out


# +1 when the close is above a rising trend average, -1 when below a falling
# one, 0 when mixed; NaN where either is unknown.
def _state(close: np.ndarray, average: np.ndarray, slope: np.ndarray) -> np.ndarray:
    known = np.isfinite(close) & np.isfinite(average) & np.isfinite(slope)
    with np.errstate(invalid="ignore"):
        up = (close > average) & (slope > 0)
        down = (close < average) & (slope < 0)
    return np.where(known, np.where(up, 1.0, np.where(down, -1.0, 0.0)), np.nan)


# A completed-period trend: the period closes (weekly or monthly), a fast
# and a slow average of them (EMA or SMA), the slow average's log slope over
# `slope` periods, the fast-over-slow stack, all carried onto daily rows
# from the last period completed at or before each row.
def _period_trend(
    dates: np.ndarray,
    close: np.ndarray,
    kind: str,
    fast: int | None,
    slow: int,
    slope: int,
    ema: bool,
) -> dict[str, np.ndarray]:
    ends = period_ends(dates, kind)
    closes = close[ends]
    average = technical.ema if ema else technical.sma
    slow_series = average(closes, slow)
    fast_series = average(closes, fast) if fast is not None else np.full(closes.shape, np.nan)
    slope_series = _log(slow_series / lag(slow_series, slope))
    with np.errstate(invalid="ignore"):
        stack = np.where(
            np.isfinite(fast_series) & np.isfinite(slow_series),
            np.where(fast_series > slow_series, 1.0, -1.0),
            np.nan,
        )
    shape = close.shape
    return {
        "fast": carry(ends, fast_series, shape),
        "slow": carry(ends, slow_series, shape),
        "slope": carry(ends, slope_series, shape),
        "stack": carry(ends, stack, shape),
    }


# 12-1 residual momentum: the name's daily log returns over t-251..t-21 less
# beta times SPY's, beta from that same window, the sum divided by the
# residuals' standard deviation. Strict: the whole window must be finite.
def _residual_momentum(logret: np.ndarray, panel) -> np.ndarray:
    spy = logret[:, panel.index(panel.benchmark)]
    window = 231  # t-251 .. t-21 inclusive
    out = np.full(logret.shape, np.nan)
    end_lag = 21
    for t in range(window + end_lag - 1, len(logret)):
        hi = t - end_lag + 1
        lo = hi - window
        y = logret[lo:hi]
        x = spy[lo:hi]
        if not np.isfinite(x).all():
            continue
        ok = np.isfinite(y).all(axis=0)
        if not ok.any():
            continue
        xc = x - x.mean()
        yc = y[:, ok] - y[:, ok].mean(axis=0)
        beta = (xc @ yc) / (xc @ xc)
        resid = yc - np.outer(xc, beta)
        sd = resid.std(axis=0, ddof=1)
        with np.errstate(all="ignore"):
            out[t, ok] = np.where(sd > 0, resid.sum(axis=0) / sd, np.nan)
    return out


# DS: the daily support/resistance block from `sr_levels.daily_levels`,
# re-indexed to "known at t's close" (its row t + 1).
def daily_levels_block(panel, close: np.ndarray, atr_fraction: np.ndarray) -> dict[str, np.ndarray]:
    """Return the DS columns keyed by name."""
    daily = sr_levels.daily_levels(panel)
    rows, names = close.shape
    levels = np.full(daily.levels.shape, np.nan)
    width = np.full(daily.width.shape, np.nan)
    levels[:-1] = daily.levels[1:]
    width[:-1] = daily.width[1:]
    kinds = sr_levels.DAILY_KINDS
    group_of = {k: g for g, fams in DS_GROUPS.items() for k in kinds if sr_levels.FAMILY_OF[k] in fams}
    price = close[:, :, None]
    with np.errstate(invalid="ignore"):
        below = np.where(levels < price, levels, -np.inf)
        above = np.where(levels > price, levels, np.inf)
    support_kind = below.argmax(axis=2)
    resistance_kind = above.argmin(axis=2)
    support = np.take_along_axis(below, support_kind[:, :, None], axis=2)[:, :, 0]
    resistance = np.take_along_axis(above, resistance_kind[:, :, None], axis=2)[:, :, 0]
    support = np.where(np.isfinite(support), support, np.nan)
    resistance = np.where(np.isfinite(resistance), resistance, np.nan)
    atr_price = atr_fraction * close
    out: dict[str, np.ndarray] = {}
    with np.errstate(all="ignore"):
        out["sr_support_dist"] = (close - support) / atr_price
        out["sr_resistance_dist"] = (resistance - close) / atr_price
        near = np.abs(levels - price) <= width[:, :, None]
        out["sr_inside_zone"] = np.where(
            np.isfinite(width), near.any(axis=2).astype(float), np.nan
        )

        # Distinct level prices within the half-width of a chosen level.
        def confluence_at(level: np.ndarray) -> np.ndarray:
            close_to = np.abs(levels - level[:, :, None]) <= width[:, :, None]
            return np.where(np.isfinite(level), close_to.sum(axis=2).astype(float), np.nan)

        out["sr_support_confluence"] = confluence_at(support)
        out["sr_resistance_confluence"] = confluence_at(resistance)
    for group in DS_GROUPS:
        members = np.array([group_of.get(k) == group for k in kinds])
        flag = members[support_kind]
        out[f"sr_support_{group}"] = np.where(np.isfinite(support), flag.astype(float), np.nan)
    return out


# M01-M08: returns, the theme and linked names, overnight/intraday split,
# MAX, abnormal volume, news-conditioned reversal, betas.
def returns_links(
    panel,
    sides: Mapping[str, str],
    side_returns: Mapping[str, np.ndarray],
    eligible: np.ndarray,
    earnings_day: np.ndarray,
) -> dict[str, np.ndarray]:
    """Return the M columns keyed by name."""
    open_, _high, _low, close = adjusted_ohlc(panel)
    volume = np.asarray(panel.volume, dtype=float)
    logret = _log(close / lag(close, 1))
    spy = logret[:, panel.index(panel.benchmark)]
    side = np.stack(
        [np.asarray(side_returns[sides.get(t, "ai")], dtype=float) for t in panel.tickers], axis=1
    )
    out: dict[str, np.ndarray] = {}
    cumulative = _cumulative(logret)
    spy_cum = _cumulative(spy[:, None])[:, 0]
    side_cum = _cumulative(np.nan_to_num(side, nan=0.0))
    for k in RETURN_HORIZONS:
        out[f"ret{k}"] = _log(close / lag(close, k))
    for k in (20, 60):
        spy_k = spy_cum - lag(spy_cum, k)
        side_k = side_cum - lag(side_cum, k)
        out[f"ret{k}_vs_spy"] = out[f"ret{k}"] - spy_k[:, None]
        out[f"ret{k}_vs_side"] = out[f"ret{k}"] - side_k
    # M02 theme baskets: leave-one-out equal weight of eligible names in the
    # name's primary theme.
    theme_daily = _theme_returns(panel, logret, eligible)
    theme_cum = _cumulative(np.nan_to_num(theme_daily, nan=0.0))
    theme_known = np.isfinite(theme_daily)
    for k in THEME_HORIZONS:
        total = theme_cum - lag(theme_cum, k)
        counted, _ = _window_sums(theme_known.astype(float), k)
        out[f"theme_ret{k}"] = np.where(counted == k, total, np.nan)
    for k in (20, 60):
        out[f"ret{k}_vs_theme"] = out[f"ret{k}"] - out[f"theme_ret{k}"]
    out["linked_mom21"] = _linked_momentum(panel, logret, eligible)  # M03
    # M04 overnight and intraday.
    gap = _log(open_ / lag(close, 1))
    intraday = _log(close / open_)
    for k in (20, 60):
        out[f"gap_sum{k}"], counted = _window_sums(gap, k)
        out[f"gap_sum{k}"] = np.where(counted == k, out[f"gap_sum{k}"], np.nan)
        total, counted = _window_sums(intraday, k)
        out[f"oc_sum{k}"] = np.where(counted == k, total, np.nan)
    with np.errstate(invalid="ignore"):
        tug = np.where(np.isfinite(gap) & np.isfinite(intraday), ((gap > 0) & (intraday < 0)).astype(float), np.nan)
    out["tug21"] = rolling_mean(tug, 21)
    out["max21"] = rolling_extreme(logret, 21, True)  # M05
    # M06 abnormal volume.
    with np.errstate(all="ignore"):
        out["abvol50"] = _log(volume / lag(rolling_mean(volume, 50), 1))
        out["abvol5"] = _log(rolling_mean(volume, 5) / lag(rolling_mean(volume, 50), 5))
    # M07 news-conditioned reversal (earnings releases are the news on file).
    news1 = earnings_day.astype(float)
    news5, _ = _window_sums(news1, 5)
    for k, news in ((1, news1), (5, news5)):
        ret = out[f"ret{k}"]
        had = np.where(np.isfinite(news), news > 0, False)
        out[f"rev{k}_no_news"] = np.where(np.isfinite(ret), np.where(had, 0.0, ret), np.nan)
        out[f"rev{k}_news"] = np.where(np.isfinite(ret), np.where(had, ret, 0.0), np.nan)
    # M08 betas and correlations over 60 sessions.
    for label, ref in (("spy", np.repeat(spy[:, None], logret.shape[1], axis=1)), ("side", side)):
        beta, corr = _rolling_beta_corr(logret, ref, 60)
        out[f"beta60_{label}"] = beta
        out[f"corr60_{label}"] = corr
    out["_gap"] = gap
    out["_logret"] = logret
    return out


# Running cumulative sum along time with NaN treated as a break: the sum
# includes NaN as 0 but the callers check window completeness separately.
def _cumulative(x: np.ndarray) -> np.ndarray:
    return np.cumsum(np.nan_to_num(np.asarray(x, dtype=float), nan=0.0), axis=0)


# Leave-one-out equal-weight daily log return of each name's primary theme
# among the names eligible that day; NaN when no other member traded.
def _theme_returns(panel, logret: np.ndarray, eligible: np.ndarray) -> np.ndarray:
    out = np.full(logret.shape, np.nan)
    live = eligible & np.isfinite(logret)
    values = np.where(live, logret, 0.0)
    themes: dict[str, list[int]] = {}
    for j, ticker in enumerate(panel.tickers):
        theme = panel.primary_theme(ticker)
        if theme is not None:
            themes.setdefault(theme, []).append(j)
    for members in themes.values():
        cols = np.array(members)
        total = values[:, cols].sum(axis=1)
        count = live[:, cols].sum(axis=1)
        for j in cols:
            others = count - live[:, j]
            own = values[:, j]
            with np.errstate(invalid="ignore", divide="ignore"):
                out[:, j] = np.where(others > 0, (total - own) / others, np.nan)
    return out


# M03: the 21-session return of the same-theme names, weighted by their
# positive 252-session return correlation with the name, among names
# eligible at t; NaN when no linked name has a positive weight.
def _linked_momentum(panel, logret: np.ndarray, eligible: np.ndarray) -> np.ndarray:
    rows, names = logret.shape
    out = np.full(logret.shape, np.nan)
    ret21, counted = _window_sums(logret, 21)
    ret21 = np.where(counted == 21, ret21, np.nan)
    themes: dict[str, list[int]] = {}
    for j, ticker in enumerate(panel.tickers):
        theme = panel.primary_theme(ticker)
        if theme is not None:
            themes.setdefault(theme, []).append(j)
    for members in themes.values():
        if len(members) < 2:
            continue
        cols = np.array(members)
        block = logret[:, cols]
        sub = len(cols)
        weights = np.zeros((rows, sub, sub))
        for a in range(sub):
            for b in range(a + 1, sub):
                corr = _rolling_corr_pair(block[:, a], block[:, b], YEAR)
                w = np.where(np.isfinite(corr), np.maximum(corr, 0.0), 0.0)
                weights[:, a, b] = w
                weights[:, b, a] = w
        live = eligible[:, cols] & np.isfinite(ret21[:, cols])
        weights = weights * live[:, None, :]
        values = np.where(live, ret21[:, cols], 0.0)
        total = np.einsum("tab,tb->ta", weights, values)
        mass = weights.sum(axis=2)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:, cols] = np.where(mass > 0, total / mass, np.nan)
    return out


# Rolling Pearson correlation of two series over `n` rows, strict windows.
def _rolling_corr_pair(x: np.ndarray, y: np.ndarray, n: int) -> np.ndarray:
    both = np.isfinite(x) & np.isfinite(y)
    xs = np.where(both, x, np.nan)
    ys = np.where(both, y, np.nan)
    sx, cx = _window_sums(xs, n)
    sy, _ = _window_sums(ys, n)
    sxx, _ = _window_sums(xs * xs, n)
    syy, _ = _window_sums(ys * ys, n)
    sxy, _ = _window_sums(xs * ys, n)
    with np.errstate(all="ignore"):
        cov = sxy - sx * sy / n
        var_x = sxx - sx * sx / n
        var_y = syy - sy * sy / n
        corr = cov / np.sqrt(var_x * var_y)
    return np.where((cx == n) & (var_x > 0) & (var_y > 0), corr, np.nan)


# Rolling beta and correlation of each column of `y` on the matching column
# of `x` over `n` rows, strict windows.
def _rolling_beta_corr(y: np.ndarray, x: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    both = np.isfinite(x) & np.isfinite(y)
    xs = np.where(both, x, np.nan)
    ys = np.where(both, y, np.nan)
    sx, cx = _window_sums(xs, n)
    sy, _ = _window_sums(ys, n)
    sxx, _ = _window_sums(xs * xs, n)
    syy, _ = _window_sums(ys * ys, n)
    sxy, _ = _window_sums(xs * ys, n)
    with np.errstate(all="ignore"):
        cov = sxy - sx * sy / n
        var_x = sxx - sx * sx / n
        var_y = syy - sy * sy / n
        beta = cov / var_x
        corr = cov / np.sqrt(var_x * var_y)
    ok = (cx == n) & (var_x > 0)
    return np.where(ok, beta, np.nan), np.where(ok & (var_y > 0), corr, np.nan)


# V01-V04 and D17-D18 from the SIP cubes: realized measures of each cube
# session with its overnight gap, the 20-session volume profile, round
# numbers. Sessions the cube lacks are NaN on the panel.
def cube_daily(panel, cubes: Mapping[str, SessionCube], atr_fraction: np.ndarray) -> dict[str, np.ndarray]:
    """Return the cube-derived daily columns keyed by name."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    names = (
        "log_rv", "log_rv_mean5", "log_rv_mean22", "rs_minus_share", "sj_mean5",
        "sj_mean20", "rskew5", "rv_std20", "poc_dist", "vah_dist", "val_dist",
        "inside_value", "round_fine", "round_coarse",
    )
    out = {name: np.full(shape, np.nan) for name in names}
    close = np.asarray(panel.adj_close, dtype=float)
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None or len(cube) == 0:
            continue
        pos = np.searchsorted(dates, cube.dates)
        ok = (pos < len(dates)) & (dates[np.minimum(pos, len(dates) - 1)] == cube.dates)
        rows = pos[ok]
        c = cube.close[ok]
        o = cube.open[ok, 0]
        prior = cube.prior_close[ok]
        with np.errstate(all="ignore"):
            bars = np.log(c / np.column_stack([o, c[:, :-1]]))
            gap = np.log(o / prior)
        returns = np.column_stack([gap, bars])  # (S, 27): gap then the 26 bars
        squares = returns * returns
        rv = squares.sum(axis=1)
        negative = np.where(returns < 0, squares, 0.0).sum(axis=1)
        positive = rv - negative
        with np.errstate(all="ignore"):
            log_rv = np.log(rv)
            share_minus = negative / rv
            jump = (positive - negative) / rv
        per_session = {
            "log_rv": log_rv,
            "log_rv_mean5": np.log(rolling_mean(rv, 5)),
            "log_rv_mean22": np.log(rolling_mean(rv, 22)),
            "rs_minus_share": share_minus,
            "sj_mean5": rolling_mean(jump, 5),
            "sj_mean20": rolling_mean(jump, 20),
            "rv_std20": rolling_std(log_rv, 20),
        }
        # V03 realized skewness over the last 5 sessions' returns.
        cubes3, _ = _window_sums(np.sum(returns**3, axis=1), 5)
        sq5, counted = _window_sums(rv, 5)
        n5 = 5 * returns.shape[1]
        with np.errstate(all="ignore"):
            per_session["rskew5"] = np.where(counted == 5, math.sqrt(n5) * cubes3 / sq5**1.5, np.nan)
        for name, values in per_session.items():
            out[name][rows, j] = values
        # D17 the volume profile of the 20 sessions ending at each session,
        # on the adjusted basis (each session scaled by its own official close).
        official = np.where(np.isfinite(cube.auction_open[ok]) & (cube.auction_open[ok] > 0), cube.auction_open[ok], c[:, -1])
        with np.errstate(all="ignore"):
            scale = close[rows, j] / official
        profile = _volume_profile(cube.high[ok] * scale[:, None], cube.low[ok] * scale[:, None], cube.volume[ok], PROFILE_SESSIONS)
        atr_price = atr_fraction[rows, j] * close[rows, j]
        with np.errstate(all="ignore"):
            out["poc_dist"][rows, j] = (close[rows, j] - profile[:, 0]) / atr_price
            out["vah_dist"][rows, j] = (close[rows, j] - profile[:, 1]) / atr_price
            out["val_dist"][rows, j] = (close[rows, j] - profile[:, 2]) / atr_price
            inside = (close[rows, j] <= profile[:, 1]) & (close[rows, j] >= profile[:, 2])
        out["inside_value"][rows, j] = np.where(np.isfinite(profile[:, 0]), inside.astype(float), np.nan)
        # D18 round numbers on the traded (raw) price.
        raw = official
        with np.errstate(all="ignore"):
            step = 10.0 ** (np.floor(np.log10(raw)) - 1.0)
            fine = np.abs(raw - np.round(raw / step) * step)
            coarse = np.abs(raw - np.round(raw / (5 * step)) * 5 * step)
            atr_raw = atr_fraction[rows, j] * raw
            out["round_fine"][rows, j] = fine / atr_raw
            out["round_coarse"][rows, j] = coarse / atr_raw
    return out


# The volume profile of each session's trailing `n` sessions (itself
# included): bar volume spread evenly over the 0.25% log-price bins its
# low-high range covers, the point of control (the fullest bin, ties to the
# lower price), and the 70% value area grown from it one bin at a time
# toward the fuller neighbour. Returns (S, 3): POC, VAH, VAL prices (bin
# midpoints), NaN until `n` sessions exist.
def _volume_profile(high: np.ndarray, low: np.ndarray, volume: np.ndarray, n: int) -> np.ndarray:
    sessions = high.shape[0]
    out = np.full((sessions, 3), np.nan)
    with np.errstate(all="ignore"):
        valid = np.isfinite(high) & np.isfinite(low) & (low > 0) & (high >= low) & np.isfinite(volume) & (volume > 0)
        lo_bin = np.floor(np.log(np.where(valid, low, 1.0)) / PROFILE_BIN).astype(np.int64)
        hi_bin = np.floor(np.log(np.where(valid, high, 1.0)) / PROFILE_BIN).astype(np.int64)
    span = np.where(valid, hi_bin - lo_bin + 1, 0)
    share = np.where(valid, volume / np.maximum(span, 1), 0.0)
    flat_span = span.ravel()
    total = int(flat_span.sum())
    if total == 0:
        return out
    first = np.repeat(np.cumsum(flat_span) - flat_span, flat_span)
    bins = np.repeat(lo_bin.ravel(), flat_span) + (np.arange(total) - first)
    weights = np.repeat(share.ravel(), flat_span)
    offsets = np.concatenate([[0], np.cumsum(span.sum(axis=1))])
    for s in range(n - 1, sessions):
        lo, hi = offsets[s - n + 1], offsets[s + 1]
        if hi <= lo:
            continue
        window = bins[lo:hi]
        base = int(window.min())
        profile = np.bincount(window - base, weights=weights[lo:hi])
        grand = profile.sum()
        if grand <= 0:
            continue
        poc = int(profile.argmax())
        top = bottom = poc
        held = profile[poc]
        while held < VALUE_AREA * grand and (top + 1 < len(profile) or bottom > 0):
            up = profile[top + 1] if top + 1 < len(profile) else -1.0
            down = profile[bottom - 1] if bottom > 0 else -1.0
            if up >= down:
                top += 1
                held += up
            else:
                bottom -= 1
                held += down
        mid = lambda b: math.exp((base + b + 0.5) * PROFILE_BIN)  # noqa: E731
        out[s] = (mid(poc), mid(top), mid(bottom))
    return out


# X and D20: the EDGAR and tone layers as the desk loads them, plus the
# retail-attention product and the anchored VWAPs.
def events_block(
    panel,
    edgar_values: np.ndarray | None,
    edgar_names: Sequence[str],
    tone_values: np.ndarray | None,
    tone_names: Sequence[str],
    earnings_day: np.ndarray,
    abvol50: np.ndarray,
    gap: np.ndarray,
    atr_fraction: np.ndarray,
) -> dict[str, np.ndarray]:
    """Return the X and D20 columns keyed by name."""
    shape = (len(panel.dates), len(panel.tickers))
    out: dict[str, np.ndarray] = {}
    for values, names, prefix in ((edgar_values, edgar_names, "edgar_"), (tone_values, tone_names, "")):
        for i, name in enumerate(names):
            out[f"{prefix}{name}"] = (
                np.asarray(values[:, :, i], dtype=float) if values is not None else np.full(shape, np.nan)
            )
    with np.errstate(invalid="ignore"):
        out["attention"] = np.where(earnings_day, 0.0, abvol50 * np.abs(gap))
    out["attention"] = np.where(np.isfinite(abvol50) & np.isfinite(gap), out["attention"], np.nan)
    # D20 anchored VWAPs: from the last earnings reaction session, and from
    # the 252-session high and low dates.
    open_, high, low, close = adjusted_ohlc(panel)
    volume = np.asarray(panel.volume, dtype=float)
    typical = (high + low + close) / 3.0
    live = np.isfinite(typical) & np.isfinite(volume)
    tpv = np.cumsum(np.where(live, typical * volume, 0.0), axis=0)
    vol = np.cumsum(np.where(live, volume, 0.0), axis=0)
    rows = np.arange(shape[0])[:, None]

    # The AVWAP from anchor row `a` (inclusive) to row t, NaN where a < 0.
    def anchored(anchor: np.ndarray) -> np.ndarray:
        safe = np.maximum(anchor, 0).astype(np.int64)
        cols = np.arange(shape[1])[None, :]
        before_tpv = np.where(safe > 0, tpv[np.maximum(safe - 1, 0), cols], 0.0)
        before_vol = np.where(safe > 0, vol[np.maximum(safe - 1, 0), cols], 0.0)
        with np.errstate(all="ignore"):
            value = (tpv - before_tpv) / (vol - before_vol)
        return np.where(anchor >= 0, value, np.nan)

    last_earnings = np.where(earnings_day, rows, -1)
    last_earnings = np.maximum.accumulate(last_earnings, axis=0)
    high_age = rows_since_extreme(high, YEAR, True)
    low_age = rows_since_extreme(low, YEAR, False)
    high_anchor = np.where(np.isfinite(high_age), rows - np.nan_to_num(high_age), -1)
    low_anchor = np.where(np.isfinite(low_age), rows - np.nan_to_num(low_age), -1)
    for name, anchor in (("avwap_earnings", last_earnings), ("avwap_high252", high_anchor), ("avwap_low252", low_anchor)):
        out[name] = _log(close / anchored(anchor)) / atr_fraction
    return out


# D16: capital-gains overhang (George-Hwang 2005) from weekly closes and
# weekly turnover = weekly volume / shares outstanding known at the week's
# end; the reference price weights each past week's close by its turnover
# times the share of it not turned over since, truncated at CGO_WEEKS weeks
# (or the panel's start) and renormalized; CGO_w = (P_{w-2} - RP_{w-1}) /
# P_{w-2}, carried onto daily rows. NaN without a share count.
def capital_gains_overhang(panel, shares: np.ndarray) -> np.ndarray:
    """Return (T, N) CGO; `shares` is (T, N) shares outstanding known at each row."""
    close = np.asarray(panel.adj_close, dtype=float)
    volume = np.asarray(panel.volume, dtype=float)
    ends = period_ends(panel.dates, "week")
    week_rows = np.flatnonzero(ends)
    starts = np.concatenate([[0], week_rows[:-1] + 1])
    weekly_volume = np.stack([np.nansum(volume[a : b + 1], axis=0) for a, b in zip(starts, week_rows, strict=True)]) if len(week_rows) else np.zeros((0, close.shape[1]))
    weekly_close = close[week_rows]
    with np.errstate(all="ignore"):
        turnover = np.clip(weekly_volume / shares[week_rows], 0.0, 1.0)
    weeks, names = weekly_close.shape
    reference = np.full((weeks, names), np.nan)
    for w in range(weeks):
        lo = max(0, w - CGO_WEEKS + 1)
        v = turnover[lo : w + 1][::-1]  # v[0] is week w, v[n] is week w - n
        p = weekly_close[lo : w + 1][::-1]
        ok = np.isfinite(v).all(axis=0) & np.isfinite(p).all(axis=0)
        if not ok.any():
            continue
        survive = np.cumprod(np.vstack([np.ones((1, names)), 1.0 - v[:-1]]), axis=0)
        weight = v * survive
        mass = weight.sum(axis=0)
        with np.errstate(all="ignore"):
            reference[w] = np.where(ok & (mass > 0), (weight * p).sum(axis=0) / mass, np.nan)
    cgo = np.full((weeks, names), np.nan)
    with np.errstate(all="ignore"):
        # reference[w] weights weeks w, w-1, ...; the plan's RP_{w-1} weights
        # weeks w-2 back, which is reference[w - 2].
        cgo[2:] = (weekly_close[:-2] - reference[:-2]) / weekly_close[:-2]
    return carry(ends, cgo, close.shape)


# G: the desk's state - grade one-hot, stances, bullish count, grade age and
# flips, the regime scalars, and the day's breadth among eligible names.
def desk_block(
    grades: np.ndarray,
    stances: Mapping[str, np.ndarray],
    regime: np.ndarray,
    adj_close: np.ndarray,
    eligible: np.ndarray,
) -> dict[str, np.ndarray]:
    """Return the G columns keyed by name."""
    grades = np.asarray(grades, dtype=float)
    graded = grades >= 0
    out: dict[str, np.ndarray] = {}
    for ordinal, label in zip(GRADE_ORDINALS, GRADE_LABELS, strict=True):
        out[f"grade_{label}"] = np.where(graded, (grades == ordinal).astype(float), np.nan)
    bullish = np.zeros(grades.shape)
    for name, values in sorted(stances.items()):
        values = np.asarray(values, dtype=float)
        out[f"stance_{name}"] = values
        bullish = bullish + np.where(np.isfinite(values) & (values > 0), 1.0, 0.0)
    out["bullish_count"] = np.where(graded, bullish, np.nan)
    change = np.zeros(grades.shape)
    change[1:] = (grades[1:] != grades[:-1]) & graded[1:] & graded[:-1]
    age = np.zeros(grades.shape)
    for t in range(1, len(grades)):
        age[t] = np.where(change[t] > 0, 0.0, age[t - 1] + 1.0)
    out["grade_age"] = np.where(graded, np.log1p(age), np.nan)
    flips, _ = _window_sums(change, 60)
    out["grade_flips60"] = np.where(graded, flips, np.nan)
    for i, name in enumerate(REGIME_NAMES):
        out[name] = np.repeat(np.asarray(regime[:, i], dtype=float)[:, None], grades.shape[1], axis=1)
    logret = _log(adj_close / lag(adj_close, 1))
    up = eligible & np.isfinite(logret)
    with np.errstate(invalid="ignore", divide="ignore"):
        breadth = np.where(up.sum(axis=1) > 0, ((logret > 0) & up).sum(axis=1) / up.sum(axis=1), np.nan)
    out["breadth"] = np.repeat(breadth[:, None], grades.shape[1], axis=1)
    return out


# The date-level columns: their names (without prefix) are listed here so
# the T-S1 export leaves them unranked.
DATE_LEVEL = frozenset(
    set(REGIME_NAMES)
    | {"breadth", "vix_level", "vix_change_20", "vix_vs_realised"}
    | {f"weekday_{d}" for d in range(5)}
)


# Assemble the daily block from its families. `calendar_values` and
# `macro_values` are the (T, N, K) arrays of `calendar.calendar_features`
# and the VIX columns of `macro.macro_features`; the calendar's columns are
# date-level. Columns whose names start with "_" are internal and dropped.
def assemble(
    panel,
    families: Sequence[Mapping[str, np.ndarray]],
    calendar_values: np.ndarray | None = None,
    calendar_names: Sequence[str] = (),
    macro_values: np.ndarray | None = None,
    macro_names: Sequence[str] = (),
) -> DailyBlock:
    """Return the DailyBlock of the given family dicts plus calendar and macro."""
    columns: dict[str, np.ndarray] = {}
    date_level: dict[str, bool] = {}
    for family in families:
        for name, values in family.items():
            if name.startswith("_"):
                continue
            if name in columns:
                raise ValueError(f"duplicate daily column {name!r}")
            columns[name] = np.asarray(values, dtype=float)
            date_level[name] = name in DATE_LEVEL
    if calendar_values is not None:
        for i, name in enumerate(calendar_names):
            columns[name] = np.asarray(calendar_values[:, :, i], dtype=float)
            date_level[name] = True
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    weekday = (days.astype(np.int64) + 3) % 7
    for d in range(5):
        columns[f"weekday_{d}"] = np.repeat((weekday == d).astype(float)[:, None], len(panel.tickers), axis=1)
        date_level[f"weekday_{d}"] = True
    if macro_values is not None:
        for i, name in enumerate(macro_names):
            if name.startswith("vix"):
                columns[name] = np.asarray(macro_values[:, :, i], dtype=float)
                date_level[name] = True
    names = tuple(columns)
    stacked = np.stack([columns[n] for n in names], axis=2)
    stacked = np.where(np.isfinite(stacked), stacked, np.nan).astype(np.float32)
    return DailyBlock(
        dates=days,
        tickers=tuple(panel.tickers),
        names=tuple(f"{DAILY_PREFIX}{n}" for n in names),
        values=stacked,
        date_level=np.array([date_level[n] for n in names], dtype=bool),
    )


# The whole daily block from a panel and its side inputs: the location and
# trend families, the daily S/R block, returns and links, the cube-derived
# measures, events, CGO and the desk state, assembled in that order.
def daily_block(
    panel,
    *,
    sides: Mapping[str, str],
    side_returns: Mapping[str, np.ndarray],
    cubes: Mapping[str, SessionCube],
    eligible: np.ndarray,
    grades: np.ndarray,
    stances: Mapping[str, np.ndarray],
    regime: np.ndarray,
    earnings_day: np.ndarray,
    shares: np.ndarray | None = None,
    edgar_values: np.ndarray | None = None,
    edgar_names: Sequence[str] = (),
    tone_values: np.ndarray | None = None,
    tone_names: Sequence[str] = (),
    calendar_values: np.ndarray | None = None,
    calendar_names: Sequence[str] = (),
    macro_values: np.ndarray | None = None,
    macro_names: Sequence[str] = (),
) -> tuple[DailyBlock, dict[str, Any]]:
    """Return (DailyBlock, internals) where internals holds sigma20, ATR14 and the gap."""
    location = location_trend(panel)
    close = np.asarray(panel.adj_close, dtype=float)
    atr_fraction = location["_atr14"]
    ds = daily_levels_block(panel, close, atr_fraction)
    links = returns_links(panel, sides, side_returns, eligible, earnings_day)
    cube_cols = cube_daily(panel, cubes, atr_fraction)
    events = events_block(
        panel, edgar_values, edgar_names, tone_values, tone_names,
        earnings_day, links["abvol50"], links["_gap"], atr_fraction,
    )
    cgo = {"cgo": capital_gains_overhang(panel, shares) if shares is not None else np.full(close.shape, np.nan)}
    desk = desk_block(grades, stances, regime, close, eligible)
    block = assemble(
        panel,
        [location, ds, links, cube_cols, events, cgo, desk],
        calendar_values, calendar_names, macro_values, macro_names,
    )
    internals = {
        "sigma20": location["_sigma20"],
        "atr14": atr_fraction,
        "logret": links["_logret"],
        "trend_daily": location["trend_daily"],
        "trend_weekly": location["trend_weekly"],
        "trend_monthly": location["trend_monthly"],
    }
    return block, internals


__all__ = [
    "DailyBlock",
    "FULL_SESSION_SLOTS",
    "daily_block",
]
