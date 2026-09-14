"""The growth objective cannot silently revert to Sharpe optimization."""

import math

import pytest

from backend.market import growth_objective


# Higher final wealth wins despite a worse intermediate drawdown.
def test_objective_maximizes_terminal_wealth_not_sharpe():
    steady = growth_objective.evaluate([100, 105, 110])
    volatile = growth_objective.evaluate([100, 80, 130])
    assert volatile["log_growth"] > steady["log_growth"]
    assert volatile["drawdown"] == pytest.approx(-0.2)
    assert steady["drawdown"] == 0
    assert math.expm1(volatile["log_growth"]) == pytest.approx(0.3)


# Holding cash gives zero and execution costs already in NAV lower the objective.
def test_cash_and_execution_costs_are_not_double_counted():
    assert growth_objective.evaluate([100, 100])["log_growth"] == 0
    actual = growth_objective.evaluate([100, 99, 109])
    assert actual["total_return"] == pytest.approx(0.09)
    assert math.expm1(actual["log_growth"]) == pytest.approx(0.09)
    with pytest.raises(ValueError, match="Positive finite"):
        growth_objective.evaluate([100, float("nan")])
