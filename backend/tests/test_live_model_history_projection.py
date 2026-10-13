"""Current-model charts preserve amounts and refuse invented or altered fills."""

from copy import deepcopy

import pytest

from backend.market.grade_led_policy import POLICY
from backend.market.live_model_history_projection import fills, nightly


# Build one grade-led night with an add, partial trim and unfunded entry signal.
def example():
    rows = []
    for name, action, qty, signal, holding in (
        ("AAA", "add", 5, "hold", 10),
        ("BBB", "trim", 3, "hold", 7),
        ("CCC", "hold", 0, "buy", 0),
        ("DDD", "hold", 0, "sell", 0),
    ):
        rows.append(
            {
                "ticker": name,
                "policy": POLICY,
                "is_fill": False,
                "order_quantity": qty,
                "action": action,
                "grade_signal": signal,
                "grade": "B" if name == "DDD" else "A+",
                "previous_grade": "A+",
                "target_weight": 0.1 if holding else 0,
                "model_target_weight": 0.15 if qty else 0,
                "signal_reason": "Learned size is zero"
                if name == "CCC"
                else "No shares held; no sell order needed"
                if name == "DDD"
                else "Learned funded size",
                "signal_status": "planned"
                if qty
                else "no_position"
                if name == "DDD"
                else "blocked",
                "action_status": "planned" if qty else "no_new_order",
            }
        )
    intents = [
        {
            "symbol": row["ticker"],
            "qty": row["order_quantity"],
            "session": "2021-01-04",
            "client_order_id": row["ticker"] + "-id",
            "execute_on": "2021-01-05",
            "execution_timing": "intraday",
        }
        for row in rows
        if row["order_quantity"]
    ]
    value = {
        "nightly": {
            "session": "2021-01-04",
            "at": "2021-01-04T16:01:00-05:00",
            "status": "planned",
            "entry": {"actions": rows},
        },
        "new_intents": intents,
        "broker": {"holdings": {"AAA": 10, "BBB": 7}},
    }
    stocks = {
        name: {"decisions": [], "targets": [], "trades": []}
        for name in ("AAA", "BBB", "CCC", "DDD")
    }
    return value, stocks


# An unchanged A+ grade still exposes learned adds/trims and genuine zero sizes.
def test_historical_decisions_keep_funded_shares_and_zero_reasons():
    value, stocks = example()
    decisions = {}
    nightly(value, stocks, decisions)
    assert [
        (row["action"], row["qty"])
        for stock in stocks.values()
        for row in stock["decisions"]
    ] == [("ADD", 5), ("TRIM", 3), ("BUY", 0), ("SELL", 0)]
    assert stocks["CCC"]["decisions"][0]["reason"] == "Learned size is zero"
    assert stocks["DDD"]["decisions"][0]["status"] == "no_position"
    assert stocks["AAA"]["decisions"][0]["model_target_weight"] == 0.15
    assert stocks["AAA"]["decisions"][0]["target_weight"] == 0.1
    assert all(not stock["trades"] for stock in stocks.values())


# An excluded name stays explicitly unavailable instead of inheriting a past size.
def test_historical_projection_preserves_missing_stock_plan():
    value, stocks = example()
    value["nightly"]["entry"]["actions"] = value["nightly"]["entry"]["actions"][:1]
    nightly(value, stocks, {})
    for name in ("BBB", "CCC", "DDD"):
        assert stocks[name]["targets"][-1]["date"] == "2021-01-04"
        assert stocks[name]["targets"][-1]["weight"] is None
        assert stocks[name]["targets"][-1]["status"] == "not_covered_by_plan"
        assert stocks[name]["decisions"] == []


# Historical chart receipts reject quantity drift and preserve partial simulated fills.
def test_historical_execution_matches_original_decision_size_and_clock():
    value, stocks = example()
    decisions = {}
    nightly(value, stocks, decisions)
    fill = {
        "client_order_id": "AAA-id",
        "symbol": "AAA",
        "side": "buy",
        "filled_qty": 2,
        "at": "2021-01-05T10:00:00-05:00",
        "price": 100,
        "fee": 0.2,
    }
    fills([fill], stocks, decisions)
    assert decisions["AAA-id"]["executed_qty"] == 2
    assert decisions["AAA-id"]["state"] == "partial"
    assert stocks["AAA"]["trades"][0]["decision_date"] == "2021-01-04"
    assert stocks["AAA"]["trades"][0]["date"] == "2021-01-05"
    for change, message in (
        ({"filled_qty": 4}, "exceeds"),
        ({"side": "sell"}, "side"),
        ({"at": value["nightly"]["at"]}, "timing"),
        ({"client_order_id": "made-up"}, "no original"),
    ):
        with pytest.raises(ValueError, match=message):
            fills([{**fill, **change}], deepcopy(stocks), deepcopy(decisions))
    value["new_intents"][0]["qty"] = 6
    with pytest.raises(ValueError, match="durable intent"):
        nightly(value, deepcopy(stocks), {})
