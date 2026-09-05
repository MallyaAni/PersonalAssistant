"""The panel and the window tensors: alignment, no look-ahead, labels.

A panel aligns histories on their shared calendar without inventing a
price; a window ending at session t contains nothing after t; labels are
separate, marked invalid where the future is not fully known, and carry the
date the label's horizon ends so a harness can purge on it; the theme
channels are the equal-weight basket, and a name without a theme degrades
to the market rather than to a fabricated zero.
"""

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market.panel import panel_from_histories
from backend.market.windows import (
    CHANNELS,
    OWN_RETURN,
    THEME_VS_MARKET,
    VS_MARKET,
    VS_THEME,
    build_windows,
)
from backend.market.yahoo import DailyBar, TickerHistory


# A history of consecutive sessions with closes following `returns`.
def _history(
    ticker: str,
    returns: list[float],
    first: date = date(2026, 1, 5),
    base: float = 100.0,
    skip: set[date] | None = None,
) -> TickerHistory:
    prices = [base]
    for r in returns:
        prices.append(prices[-1] * (1.0 + r))
    bars = []
    for i, p in enumerate(prices):
        day = first + timedelta(days=i)
        if skip and day in skip:
            continue
        bars.append(DailyBar(day, p, p * 1.01, p * 0.99, p, p, 1_000_000))
    return TickerHistory(
        ticker, tuple(bars), (), bars[-1].session_date, datetime(2026, 3, 1, tzinfo=UTC)
    )


# The standard fixture: a benchmark, two themed names, one untagged name.
def _panel(n: int = 40, skip_a: set[date] | None = None):
    histories = {
        "SPY": _history("SPY", [0.001] * n),
        "AAA": _history("AAA", [0.01] * n, skip=skip_a),
        "BBB": _history("BBB", [0.02] * n),
        "CCC": _history("CCC", [-0.005] * n),
    }
    themes = {"AAA": ("ai-compute",), "BBB": ("ai-compute",)}
    return panel_from_histories(histories, "SPY", themes)


# The theme return is the equal-weight mean of its members' returns, and an
# untagged name's theme series is the benchmark's.
def test_theme_returns_are_equal_weight_and_untagged_falls_back_to_market():
    panel = _panel()
    theme = panel.theme_returns()["ai-compute"]
    expected = (math.log(1.01) + math.log(1.02)) / 2
    assert np.allclose(theme[1:], expected)
    matrix = panel.theme_return_matrix()
    assert np.allclose(matrix[1:, panel.index("CCC")], panel.benchmark_returns()[1:])
    assert np.allclose(matrix[1:, panel.index("AAA")], expected)


# Windows have the documented shape, and the relative channels are the
# differences they claim to be.
def test_window_channels_are_the_documented_differences():
    panel = _panel()
    result = build_windows(panel, window_size=10, horizon=5)
    assert result.inputs.shape[1:] == (10, CHANNELS)
    assert result.inputs.dtype == np.float32
    first_aaa = np.flatnonzero(result.tickers == "AAA")[0]
    window = result.inputs[first_aaa]
    own = math.log(1.01)
    bench = math.log(1.001)
    theme = (math.log(1.01) + math.log(1.02)) / 2
    assert np.allclose(window[:, OWN_RETURN], own, atol=1e-6)
    assert np.allclose(window[:, VS_MARKET], own - bench, atol=1e-6)
    assert np.allclose(window[:, VS_THEME], own - theme, atol=1e-6)
    assert np.allclose(window[:, THEME_VS_MARKET], theme - bench, atol=1e-6)
    # The benchmark itself is never a window.
    assert "SPY" not in set(result.tickers)


# No window that ends before a one-day jump contains it; the window ending
# on the jump ends with it.
def test_windows_do_not_contain_future_returns():
    n = 30
    returns = [0.01] * n
    returns[15] = 0.9
    histories = {"SPY": _history("SPY", [0.001] * n), "AAA": _history("AAA", returns)}
    panel = panel_from_histories(histories, "SPY", {})
    jump_date = np.datetime64(date(2026, 1, 5) + timedelta(days=16), "D")
    result = build_windows(panel, window_size=10, horizon=1)
    jump = math.log(1.9)
    for end, window in zip(result.end_dates, result.inputs, strict=True):
        own = window[:, OWN_RETURN]
        if end < jump_date:
            assert not np.any(np.abs(own - jump) < 1e-4), "future return leaked in"
        if end == jump_date:
            assert abs(own[-1] - jump) < 1e-4


# Labels are the forward returns over the horizon, invalid where the future
# is not fully known, and the label end date is horizon sessions after the
# window end.
def test_labels_are_forward_only_and_flagged_when_incomplete():
    panel = _panel(n=30)
    horizon = 5
    result = build_windows(panel, window_size=5, horizon=horizon)
    dates = panel.dates
    for i in range(result.size):
        t = int(np.flatnonzero(dates == result.end_dates[i])[0])
        column = panel.index(str(result.tickers[i]))
        if t + horizon < len(dates):
            assert result.valid[i]
            expected = math.log(
                panel.adj_close[t + horizon, column] / panel.adj_close[t, column]
            )
            assert abs(result.own_future[i] - expected) < 1e-5
            assert result.label_end_dates[i] == dates[t + horizon]
            market = math.log(
                panel.adj_close[t + horizon, panel.index("SPY")]
                / panel.adj_close[t, panel.index("SPY")]
            )
            assert abs(result.residual_future[i] - (expected - market)) < 1e-5
        else:
            assert not result.valid[i]
            assert np.isnat(result.label_end_dates[i])
    assert result.valid.sum() > 0
    assert (~result.valid).sum() == 3 * horizon


# A ticker missing a session gets no window spanning the gap, and the
# theme basket that day is the remaining member alone.
def test_a_missing_session_drops_windows_over_the_gap():
    gap = date(2026, 1, 20)
    panel = _panel(skip_a={gap})
    result = build_windows(panel, window_size=5, horizon=1)
    gap64 = np.datetime64(gap, "D")
    for ticker, end in zip(result.tickers, result.end_dates, strict=True):
        if ticker != "AAA":
            continue
        # A gap breaks the return on the gap day and the day after it.
        assert not (
            end - np.timedelta64(4, "D") <= gap64 + np.timedelta64(1, "D")
            and gap64 <= end
        )
    theme = panel.theme_returns()["ai-compute"]
    gap_row = int(np.flatnonzero(panel.dates == gap64)[0])
    assert abs(theme[gap_row] - math.log(1.02)) < 1e-9


# An empty panel of names yields an empty, correctly shaped window set.
def test_empty_window_set_shape():
    panel = panel_from_histories({"SPY": _history("SPY", [0.001] * 10)}, "SPY", {})
    result = build_windows(panel, window_size=5, horizon=2)
    assert result.inputs.shape == (0, 5, CHANNELS)
    assert result.size == 0
