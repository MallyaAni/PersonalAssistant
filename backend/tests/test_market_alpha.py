"""The multi-scale features: causal, complete-window-only, exact where checkable."""

from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market.alpha import ALPHA_COUNT, ALPHA_NAMES, alpha_features
from backend.market.panel import panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory


# A history from a return series with a widening daily range.
def _history(ticker: str, returns: np.ndarray) -> TickerHistory:
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    first = date(2024, 1, 1)
    bars = tuple(
        DailyBar(first + timedelta(days=i), p, p * 1.02, p * 0.98, p, p, 1_000_000)
        for i, p in enumerate(prices)
    )
    return TickerHistory(
        ticker, bars, (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


def _panel(t: int = 120, n: int = 6, seed: int = 0):
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.01, size=(t, n))
    histories = {f"N{i}": _history(f"N{i}", returns[:, i]) for i in range(n)}
    histories["SPY"] = _history("SPY", returns.mean(axis=1))
    return panel_from_histories(histories, "SPY", {"N0": ("a",), "N1": ("a",)})


# Shape and names agree, and every feature is NaN until its window exists.
def test_shape_and_warmup():
    panel = _panel()
    feats = alpha_features(panel)
    assert feats.shape == (len(panel.dates), len(panel.tickers), ALPHA_COUNT)
    assert len(ALPHA_NAMES) == ALPHA_COUNT
    col = panel.index("N2")
    idx = ALPHA_NAMES.index("ret_60")
    assert np.isnan(feats[:60, col, idx]).all()
    assert np.isfinite(feats[60:, col, idx]).all()
    idx = ALPHA_NAMES.index("vol_5")
    assert np.isnan(feats[:5, col, idx]).all()
    assert np.isfinite(feats[5:, col, idx]).all()


# Features at session t do not change when the future is altered.
def test_features_are_causal():
    panel = _panel()
    before = alpha_features(panel)
    corrupted = panel.adj_close.copy()
    corrupted[90:] *= 3.0
    panel_after = panel_from_histories(
        {
            ticker: _history(ticker, np.diff(np.log(corrupted[:, i])))
            for i, ticker in enumerate(panel.tickers)
        },
        "SPY",
        panel.themes,
    )
    after = alpha_features(panel_after)
    assert np.allclose(before[:89], after[:89], equal_nan=True)


# ret_20 is the sum of the last twenty daily log returns, exactly.
def test_return_feature_is_exact():
    panel = _panel()
    feats = alpha_features(panel)
    col = panel.index("N3")
    returns = panel.log_returns()[:, col]
    idx = ALPHA_NAMES.index("ret_20")
    t = 80
    assert np.isclose(feats[t, col, idx], returns[t - 19 : t + 1].sum(), atol=1e-5)
    idx = ALPHA_NAMES.index("close_over_max_20")
    assert feats[t, col, idx] <= 1e-6  # at or below the rolling max


# Beta of the benchmark to itself is one, correlation one.
def test_market_beta_and_correlation_extremes():
    panel = _panel()
    feats = alpha_features(panel)
    bench = panel.index("SPY")
    assert np.isclose(feats[100, bench, ALPHA_NAMES.index("beta_60")], 1.0, atol=1e-4)
    assert np.isclose(
        feats[100, bench, ALPHA_NAMES.index("corr_mkt_60")], 1.0, atol=1e-4
    )
