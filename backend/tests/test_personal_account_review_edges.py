"""Keep personal funding requirements out of the explicit paper-target path."""

import pytest

from backend.agents.trading.desk import paper
from backend.market import decision_view
from backend.market.holdings import Holding
from backend.tests.test_decision_view import setup


# The explicit-target research paper path is funded by its own later account layer.
def test_explicit_paper_targets_do_not_inherit_personal_unknown_cash_gate():
    record, snapshot, quoted, now = setup()
    targets = {symbol: 0.1 if symbol == "S11" else 0 for symbol in record["grades"]}
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        targets=targets,
        entries={"S11": 1.5},
    )["rows"]["S11"]
    assert row["action"] == "Buy"
    assert row["move_weight"] > 0
    assert "available cash is unknown" not in row["reason"]


# A buy the basket cannot fund must never retain its pre-allocation action.
def test_entry_below_minimum_remaining_cap_is_not_executable():
    record, snapshot, quoted, now = setup()
    price = snapshot["quotes"]["S11"]["last"]
    weight = paper.ENTRY_NAME_CAP - paper.MIN_TRADE / 2
    held = [Holding("S11", weight * 100000 / price, price, "2026-08-01")]
    row = decision_view.build(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000,
    )["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0
    assert row["executable"] is False
    assert row["blocker"]


# Account validation must block the proposal rather than leave unsized opinions.
def test_invalid_held_price_cannot_bypass_account_cash_bound():
    record, snapshot, quoted, now = setup()
    snapshot["quotes"]["S10"]["last"] = float("nan")
    held = [Holding("S10", 5.0, 100.0, "2026-08-01")]
    row = decision_view.build(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000,
    )["rows"]["S11"]
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0
    assert row["executable"] is False
    assert "account" in row["blocker"]


# A valid execution quote cannot make an invalid sizing price into a funded buy.
@pytest.mark.parametrize("price", [float("nan"), float("inf"), -100.0])
def test_invalid_sizing_price_cannot_produce_a_buy(price):
    record, snapshot, quoted, now = setup()
    snapshot["quotes"]["S11"]["last"] = price
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000,
    )["rows"]["S11"]
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0
    assert row["executable"] is False
    assert row["blocker"]
