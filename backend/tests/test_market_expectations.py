"""The expectations study's pure parts.

What has to hold: residual momentum over k sessions is the name's log
return less beta times the market's over the same window, NaN until the
window fills; and the learner fits and predicts through the native API
without scikit-learn.
"""

import numpy as np
import pytest

from backend.cli.market_expectations import _fit_predict, _momentum
from backend.market.panel import Panel


def test_residual_momentum_removes_the_markets_part():
    rows = 8
    bench = 100.0 * np.exp(0.01 * np.arange(rows))
    own = 50.0 * np.exp(0.03 * np.arange(rows))
    close = np.column_stack([own, bench])
    panel = Panel(
        dates=np.arange(rows).astype("datetime64[D]"),
        tickers=("AAA", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.ones_like(close),
        themes={},
        benchmark="SPY",
    )
    beta = np.full(close.shape, 2.0)
    mom = _momentum(panel, beta, 4)
    assert np.isnan(mom[:4, 0]).all()
    # Own 4-session log return 0.12, market 0.04, beta 2: residual 0.04.
    assert mom[4:, 0] == pytest.approx(0.12 - 2.0 * 0.04)


def test_the_learner_fits_and_predicts_without_scikit_learn():
    pytest.importorskip("lightgbm")
    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 3))
    y = 0.5 * x[:, 0] + rng.normal(scale=0.1, size=400)
    pred, booster = _fit_predict(x[:300], y[:300], x[300:], ("a", "b", "c"))
    assert pred.shape == (100,)
    assert np.corrcoef(pred, y[300:])[0, 1] > 0.8
    assert booster.feature_importance(importance_type="gain")[0] > 0
