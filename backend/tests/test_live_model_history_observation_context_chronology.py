"""Exercise reservation coverage and same-clock cash without a broker or sender."""

from datetime import timedelta

import pytest

from backend.market.live_model_history_observation_context import ObservationContext
from backend.tests.test_live_model_history_observation_context import (
    NOW,
    OPEN,
    attempt,
    context,
    records,
    row,
)


# Outstanding accepted sales reserve coverage even though positions still show shares.
def test_uncovered_sale_is_independently_derived():
    prior = attempt(side="sell", qty=3, at=OPEN - timedelta(days=1))
    prior["client_order_id"] = "another-original-sale"
    value = context(held={"AAA": 5}, accepted={prior["client_order_id"]: prior})
    rejected = attempt(side="sell", accepted=False, reason="uncovered_sell")
    value.admit(row("sell"), rejected)
    assert value.result(row("sell"))["reason"] == "uncovered_sell"
    assert "funded-five" not in value.requests


# Sale proceeds from this decision's later flush cannot fund its purchase request.
def test_same_clock_sale_cash_is_unavailable_until_the_next_observation():
    prior = attempt(side="sell", at=OPEN - timedelta(days=1))
    prior["client_order_id"] = "prior-sale"
    fill = {
        "client_order_id": "prior-sale",
        "symbol": "AAA",
        "side": "sell",
        "filled_qty": 5,
        "price": 100,
        "fee": 0.5,
        "at": NOW.isoformat(),
    }
    value = ObservationContext(
        cash=100,
        held={"AAA": 5},
        basis={"AAA": 100},
        dividends=[],
        records=records(),
        accepted={"prior-sale": prior},
        outcomes={},
        cancellations={},
        fills=[fill],
        opening=OPEN,
    )
    buy = {**row(), "symbol": "BBB"}
    value.advance(NOW, {"AAA": 100, "BBB": 100})
    assert value.result(buy)["reason"] == "insufficient_reserved_cash"
    assert value.result(buy)["available_cash"] == 100
    value.advance(NOW + timedelta(minutes=15), {"AAA": 100, "BBB": 100})
    assert value.result(buy)["reason"] is None
    assert value.result(buy)["available_cash"] == 599.5
    assert value.held == {}


# Native request identity and time cannot be supplied by a different accepted receipt.
@pytest.mark.parametrize("field", ["client_order_id", "symbol", "side", "at"])
def test_request_identity_and_clock_are_exact(field):
    receipt = attempt()
    receipt[field] = {
        "client_order_id": "another-request",
        "symbol": "BBB",
        "side": "sell",
        "at": (NOW + timedelta(minutes=15)).isoformat(),
    }[field]
    with pytest.raises(ValueError, match="identity or clock"):
        context().admit(row(), receipt)
