"""The trader's toolkit as named features: EMAs, levels, candles, timeframes.

The first feature set covered candlestick shape (gap, range, close
position) and distance from 20- and 60-session means and extremes. It did
not cover the stack a discretionary trader actually watches: the 9, 21, 50
and 200 EMAs and the 200 SMA on the daily chart, the same on the weekly
chart, the 52-week high and low, and the named reversal candles. This
module builds those, causally, so each can be measured on its own through
the harness and fed to the models beside everything else.

Per (session, name):

    distance of close from the 9/21/50/200 EMA and the 200 SMA (log)
    slope of each EMA over 5 sessions (log change)
    stack order: how many of 9>21, 21>50, 50>200 hold, minus how many
      are inverted (-3..3)
    crossovers: 9/21 and 50/200 crossed up (+1) or down (-1) within 5 sessions
    weekly: distance from the 9- and 21-week EMA of weekly closes, weekly
      9>21 (weekly bars close on the last session of each calendar week)
    52-week high and low: log distance of close from each, and whether a
      new 52-week high was set within 5 sessions
    candles: hammer, shooting star, bullish and bearish engulfing on the
      last session (each 0/1), and a net reversal score (bullish minus
      bearish) over the last 3 sessions

    EMA spreads: (9 - 21) and (21 - 50) as a fraction of price, their
      3-session slope, and "converging" flags: +1 when the spread is below
      zero and rising (a cross up is coming), -1 when above zero and
      falling (a cross down is coming) - the slope change a trader watches
      for rather than the cross itself
    MACD family (Baz et al. 2015): the EMA-pair spread at three scales
      (8/24, 16/48, 32/96) divided by the 63-session price volatility and
      then by its own 252-session volatility, and their mean

Everything is NaN until its window is complete; a 200-day EMA needs 200
sessions, and a name listed last year has none. Nothing here is traded on
its own; each is a claim a trader makes, made measurable.
"""

import numpy as np

from backend.market.alpha import _rolling_extreme
from backend.market.panel import Panel

TECHNICAL_NAMES: tuple[str, ...] = (
    "ema9_distance",
    "ema21_distance",
    "ema50_distance",
    "ema200_distance",
    "sma200_distance",
    "ema9_slope",
    "ema21_slope",
    "ema50_slope",
    "ema200_slope",
    "stack_order",
    "cross_9_21",
    "cross_50_200",
    "weekly_ema9_distance",
    "weekly_ema21_distance",
    "weekly_stack",
    "high_52w_distance",
    "low_52w_distance",
    "new_52w_high",
    "hammer",
    "shooting_star",
    "bullish_engulfing",
    "bearish_engulfing",
    "reversal_net_3",
    "spread_9_21",
    "spread_9_21_slope",
    "spread_21_50",
    "spread_21_50_slope",
    "converging_9_21",
    "converging_21_50",
    "macd_8_24",
    "macd_16_48",
    "macd_32_96",
    "macd_composite",
)
TECHNICAL_COUNT = len(TECHNICAL_NAMES)


# An exponential moving average per column, NaN until `span` values exist.
def ema(values: np.ndarray, span: int) -> np.ndarray:
    """Return the (T, N) EMA with the standard 2/(span+1) weight."""
    alpha = 2.0 / (span + 1.0)
    out = np.full_like(values, np.nan)
    rows = values.shape[0]
    state = np.full(values.shape[1], np.nan)
    count = np.zeros(values.shape[1], dtype=int)
    for t in range(rows):
        x = values[t]
        known = np.isfinite(x)
        fresh = known & ~np.isfinite(state)
        state = np.where(fresh, x, state)
        cont = known & ~fresh
        state = np.where(cont, alpha * x + (1 - alpha) * state, state)
        count = np.where(known, count + 1, 0)
        state = np.where(known, state, np.nan)
        out[t] = np.where(count >= span, state, np.nan)
    return out


# A simple moving average per column, NaN until `length` values exist.
def sma(values: np.ndarray, length: int) -> np.ndarray:
    """Return the (T, N) rolling mean over `length` sessions."""
    known = np.isfinite(values)
    filled = np.where(known, values, 0.0)
    cumulative = np.vstack([np.zeros((1, values.shape[1])), np.cumsum(filled, axis=0)])
    counts = np.vstack([np.zeros((1, values.shape[1])), np.cumsum(known, axis=0)])
    out = np.full_like(values, np.nan)
    for t in range(length - 1, values.shape[0]):
        complete = (counts[t + 1] - counts[t + 1 - length]) == length
        out[t] = np.where(
            complete, (cumulative[t + 1] - cumulative[t + 1 - length]) / length, np.nan
        )
    return out


# Log distance of price from a level, NaN where either is unknown.
def _distance(price: np.ndarray, level: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.log(price / level)
    return np.where(np.isfinite(out), out, np.nan)


# Log change of a series over `lag` sessions.
def _slope(series: np.ndarray, lag: int) -> np.ndarray:
    out = np.full_like(series, np.nan)
    out[lag:] = _distance(series[lag:], series[:-lag])
    return out


# +1 where `fast` crossed above `slow` within the last `window` sessions,
# -1 where it crossed below, 0 otherwise.
def _crossover(fast: np.ndarray, slow: np.ndarray, window: int) -> np.ndarray:
    above = fast > slow
    known = np.isfinite(fast) & np.isfinite(slow)
    signal = np.zeros_like(fast)
    for t in range(1, fast.shape[0]):
        up = above[t] & ~above[t - 1] & known[t] & known[t - 1]
        down = ~above[t] & above[t - 1] & known[t] & known[t - 1]
        signal[t] = np.where(up, 1.0, np.where(down, -1.0, 0.0))
    out = np.zeros_like(fast)
    for t in range(fast.shape[0]):
        recent = signal[max(0, t - window + 1) : t + 1]
        latest = np.zeros(fast.shape[1])
        for row in recent:
            latest = np.where(row != 0, row, latest)
        out[t] = latest
    out[~known] = np.nan
    return out


# Weekly closes carried forward daily: the last session of each calendar
# week is the weekly close; between weekly closes the value is the last
# completed week's, so nothing from the current week leaks in.
def _weekly_series(panel: Panel, values: np.ndarray) -> np.ndarray:
    dates = panel.dates.astype("datetime64[D]")
    # ISO week number changes mark week boundaries.
    weeks = (dates.astype("datetime64[W]")).astype(int)
    rows = values.shape[0]
    weekly_close = np.full_like(values, np.nan)
    last_week_value = np.full(values.shape[1], np.nan)
    for t in range(rows):
        ends_week = t + 1 == rows or weeks[t + 1] != weeks[t]
        if ends_week:
            last_week_value = np.where(
                np.isfinite(values[t]), values[t], last_week_value
            )
        weekly_close[t] = last_week_value
    return weekly_close


# EMA over weekly closes, evaluated only at week ends and carried forward.
#
# The last row of the panel is NOT treated as a week end. Live, the panel
# ends today and today's week is usually still forming; counting it as a
# close would give the newest session a weekly EMA that includes a partial
# week, while every historical row uses completed weeks. The desk would
# then read a different weekly trend live than the one measured in the
# backtest. A mid-week session carries the last completed week's value,
# which is the same thing a backtest at that row sees.
def _weekly_ema(panel: Panel, close: np.ndarray, span: int) -> np.ndarray:
    dates = panel.dates.astype("datetime64[D]")
    # NumPy's datetime64[W] buckets weeks from the epoch, a Thursday, so
    # its "weeks" run Thursday to Wednesday and its week ends are
    # Wednesdays. Shift by three days so a week is Monday to Friday,
    # which is the week a trader means.
    weeks = (dates.astype(int) + 3) // 7
    rows = close.shape[0]
    # A session ends the week when it is a Friday, or when the next session
    # on file starts a new week (a short week whose Friday is a holiday).
    # The next-session test alone would fail on the newest row, where
    # there is no next session yet; the weekday test is what a trader
    # uses at a Friday close and needs no future.
    friday = (dates.astype(int) + 3) % 7 == 4
    ends = np.array(
        [
            bool(friday[t]) or (t + 1 < rows and weeks[t + 1] != weeks[t])
            for t in range(rows)
        ]
    )
    week_rows = np.flatnonzero(ends)
    weekly = ema(close[week_rows], span)
    out = np.full_like(close, np.nan)
    carried = np.full(close.shape[1], np.nan)
    pointer = 0
    for t in range(rows):
        if pointer < len(week_rows) and week_rows[pointer] == t:
            carried = weekly[pointer]
            pointer += 1
        out[t] = carried
    return out


# Named candles on each session from its own OHLC and the previous one.
def _candles(panel: Panel) -> dict[str, np.ndarray]:
    o, h, low, c = panel.open, panel.high, panel.low, panel.close
    body = np.abs(c - o)
    rng = h - low
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - low
    with np.errstate(invalid="ignore", divide="ignore"):
        small_body = body <= 0.35 * rng
        hammer = small_body & (lower >= 2 * body) & (upper <= 0.25 * rng)
        star = small_body & (upper >= 2 * body) & (lower <= 0.25 * rng)
    prev_o = np.vstack([np.full((1, c.shape[1]), np.nan), o[:-1]])
    prev_c = np.vstack([np.full((1, c.shape[1]), np.nan), c[:-1]])
    bull_engulf = (c > o) & (prev_c < prev_o) & (c >= prev_o) & (o <= prev_c)
    bear_engulf = (c < o) & (prev_c > prev_o) & (c <= prev_o) & (o >= prev_c)
    known = np.isfinite(o) & np.isfinite(h) & np.isfinite(low) & np.isfinite(c)
    known_prev = known & np.isfinite(prev_o) & np.isfinite(prev_c)

    def flag(mask: np.ndarray, valid: np.ndarray) -> np.ndarray:
        return np.where(valid, mask.astype(float), np.nan)

    hammer_f = flag(hammer, known)
    star_f = flag(star, known)
    bull_f = flag(bull_engulf, known_prev)
    bear_f = flag(bear_engulf, known_prev)
    net = (
        np.nan_to_num(hammer_f)
        + np.nan_to_num(bull_f)
        - np.nan_to_num(star_f)
        - np.nan_to_num(bear_f)
    )
    net3 = np.zeros_like(net)
    for t in range(net.shape[0]):
        net3[t] = net[max(0, t - 2) : t + 1].sum(axis=0)
    net3 = np.where(known, net3, np.nan)
    return {
        "hammer": hammer_f,
        "shooting_star": star_f,
        "bullish_engulfing": bull_f,
        "bearish_engulfing": bear_f,
        "reversal_net_3": net3,
    }


# Build the (T, N, TECHNICAL_COUNT) feature array for a panel.
def technical_features(panel: Panel) -> np.ndarray:
    """Return the trader's-toolkit features per (session, name), causal."""
    close = panel.adj_close
    e9, e21, e50, e200 = (ema(close, n) for n in (9, 21, 50, 200))
    s200 = sma(close, 200)
    stack = np.zeros_like(close)
    for fast, slow in ((e9, e21), (e21, e50), (e50, e200)):
        stack = stack + np.where(fast > slow, 1.0, -1.0)
    stack = np.where(np.isfinite(e200), stack, np.nan)
    w9 = _weekly_ema(panel, close, 9)
    w21 = _weekly_ema(panel, close, 21)
    weekly_stack = np.where(np.isfinite(w21), np.where(w9 > w21, 1.0, -1.0), np.nan)
    high52 = _rolling_extreme(panel.high, 252, largest=True)
    low52 = _rolling_extreme(panel.low, 252, largest=False)
    prev_high52 = np.vstack([np.full((1, close.shape[1]), np.nan), high52[:-1]])
    new_high = np.where(
        np.isfinite(high52) & np.isfinite(prev_high52),
        (panel.high >= prev_high52).astype(float),
        np.nan,
    )
    new_high5 = np.full_like(new_high, np.nan)
    for t in range(new_high.shape[0]):
        window = np.nan_to_num(new_high[max(0, t - 4) : t + 1], nan=0.0)
        new_high5[t] = np.where(np.isfinite(new_high[t]), window.max(axis=0), np.nan)
    candles = _candles(panel)
    with np.errstate(invalid="ignore", divide="ignore"):
        spread_9_21 = (e9 - e21) / close
        spread_21_50 = (e21 - e50) / close
    macd = [_macd(close, short, long) for short, long in ((8, 24), (16, 48), (32, 96))]
    stacked_macd = np.stack(macd, axis=2)
    known_macd = np.isfinite(stacked_macd)
    macd_composite = np.where(
        known_macd.all(axis=2),
        np.where(known_macd, stacked_macd, 0.0).sum(axis=2) / 3.0,
        np.nan,
    )
    columns = [
        _distance(close, e9),
        _distance(close, e21),
        _distance(close, e50),
        _distance(close, e200),
        _distance(close, s200),
        _slope(e9, 5),
        _slope(e21, 5),
        _slope(e50, 5),
        _slope(e200, 5),
        stack,
        _crossover(e9, e21, 5),
        _crossover(e50, e200, 5),
        _distance(close, w9),
        _distance(close, w21),
        weekly_stack,
        _distance(close, high52),
        _distance(close, low52),
        new_high5,
        candles["hammer"],
        candles["shooting_star"],
        candles["bullish_engulfing"],
        candles["bearish_engulfing"],
        candles["reversal_net_3"],
        spread_9_21,
        _slope_diff(spread_9_21, 3),
        spread_21_50,
        _slope_diff(spread_21_50, 3),
        _converging(spread_9_21, 3),
        _converging(spread_21_50, 3),
        macd[0],
        macd[1],
        macd[2],
        macd_composite,
    ]
    stacked = np.stack(columns, axis=2)
    assert stacked.shape[2] == TECHNICAL_COUNT
    return np.where(np.isfinite(stacked), stacked, np.nan).astype(np.float32)


# The change of a series over `lag` sessions (a plain difference, for
# spreads that are already fractions of price).
def _slope_diff(series: np.ndarray, lag: int) -> np.ndarray:
    out = np.full_like(series, np.nan)
    out[lag:] = series[lag:] - series[:-lag]
    return out


# +1 where the spread is below zero and rising over `lag` sessions (a cross
# up is approaching), -1 where above zero and falling, 0 otherwise.
def _converging(spread: np.ndarray, lag: int) -> np.ndarray:
    slope = _slope_diff(spread, lag)
    known = np.isfinite(spread) & np.isfinite(slope)
    up = (spread < 0) & (slope > 0)
    down = (spread > 0) & (slope < 0)
    out = np.where(up, 1.0, np.where(down, -1.0, 0.0))
    return np.where(known, out, np.nan)


# The normalised MACD of Baz et al. (2015): the EMA-pair spread divided by
# the 63-session price volatility, then by the 252-session volatility of
# that ratio, so scales and names are comparable.
def _macd(close: np.ndarray, short: int, long: int) -> np.ndarray:
    from backend.market.alpha import _rolling_std

    spread = ema(close, short) - ema(close, long)
    price_vol = _rolling_std(close, 63)
    with np.errstate(invalid="ignore", divide="ignore"):
        scaled = spread / price_vol
    scaled = np.where(np.isfinite(scaled), scaled, np.nan)
    scale_vol = _rolling_std(scaled, 252)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = scaled / scale_vol
    return np.where(np.isfinite(out), out, np.nan)
