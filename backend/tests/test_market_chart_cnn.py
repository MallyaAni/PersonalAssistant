"""The chart CNN: images drawn as claimed, and the fold runs end to end."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from backend.market import chart_cnn  # noqa: E402
from backend.market.model import TrainConfig, walk_forward  # noqa: E402
from backend.market.panel import panel_from_histories  # noqa: E402
from backend.market.yahoo import DailyBar, TickerHistory  # noqa: E402


# A history from a return series with a widening daily range.
def _history(ticker: str, returns: np.ndarray) -> TickerHistory:
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    first = date(2024, 1, 1)
    bars = tuple(
        DailyBar(
            first + timedelta(days=i), p * 0.995, p * 1.01, p * 0.99, p, p, 1e6 + i
        )
        for i, p in enumerate(prices)
    )
    return TickerHistory(
        ticker, bars, (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# The image has the documented shape, one bar column per day, the open tick
# left of the close tick, and the volume band at the bottom.
def test_render_chart_draws_bars_and_volume():
    closes = np.linspace(100, 120, chart_cnn.WINDOW)
    opens = closes - 0.5
    highs = closes + 1.0
    lows = closes - 1.5
    volumes = np.linspace(1, 2, chart_cnn.WINDOW)
    ma = np.full(chart_cnn.WINDOW, 110.0)
    image = chart_cnn.render_chart(opens, highs, lows, closes, volumes, ma)
    assert image.shape == (chart_cnn.IMAGE_HEIGHT, chart_cnn.IMAGE_WIDTH)
    assert image.dtype == np.float32
    # Day 0 (lowest prices) draws its bar near the bottom of the price rows,
    # day 19 near the top.
    col0 = image[: chart_cnn.PRICE_ROWS, 1]
    col19 = image[: chart_cnn.PRICE_ROWS, 58]
    assert np.flatnonzero(col0).mean() > np.flatnonzero(col19).mean()
    # The moving-average line is a horizontal row across every day.
    ma_rows = [
        r
        for r in range(chart_cnn.PRICE_ROWS)
        if image[r, ::3].sum() == chart_cnn.WINDOW
    ]
    assert len(ma_rows) == 1
    # Volume grows across the window: the last column's band is the tallest.
    band = image[chart_cnn.PRICE_ROWS + 1 :, 1::3].sum(axis=0)
    assert band[-1] >= band[0]
    assert (
        chart_cnn.render_chart(opens, highs, lows, closes * np.nan, volumes, ma) is None
    )


# Targets split each session at its own median.
def test_targets_are_session_relative():
    labels = np.array([[0.1, 0.2, 0.3, 0.4], [4.0, 3.0, 2.0, 1.0]])
    cells = np.array([[0, 0], [0, 3], [1, 0], [1, 3]])
    assert chart_cnn.above_median_targets(labels, cells).tolist() == [0, 1, 1, 0]


# The CNN encoder runs the walk-forward end to end and scores test cells.
def test_chart_cnn_fold_runs():
    rng = np.random.default_rng(2)
    n, t = 12, 160
    returns = rng.normal(0.0, 0.01, size=(t, n))
    histories = {f"N{i:02d}": _history(f"N{i:02d}", returns[:, i]) for i in range(n)}
    histories["SPY"] = _history("SPY", returns.mean(axis=1))
    panel = panel_from_histories(histories, "SPY", {})
    config = TrainConfig(
        window_size=5,
        horizon=5,
        momentum_length=30,
        momentum_skip=5,
        lookback=10,
        train_size=80,
        test_size=30,
        embargo=2,
        encoder="chart_cnn",
        epochs=1,
        cnn_max_train_cells=300,
    )
    result = walk_forward(panel, config)
    scored = np.isfinite(result.scores).any(axis=1)
    assert scored.sum() > 0
    expected = sorted({s for f in result.folds for s in f.test})
    assert set(np.flatnonzero(scored)).issubset(expected)
