"""Trade location: support, resistance, and whether the timeframes agree.

This is the technical analysis a discretionary trader means: not "is the
name ranked high on momentum" but "where is price sitting". Levels come
from confirmed swing points on the daily bars (a low that is the lowest of
its five neighbours either side, known only once the right-hand neighbours
have printed) and from the moving averages price tends to respect (daily
50 and 200 EMA, weekly 21 EMA). Support is the nearest such level below the
close, resistance the nearest confirmed swing high above it. From those:
distance to support, distance to resistance, reward-to-risk, position in
the 60-session range, the weekly and daily trend, and a confluence count
of how many things line up for a long entry. Everything is causal: a
value at session t reads only bars up to t.
"""

import numpy as np

from backend.market.panel import Panel
from backend.market.technical import _weekly_ema, ema

LEVEL_NAMES: tuple[str, ...] = (
    "support_distance",
    "resistance_distance",
    "reward_risk",
    "range_position_60",
    "weekly_trend",
    "daily_trend",
    "at_support",
    "no_overhead",
    "confluence",
)
SWING = 5
LEVEL_LOOKBACK = 250
AT_SUPPORT = 0.05
GOOD_REWARD_RISK = 2.0


# Confirmed swing lows and highs: a bar whose low is the lowest (high the
# highest) of the `k` bars either side. The level is stamped on the session
# that confirms it (t + k), never earlier.
def swing_points(
    high: np.ndarray, low: np.ndarray, k: int = SWING
) -> tuple[np.ndarray, np.ndarray]:
    """Return (swing_low_levels, swing_high_levels), (T, N), NaN where none."""
    rows, cols = low.shape
    lows = np.full((rows, cols), np.nan)
    highs = np.full((rows, cols), np.nan)
    for t in range(k, rows - k):
        # The neighbours only: a swing must beat them strictly, so a flat
        # stretch of equal bars is not a level.
        others = [i for i in range(t - k, t + k + 1) if i != t]
        window_low = low[others]
        window_high = high[others]
        with np.errstate(invalid="ignore"):
            is_low = np.isfinite(low[t]) & (low[t] < np.nanmin(window_low, axis=0))
            is_high = np.isfinite(high[t]) & (high[t] > np.nanmax(window_high, axis=0))
        lows[t + k] = np.where(is_low, low[t], np.nan)
        highs[t + k] = np.where(is_high, high[t], np.nan)
    return lows, highs


# The nearest level below (or above) the close among those confirmed in the
# last `lookback` sessions, per name.
def _nearest(
    levels: np.ndarray, close: np.ndarray, below: bool, lookback: int
) -> np.ndarray:
    rows, cols = close.shape
    out = np.full((rows, cols), np.nan)
    for t in range(rows):
        window = levels[max(0, t - lookback + 1) : t + 1]
        with np.errstate(invalid="ignore"):
            if below:
                candidates = np.where(window < close[t], window, np.nan)
                out[t] = np.nanmax(candidates, axis=0) if len(window) else np.nan
            else:
                candidates = np.where(window > close[t], window, np.nan)
                out[t] = np.nanmin(candidates, axis=0) if len(window) else np.nan
    return out


# Slope over `n` sessions as a fraction of the level.
def _slope(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[n:] = (x[n:] - x[:-n]) / np.abs(x[:-n])
    return out


# All level features per (session, name), (T, N, K) in LEVEL_NAMES order.
def level_features(panel: Panel) -> np.ndarray:
    """Return the trade-location features, causal."""
    close = panel.adj_close
    high, low = panel.high, panel.low
    swing_low, swing_high = swing_points(high, low)
    e50, e200 = ema(close, 50), ema(close, 200)
    w21 = _weekly_ema(panel, close, 21)
    e21 = ema(close, 21)
    # Support: nearest of the confirmed swing lows and the averages below.
    support = _nearest(swing_low, close, True, LEVEL_LOOKBACK)
    with np.errstate(invalid="ignore"):
        for level in (e50, e200, w21):
            candidate = np.where(level < close, level, np.nan)
            support = np.fmax(support, candidate)
        resistance = _nearest(swing_high, close, False, LEVEL_LOOKBACK)
        support_distance = (close - support) / close
        resistance_distance = (resistance - close) / close
        reward_risk = resistance_distance / np.maximum(support_distance, 0.01)
        high60 = _rolling(high, 60, largest=True)
        low60 = _rolling(low, 60, largest=False)
        range_position = (close - low60) / (high60 - low60)
        w21_slope = _slope(w21, 5)
        weekly_trend = np.where(
            (close > w21) & (w21_slope > 0),
            1.0,
            np.where((close < w21) & (w21_slope < 0), -1.0, 0.0),
        )
        weekly_trend = np.where(np.isfinite(w21_slope), weekly_trend, np.nan)
        e21_slope = _slope(e21, 5)
        daily_trend = np.where(
            (e21 > e50) & (e21_slope > 0),
            1.0,
            np.where((e21 < e50) & (e21_slope < 0), -1.0, 0.0),
        )
        daily_trend = np.where(np.isfinite(e50), daily_trend, np.nan)
        at_support = np.where(
            np.isfinite(support_distance),
            (support_distance <= AT_SUPPORT).astype(float),
            np.nan,
        )
        # No confirmed swing high overhead within the lookback: open sky.
        no_overhead = np.where(
            np.isfinite(close), (~np.isfinite(resistance)).astype(float), np.nan
        )
        good_rr = (reward_risk >= GOOD_REWARD_RISK) | (no_overhead > 0)
        confluence = (
            (weekly_trend > 0).astype(float)
            + (daily_trend > 0).astype(float)
            + (at_support > 0).astype(float)
            + good_rr.astype(float)
        )
        confluence = np.where(
            np.isfinite(weekly_trend),
            confluence,
            np.nan,
        )
    return np.stack(
        [
            support_distance,
            resistance_distance,
            reward_risk,
            range_position,
            weekly_trend,
            daily_trend,
            at_support,
            no_overhead,
            confluence,
        ],
        axis=2,
    )


# Rolling max or min over `n` sessions ending at t (inclusive).
def _rolling(x: np.ndarray, n: int, largest: bool) -> np.ndarray:
    out = np.full_like(x, np.nan)
    with np.errstate(invalid="ignore"):
        for t in range(n - 1, x.shape[0]):
            window = x[t - n + 1 : t + 1]
            out[t] = np.nanmax(window, axis=0) if largest else np.nanmin(window, axis=0)
    return out
