"""Trade location: swing points, support, resistance, trends, confluence."""

from datetime import date, timedelta

import numpy as np

from backend.market import levels
from backend.market.panel import Panel


# A one-name panel (plus SPY) from a close path; highs and lows hug the close.
def _panel(close: np.ndarray) -> Panel:
    t = len(close)
    both = np.stack([close, np.full(t, 100.0)], axis=1)
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    return Panel(
        dates=dates,
        tickers=("AAA", "SPY"),
        open=both,
        high=both * 1.01,
        low=both * 0.99,
        close=both,
        adj_close=both,
        volume=np.full_like(both, 1e6),
        themes={"AAA": ()},
        benchmark="SPY",
    )


# A swing low is stamped only once its right-hand neighbours have printed,
# and it is the low of the bar, not the close.
def test_swing_points_are_confirmed_late():
    close = np.full(30, 100.0)
    close[10] = 90.0  # a single dip
    panel = _panel(close)
    lows, highs = levels.swing_points(panel.high, panel.low)
    assert np.isnan(lows[10, 0])
    assert lows[15, 0] == 90.0 * 0.99
    assert np.isnan(lows[16, 0])
    assert np.isnan(highs[:, 0]).all() or np.nanmax(highs[:, 0]) <= 101.0


# Support is the nearest confirmed level below the close; resistance the
# nearest confirmed swing high above it; open sky when there is none.
def test_support_and_resistance_are_nearest_levels():
    close = np.full(120, 100.0)
    close[20] = 80.0  # swing low at 79.2
    close[40] = 90.0  # swing low at 89.1, nearer
    close[60] = 120.0  # swing high at 121.2
    panel = _panel(close)
    feats = levels.level_features(panel)
    idx = {n: i for i, n in enumerate(levels.LEVEL_NAMES)}
    last = feats[-1, 0]
    # Support may be an average sitting between 89.1 and 100; it is never
    # below the nearer swing low and always below the close.
    assert 0 < last[idx["support_distance"]] <= (100 - 89.1) / 100 + 1e-9
    assert abs(last[idx["resistance_distance"]] - (121.2 - 100) / 100) < 1e-9
    assert last[idx["no_overhead"]] == 0.0
    flat = levels.level_features(_panel(np.full(120, 100.0)))
    assert flat[-1, 0, idx["no_overhead"]] == 1.0


# Trends read the timeframes: a steady climb has both trends up, a steady
# fall both down, and confluence counts the aligned pieces.
def test_trends_and_confluence():
    up = 100.0 * np.exp(np.cumsum(np.full(300, 0.003)))
    down = 100.0 * np.exp(np.cumsum(np.full(300, -0.003)))
    idx = {n: i for i, n in enumerate(levels.LEVEL_NAMES)}
    rising = levels.level_features(_panel(up))[-1, 0]
    falling = levels.level_features(_panel(down))[-1, 0]
    assert rising[idx["weekly_trend"]] == 1.0
    assert rising[idx["daily_trend"]] == 1.0
    assert falling[idx["weekly_trend"]] == -1.0
    assert falling[idx["daily_trend"]] == -1.0
    assert rising[idx["range_position_60"]] > 0.9
    assert rising[idx["confluence"]] >= 2
    assert falling[idx["confluence"]] <= 1
