"""Baselines and the harness: a planted signal is found, a purge is a purge.

The harness is trusted only if it finds a signal that is really there and
finds nothing in noise; the fold builder is trusted only if no training
session can carry a label that ends inside its test range.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market import baselines
from backend.market.harness import (
    evaluate_scores,
    long_short_weights,
    rank_correlation,
    walk_forward_folds,
)
from backend.market.panel import panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory


# A history from a return series.
def _history(
    ticker: str, returns: np.ndarray, first: date = date(2024, 1, 1)
) -> TickerHistory:
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    bars = tuple(
        DailyBar(first + timedelta(days=i), p, p * 1.01, p * 0.99, p, p, 1_000_000)
        for i, p in enumerate(prices)
    )
    return TickerHistory(
        ticker, bars, (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# A panel of `n` names over `t` sessions where each name has a persistent
# drift (so momentum is real) plus noise; benchmark is the average.
def _drift_panel(
    n: int = 40,
    t: int = 400,
    drift_scale: float = 0.004,
    noise: float = 0.01,
    seed: int = 7,
):
    rng = np.random.default_rng(seed)
    drifts = rng.normal(0.0, drift_scale, size=n)
    returns = drifts[None, :] + rng.normal(0.0, noise, size=(t, n))
    histories = {f"N{i:03d}": _history(f"N{i:03d}", returns[:, i]) for i in range(n)}
    histories["SPY"] = _history("SPY", returns.mean(axis=1))
    themes = {f"N{i:03d}": ("alpha",) if i % 2 == 0 else ("beta",) for i in range(n)}
    return panel_from_histories(histories, "SPY", themes)


# Trailing sums are exact and NaN until the span is complete.
def test_trailing_sum_is_exact_and_requires_a_complete_span():
    returns = np.arange(1.0, 11.0)[:, None]
    out = baselines.trailing_sum(returns, length=3, skip=1)
    assert np.isnan(out[:3, 0]).all()
    assert out[3, 0] == 1 + 2 + 3  # sessions 0..2, skipping session 3
    assert out[9, 0] == 7 + 8 + 9
    returns[5, 0] = np.nan
    out = baselines.trailing_sum(returns, length=3)
    assert np.isnan(out[5:8, 0]).all()
    assert out[8, 0] == 7 + 8 + 9


# Momentum finds a planted persistent drift: positive IC, positive net PnL.
def test_momentum_finds_a_planted_drift():
    panel = _drift_panel()
    scores = baselines.momentum(panel, length=120, skip=5)
    report = evaluate_scores(scores, panel, horizon=10, cost_bps=10, min_names=20)
    assert report.count >= 20
    assert report.mean_ic > 0.15
    assert report.ic_tstat > 3
    assert report.mean_net_return > 0
    assert report.total_cost > 0


# The same harness finds nothing in a shuffled score matrix.
def test_harness_finds_nothing_in_noise():
    panel = _drift_panel()
    rng = np.random.default_rng(1)
    scores = rng.normal(size=panel.adj_close.shape)
    report = evaluate_scores(scores, panel, horizon=10, cost_bps=10, min_names=20)
    assert abs(report.mean_ic) < 0.1
    assert abs(report.ic_tstat) < 2.5


# Theme momentum ranks baskets: every member of a theme shares a score.
def test_theme_momentum_is_a_basket_score():
    panel = _drift_panel(n=10, t=60)
    scores = baselines.theme_momentum(panel, lookback=5)
    row = scores[-1]
    alpha = [row[panel.index(f"N{i:03d}")] for i in range(0, 10, 2)]
    beta = [row[panel.index(f"N{i:03d}")] for i in range(1, 10, 2)]
    assert np.allclose(alpha, alpha[0])
    assert np.allclose(beta, beta[0])
    assert np.isnan(row[panel.index("SPY")])


# Percentile ranks average ties and span [0, 1].
def test_percentile_rank_averages_ties():
    ranks = baselines.percentile_rank(np.array([[1.0, 3.0, 3.0, np.nan, 0.0]]))[0]
    assert ranks[4] == 0.0
    assert ranks[0] == 1 / 3
    assert ranks[1] == ranks[2] == 2.5 / 3
    assert np.isnan(ranks[3])


# Rank correlation is 1 for a monotone relation and 0 for orthogonal ranks.
def test_rank_correlation_extremes():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert abs(rank_correlation(a, np.exp(a)) - 1.0) < 1e-12
    assert abs(rank_correlation(a, -a) + 1.0) < 1e-12
    # d = (0, -2, 1, 1): 1 - 6*6 / (4*15) = 0.4
    assert (
        abs(
            rank_correlation(
                np.array([1.0, 2.0, 3.0, 4.0]), np.array([1.0, 4.0, 2.0, 3.0])
            )
            - 0.4
        )
        < 1e-12
    )


# Long-short weights sum to zero and each side to one.
def test_long_short_weights_are_balanced():
    weights = long_short_weights(np.array([0.1, 0.5, -0.2, 0.9, 0.3]), top_fraction=0.4)
    assert abs(weights.sum()) < 1e-12
    assert abs(weights[weights > 0].sum() - 1.0) < 1e-12
    assert weights[3] > 0
    assert weights[1] > 0
    assert weights[2] < 0
    assert weights[0] < 0


# Costs scale with turnover and reduce the net return exactly.
def test_costs_are_charged_on_turnover():
    panel = _drift_panel(n=30, t=120)
    scores = baselines.momentum(panel, length=40, skip=2)
    free = evaluate_scores(scores, panel, horizon=10, cost_bps=0, min_names=10)
    paid = evaluate_scores(scores, panel, horizon=10, cost_bps=25, min_names=10)
    assert free.count == paid.count
    for a, b in zip(free.periods, paid.periods, strict=True):
        assert a.gross_return == b.gross_return
        assert abs(b.cost - b.turnover * 0.0025) < 1e-12
    assert paid.total_net_return < free.total_net_return


# Periods never overlap: consecutive rebalance dates are >= horizon apart.
def test_rebalance_periods_do_not_overlap():
    panel = _drift_panel(n=30, t=200)
    scores = baselines.relative_strength(panel, lookback=20)
    report = evaluate_scores(scores, panel, horizon=10, min_names=10)
    dates = [p.date for p in report.periods]
    gaps = [b - a for a, b in zip(dates, dates[1:], strict=False)]
    assert all(gap >= np.timedelta64(10, "D") for gap in gaps)
    assert all(p.names == 30 for p in report.periods)  # the benchmark is never ranked


# No training session in any fold can carry a label ending inside its test
# range: the train range ends at least horizon + embargo before the test.
def test_walk_forward_folds_purge_the_label_horizon():
    horizon, embargo = 10, 3
    folds = walk_forward_folds(
        n_sessions=300, train_size=100, test_size=25, horizon=horizon, embargo=embargo
    )
    assert len(folds) == (300 - 100 - horizon - embargo) // 25
    previous_test_start = None
    for train, test in folds:
        assert len(train) == 100
        assert len(test) == 25
        assert train.stop + horizon + embargo == test.start
        # A label from the last training session ends before the test starts.
        assert train.stop - 1 + horizon < test.start
        if previous_test_start is not None:
            assert test.start == previous_test_start + 25
        previous_test_start = test.start
