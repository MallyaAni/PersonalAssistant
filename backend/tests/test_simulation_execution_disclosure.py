"""Published daily simulations must not inherit the live executor's identity."""

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper, simulate
from backend.cli import market_daily
from backend.tests.test_market_daily import _report


# Check curve identity independently of current and future planner versions.
@pytest.mark.parametrize("planner_version", [paper.POLICY_VERSION, "future-paper/99"])
def test_daily_curve_names_its_actual_model_not_the_live_executor(
    monkeypatch, planner_version
):
    monkeypatch.setattr(paper, "POLICY_VERSION", planner_version)
    report = _report()
    result = simulate.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 0.1]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    monkeypatch.setattr(simulate, "run", lambda report, **kwargs: result)
    curve = market_daily.curve_block(report, None)
    assert curve["execution_policy"] == "daily-open-close/1"
    assert curve["live_execution_policy"] == paper.POLICY_VERSION
    assert curve["live_execution_timing"] == intraday_orders.INTRADAY_TIMING
    assert curve["execution_matches_live"] is False
    assert "next-open buys" in curve["execution_note"]
    assert "green-open sell suppression" in curve["execution_note"]
    assert "live executor" not in curve["point_in_time_label"]
    np.testing.assert_allclose(curve["rules"], [0.0, 0.05, 0.1])
