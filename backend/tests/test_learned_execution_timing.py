"""Behavioral acceptance for stock-specific execution risk and funded timing."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.learned_execution_timing import HORIZON, account, decision


# Opposite price forecasts must reverse the trade side's waiting preference.
@pytest.mark.parametrize(
    ("side", "mean", "state"),
    [
        ("buy", 0.001, "wait"),
        ("sell", 0.001, "execute"),
        ("buy", -0.001, "execute"),
        ("sell", -0.001, "wait"),
        ("buy", 0, "execute"),
        ("sell", 0, "execute"),
    ],
)
def test_side_and_tie(side, mean, state):
    chosen = decision(mean, mean * mean, side, 0.1, 10, horizon=HORIZON)
    assert chosen.state == state


# High conditional waiting risk can favor execution without any percentage trigger.
def test_stock_risk_changes_same_mean_decision():
    low = decision(0.001, 0.000001, "buy", 0.2, 0, horizon=HORIZON)
    high = decision(0.001, 0.003, "buy", 0.2, 0, horizon=HORIZON)
    assert low.state == "wait"
    assert high.state == "execute"
    assert high.variance > low.variance


# A larger funded order must pay more attention to the same uncertain price advantage.
def test_order_notional_changes_risk_tradeoff():
    small = decision(0.001, 0.0015, "buy", 0.1, 0, horizon=HORIZON)
    large = decision(0.001, 0.0015, "buy", 0.8, 0, horizon=HORIZON)
    assert small.state == "wait"
    assert large.state == "execute"


# Refuse missing or contradictory moments rather than inventing risk-free trades.
@pytest.mark.parametrize(
    ("mean", "second"), [(np.nan, 0), (0, np.inf), (0, -1), (0.1, 0.001), (True, 1)]
)
def test_unavailable_moments(mean, second):
    assert (
        decision(mean, second, "buy", 0.1, 10, horizon=HORIZON).state == "unavailable"
    )


# Long holding-period variance must never be silently used as execution risk.
def test_wrong_horizon_and_unfunded_trade():
    with pytest.raises(ValueError, match="horizon"):
        decision(0.001, 0.0001, "buy", 0.1, 10, horizon="ten_sessions")
    assert decision(0, 0, "buy", 0, 10, horizon=HORIZON).state == "no_trade"
    assert decision(0, 0, "buy", 1.1, 10, horizon=HORIZON).state == "unavailable"


# Supply an ordinary stock and benchmarks on a complete synthetic causal timeline.
def sample(days=2, stocks=("STOCK", "SPY", "QQQ")):
    dates = np.datetime64("2026-08-01") + np.arange(days).astype("timedelta64[D]")
    prices = np.full((days, len(stocks)), 10.0)
    panel = SimpleNamespace(dates=dates, tickers=stocks, adj_close=prices)
    grades = np.full(prices.shape, 3)
    eligible = np.ones(prices.shape, dtype=bool)
    eligible[:, -2:] = False
    shape = (days, 25, len(stocks))
    dataset = {
        "dates": dates,
        "current_close": np.full(shape, 10.0),
        "next_open": np.full(shape, 10.0),
    }
    forecasts = np.zeros((*shape, 3))
    risk = np.zeros(shape)
    return panel, grades, eligible, dataset, forecasts, risk, prices.copy()


# Execute a favorable first decision once and reconcile the funded stock wealth.
def test_completed_intent_does_not_fill_twice():
    args = sample()
    result = account(*args, first=1, cost_bps=10, offset=0)
    assert result["counts"]["intents"] == 1
    assert result["counts"]["completed_intents"] == 1
    assert result["counts"]["fills"] == 1
    assert result["counts"]["closing_fills"] == 0
    assert result["cash"][-1] == pytest.approx(0.74975)
    assert result["nav"][-1] == pytest.approx(0.99975)
    assert sum(
        x["net_gain_initial_nav_units"] for x in result["stocks"].values()
    ) == pytest.approx(-0.00025)


# Two stocks can execute on different bars from different forecasts under one plan.
def test_per_stock_forecasts_and_completed_bar_execution():
    args = sample(stocks=("NOW", "LATER", "SPY", "QQQ"))
    args[4][:, :, 1, 2] = 0.001
    args[5][:, :, 1] = 0.000001
    args[4][1, 3, 1, 2] = -0.001
    args[3]["next_open"][1, :, 0] = 12
    args[3]["next_open"][1, :, 1] = 8
    # Decision bars' closes cannot retrospectively become executable fill prices.
    args[3]["current_close"][1, :, 0] = 11
    result = account(*args, first=1, cost_bps=0, offset=0)
    assert result["counts"]["fills"] == 2
    assert result["counts"]["waiting_decisions"] == 3
    assert result["stocks"]["NOW"]["net_gain_initial_nav_units"] == pytest.approx(-0.05)
    assert result["stocks"]["LATER"]["net_gain_initial_nav_units"] == pytest.approx(
        0.05
    )


# Count unavailable execution attempts without selecting a future best price.
def test_missing_execution_and_deadline_are_explicit():
    args = sample()
    args[3]["next_open"][1, 0, 0] = np.nan
    result = account(*args, first=1, cost_bps=0, offset=0)
    assert result["counts"]["missing_execution"] == 1
    assert result["counts"]["fills"] == 0
    assert result["counts"]["expired_unfilled"] == 1
    args[4][1, :, 0, 2] = 0.001
    args[5][1, :, 0] = 0.000001
    args[6][1, 0] = np.nan
    result = account(*args, first=1, cost_bps=0, offset=0)
    assert result["counts"]["expired_unfilled"] == 1
    assert result["counts"]["completed_intents"] == 0
    assert result["counts"]["waiting_decisions"] == 23
    assert result["counts"]["missing_execution"] == 1
    assert result["nav"][-1] == 1


# Even lower later prices cannot let same-day sales finance the replacement stock.
def test_sales_cannot_finance_same_day_replacement():
    args = sample(days=22, stocks=("OLD", "NEW", "SPY", "QQQ"))
    args[2][:, 1] = False
    args[2][20, 0] = False
    args[2][20, 1] = True
    # The first stock consumes the entire account's cash when its execution price gaps.
    args[3]["next_open"][1, :, 0] = 40
    result = account(*args, first=1, cost_bps=0, offset=0)
    assert result["stocks"]["OLD"]["fills"] == 2
    assert result["stocks"]["NEW"]["fills"] == 0
    assert result["counts"]["expired_unfilled"] >= 1
    assert (result["cash"] >= 0).all()


# Partial funding consumes one locked attempt and cannot create repeat or auction fills.
def test_partial_funded_intent_expires_without_later_retry():
    args = sample()
    args[3]["next_open"][1, 0, 0] = 100
    args[3]["next_open"][1, 1:, 0] = 1
    result = account(*args, first=1, cost_bps=0, offset=0)
    counts = result["counts"]
    assert counts["intents"] == counts["expired_partial"] == counts["fills"] == 1
    assert counts["completed_intents"] == counts["expired_unfilled"] == 0
    assert counts["closing_fills"] == 0
    assert result["cash"][-1] == 0
    assert result["nav"][-1] == pytest.approx(0.1)
