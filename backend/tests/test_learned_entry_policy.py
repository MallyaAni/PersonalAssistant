"""Economic decision and cash-ledger properties for learned entry research."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk.simulate import _Book
from backend.market.learned_entry_evaluation import funded_fill, score
from backend.market.learned_entry_policy import (
    correlation,
    decide,
    growth_parameters,
    growth_weights,
)


# Supply deterministic preceding histories with different correlated risk paths.
def history():
    rng = np.random.default_rng(7)
    moves = rng.normal(0, 0.01, (252, 3))
    moves[:, 1] = moves[:, 0] + rng.normal(0, 0.001, 252)
    return np.vstack((np.ones(3), np.exp(np.cumsum(moves, axis=0))))


# Learned expected return and risk change allocation rather than imposing equal weights.
def test_weights_respond_to_return_and_risk():
    low = growth_weights([0.005, 0.004], np.diag([0.1, 0.1]), [0, 0], [0.25, 0.25], 0)
    high = growth_weights([0.005, 0.004], np.diag([0.02, 0.1]), [0, 0], [0.25, 0.25], 0)
    assert low[0] > low[1] > 0
    assert high[0] > low[0] * 4
    assert high.sum() <= 1


# Increasing declared costs suppresses changes that cannot earn their execution expense.
def test_costs_discourage_turnover():
    current = np.array([0.05, 0.04])
    low = growth_weights([0.006, 0.003], np.diag([0.1, 0.1]), current, [0.25, 0.25], 0)
    high = growth_weights(
        [0.006, 0.003], np.diag([0.1, 0.1]), current, [0.25, 0.25], 0.0025
    )
    assert np.abs(high - current).sum() < np.abs(low - current).sum()
    np.testing.assert_allclose(high, current, atol=1e-5)


# Correlation penalizes redundant bets and cannot produce an indefinite risk matrix.
def test_correlation_changes_weights():
    corr = correlation(history())
    assert corr[0, 1] > corr[0, 2]
    assert np.linalg.eigvalsh(corr).min() >= -1e-10
    independent = growth_weights(
        [0.02, 0.02], np.diag([0.1, 0.1]), [0, 0], [0.25, 0.25], 0
    )
    redundant = growth_weights(
        [0.02, 0.02], np.array([[0.1, 0.09], [0.09, 0.1]]), [0, 0], [0.25, 0.25], 0
    )
    assert redundant.sum() < independent.sum()


# Positive waiting advantage postpones buys while negative advantage postpones sells.
def test_waiting_is_side_specific_and_cannot_overfund():
    current = np.array([0.25, 0.25, 0.0])
    forecasts = np.array([[-0.05, 0.1, -0.01], [0.005, 0.1, 0], [0.05, 0.1, 0]])
    target, detail = decide(forecasts, history(), current, np.ones(3, bool), 10)
    assert target[0] == current[0]
    assert detail["waiting"] >= 1
    assert 0 <= target.sum() <= 1
    forecasts[2, 2] = 0.01
    waited, _ = decide(forecasts, history(), current, np.ones(3, bool), 10)
    assert waited[2] == 0


# Preserve unknown holdings and prohibit additions to below-grade names.
def test_unknown_and_below_grade_holdings():
    current = np.array([0.1, 0, 0])
    forecasts = np.array([[0.02, 0.1, 0], [0.04, 0.1, 0], [0.03, 0.1, 0]])
    target, _ = decide(forecasts, history(), current, [False, False, True], 10)
    assert target[0] <= current[0] + 1e-9
    assert target[1] == 0
    forecasts[0] = np.nan
    frozen, detail = decide(forecasts, history(), current, [False, False, True], 10)
    np.testing.assert_array_equal(frozen, current)
    assert detail["status"] == "hold_missing_held_evidence"


# Inconsistent moment forecasts are counted and never converted to zero-risk bets.
def test_inconsistent_moments_are_explicit():
    forecasts = np.array([[0.1, -0.01, 0], [0.02, 0.1, 0], [0.03, 0.1, 0]])
    target, detail = decide(forecasts, history(), np.zeros(3), np.ones(3, bool), 10)
    assert detail["inconsistent_moments"] == 1
    assert np.isfinite(target).all()
    assert target.sum() <= 1


# Sales credit closing cash but cannot finance buys in any later batch that day.
def test_no_same_day_reinvestment_across_batches():
    panel = SimpleNamespace(tickers=("A", "B"))
    book = _Book(2, 0, 10, panel, None, None)
    book.shares[:] = [1, 0]
    budget, _, _ = funded_fill(book, np.array([0, 0]), np.array([10, 10]), 0, 0, "sell")
    assert book.cash == pytest.approx(9.99)
    assert budget == 0
    budget, dollars, _ = funded_fill(
        book, np.array([0, 1]), np.array([10, 10]), budget, 0, "buy"
    )
    assert book.shares[1] == 0
    assert dollars.sum() == 0
    assert budget == 0
    _, dollars, fees = funded_fill(
        book, np.array([0, 2]), np.array([10, 10]), book.cash, 1, "next_day"
    )
    assert 0 < book.shares[1] < 1
    assert fees == pytest.approx(np.abs(dollars).sum() * 0.001)
    assert book.cash >= 0


# Unpriced exits preserve the covered holding instead of inventing sale proceeds.
def test_missing_execution_does_not_liquidate():
    panel = SimpleNamespace(tickers=("A",))
    book = _Book(1, 1, 10, panel, None, None)
    book.shares[:] = 1
    _, dollars, fees = funded_fill(
        book, np.zeros(1), np.full(1, np.nan), 1, 0, "missing"
    )
    assert book.shares[0] == 1
    assert book.cash == 1
    assert dollars[0] == fees == 0


# Invalid covariance, cash weights and trading costs fail instead of appearing optimal.
def test_invalid_optimization_inputs_fail():
    with pytest.raises(ValueError, match="optimization inputs"):
        growth_weights([1], [[-1]], [0], [0.25], 0)
    with pytest.raises(ValueError, match="current funded"):
        decide(np.ones((3, 3)), history(), [1, 1, 0], np.ones(3, bool), 10)
    with pytest.raises(ValueError, match="optimization inputs"):
        growth_weights([1], [[1]], [0], [0.25], -1)


# Reported gain includes the first trading day and drawdown has the positive loss sign.
def test_score_uses_continuous_initial_nav():
    dates = np.array(["2026-08-14", "2026-08-17", "2026-08-18"], dtype="datetime64[D]")
    account = {
        "dates": dates,
        "nav": np.array([1, 1.1, 0.99]),
        "cash": np.zeros(3),
        "exposure": np.ones(3),
        "turnover": np.array([0, 1, 1]),
        "fees": np.zeros(3),
    }
    result = score(account, {}, np.ones(3))
    all_row = result["windows"][0]
    assert all_row["total_net_gain"] == pytest.approx(-0.01)
    assert all_row["max_drawdown_loss"] == pytest.approx(0.1)
    assert result["windows"][-1]["sessions"] == 2


# Full exposure to one asset reproduces its predicted log gain without double risk.
def test_log_moment_conversion_preserves_single_asset_growth():
    f = np.array([[0.03, 0.04, 0]])
    mean, cross, _ = growth_parameters(f, np.ones((1, 1)))
    assert mean[0] - 0.5 * cross[0, 0] == pytest.approx(f[0, 0])
    assert cross[0, 0] == pytest.approx(f[0, 1])
