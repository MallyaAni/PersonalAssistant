"""The expectations study's pure parts.

What has to hold: residual momentum over k sessions is the name's log
return less beta times the market's over the same window, NaN until the
window fills; the learner fits and predicts through the native API
without scikit-learn; and a row's surprise fifth uses only the reports up
to its own session, never the reports that come after it, and is not
placed until its own history has enough reports.
"""

import numpy as np
import pytest

from backend.cli.market_expectations import _fifths, _fit_predict, _momentum
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


def test_a_fifths_bucket_never_depends_on_later_reports():
    n = 30
    years = np.array([2020] * n)
    meta = [(0, r, 2020) for r in range(n)]
    values = np.arange(n, dtype=float)
    shape = (n, 1)
    ok = np.ones(n, dtype=bool)
    first = _fifths(values, ok, meta, years, [2020], shape, 0)
    # A later report must not move an earlier row's bucket: make the last
    # report's value enormous and every other row must keep its fifth.
    moved = values.copy()
    moved[-1] = 1e6
    second = _fifths(moved, ok, meta, years, [2020], shape, 0)
    assert (first[: n - 1] == second[: n - 1]).all()
    # A row is not bucketed until its own trailing history has 25 reports.
    assert not first[:24].any()
    # Row 25 is placed from its own trailing pool (values 0..25): 25 sits
    # above the 80th percentile of 0..25, so it is the most positive fifth.
    assert first[25, 0, 4]
    assert not first[25, 0, :4].any()
