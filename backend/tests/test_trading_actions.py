"""The action board.

What has to hold: the action follows from the target and the holding;
the grade margin says how far a name sits above the line that keeps its
grade; and a board lists sells and trims before buys and adds, carries
sizes as weights of equity, the rebalance clock, and stop levels off the
twenty-session high.
"""

import numpy as np

from backend.agents.trading.desk import actions, grading, paper
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


# A held name with no target is sold only when the paper book would sell
# it: on a grade below A, or when the plan itself wrote the exit. Still
# graded A or better and with no order against it, nothing trades until
# the reset, so the board says hold rather than sell.
def test_a_held_a_name_with_no_target_is_a_hold_not_a_sell():
    assert actions.action_for(0.0, 0.10, grade=grading.A) == "hold"
    assert actions.action_for(0.0, 0.10, grade=grading.A_PLUS) == "hold"
    assert actions.action_for(0.0, 0.10, grade=grading.B) == "sell"
    assert actions.action_for(0.0, 0.10, grade=grading.C) == "sell"
    # The plan's own sell order is an explicit exit whatever the grade.
    assert actions.action_for(0.0, 0.10, grade=grading.A, exiting=True) == "sell"
    # Without a grade the old reading stands.
    assert actions.action_for(0.0, 0.10) == "sell"
    # A held name that keeps a target is unaffected by the grade.
    assert actions.action_for(0.08, 0.10, grade=grading.A) == "trim"


# The board applies the same rule from the report's grades and the plan's
# orders: N1 is an A the book still holds with no target and no order, so
# it is a hold that leaves at the reset; give the plan a sell order for it
# and it is a sell.
def test_the_board_holds_an_a_name_the_book_has_not_sold():
    report = _report()  # N0 is A+, N1 is A, N2 is B
    holdings = {
        "N1": actions.Holding(weight=0.10, entry_price=50.0),
        "N2": actions.Holding(weight=0.08, entry_price=40.0),
    }
    rows = actions.build(report, {"N0": 0.15}, holdings, sessions_since_rebalance=5)
    by = {r["ticker"]: r for r in rows}
    assert by["N1"]["action"] == "hold"
    assert by["N1"]["leaves_if"] == (
        "the next rebalance, or the grade falls below A first"
    )
    assert by["N2"]["action"] == "sell"
    assert [r["action"] for r in rows] == ["sell", "buy", "hold"]
    planned = actions.build(
        report,
        {"N0": 0.15},
        holdings,
        sessions_since_rebalance=5,
        reasons={"N1": "leaves the book"},
    )
    assert {r["ticker"]: r["action"] for r in planned}["N1"] == "sell"


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
    # The rotation sells a downgrade the session it happens, not at the
    # next reset, and the row says so.
    assert by["N0"]["leaves_if"] == "the grade falls below A"
    assert by["N1"]["action"] == "hold" and by["N1"]["entry_price"] == 50.0
    for r in rows:
        assert set(r["stances"]) == set(report.graded.stances)
        assert "reason" in r and "why" in r
        # Against the book's own constant, not a copy of it. This asserted a
        # literal 15, which was `actions.REBALANCE` at 20 minus the fixture's
        # five sessions - and it went on passing after the book moved to a
        # 120-session reset, while the page told the operator his weights
        # reset in 14 sessions when the answer was 114.
        assert r["until_rebalance"] == paper.REBALANCE_EVERY - 5
        assert r["entry"] == "market-on-open"
        assert r["rank"] is not None and r["grade"] in ("A+", "A", "B", "C")
    last = len(panel.dates) - 1
    col = panel.index("N0")
    high = float(np.nanmax(panel.high[last - 19 : last + 1, col]))
    assert np.isclose(by["N0"]["high_20"], high)
    assert np.isclose(by["N0"]["stops"]["12"], high * 0.88)
    assert set(by["N0"]["stops"]) == {"8", "12", "20"}
