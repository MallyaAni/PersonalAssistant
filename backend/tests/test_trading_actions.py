"""The action board.

What has to hold: the action follows from the target and the holding;
the grade margin says how far a name sits above the line that keeps its
grade; and a board lists sells and trims before buys and adds, carries
sizes as weights of equity, the rebalance clock, and stop levels off the
twenty-session high.
"""

import numpy as np

from backend.agents.trading.desk import actions, grading
from backend.tests.test_trading_simulate import _report


# Target against holding gives the action; a change under half a percent
# of equity is a hold, not an order.
def test_action_follows_target_and_holding():
    assert actions.action_for(0.10, 0.0) == "buy"
    assert actions.action_for(0.0, 0.10) == "sell"
    assert actions.action_for(0.12, 0.10) == "add"
    assert actions.action_for(0.08, 0.10) == "trim"
    assert actions.action_for(0.102, 0.10) == "hold"
    assert actions.action_for(0.0, 0.0) == "hold"


# The margin is the votes above the grade's own threshold.
def test_grade_margin_is_measured_from_the_grades_threshold():
    assert actions.grade_margin(2.5, grading.A_PLUS, True) == 0.5
    assert actions.grade_margin(2.5, grading.A, False) == 0.5
    assert np.isclose(
        actions.grade_margin(1.2, grading.A, True), 0.2
    )  # bullish release
    assert np.isclose(actions.grade_margin(0.6, grading.B, False), 0.1)
    assert actions.grade_margin(0.0, grading.C, False) == -0.5


# The board: most urgent first, sizes as weights, the clock and the stops.
def test_board_orders_rows_and_carries_the_exit_plan():
    report = _report()
    panel = report.panel
    targets = {"N0": 0.15, "N1": 0.10}
    holdings = {
        "N1": actions.Holding(weight=0.10, entry_price=50.0),
        "N2": actions.Holding(weight=0.08, entry_price=40.0),
    }
    rows = actions.build(report, targets, holdings, sessions_since_rebalance=5)
    by = {r["ticker"]: r for r in rows}
    assert [r["action"] for r in rows] == ["sell", "buy", "hold"]
    assert (
        by["N2"]["action"] == "sell"
        and by["N2"]["leaves_if"] == "already outside the book"
    )
    assert by["N0"]["action"] == "buy" and by["N0"]["delta_weight"] == 0.15
    assert by["N1"]["action"] == "hold" and by["N1"]["entry_price"] == 50.0
    for r in rows:
        assert set(r["stances"]) == set(report.graded.stances)
        assert "reason" in r and "why" in r
        assert r["until_rebalance"] == 15
        assert r["entry"] == "market-on-open"
        assert r["rank"] is not None and r["grade"] in ("A+", "A", "B", "C")
    last = len(panel.dates) - 1
    col = panel.index("N0")
    high = float(np.nanmax(panel.high[last - 19 : last + 1, col]))
    assert np.isclose(by["N0"]["high_20"], high)
    assert np.isclose(by["N0"]["stops"]["12"], high * 0.88)
    assert set(by["N0"]["stops"]) == {"8", "12", "20"}
