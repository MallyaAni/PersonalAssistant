"""Actual-clock CDF timing through the real private persisted paper sender."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import forward_probability_timing as forward
from backend.market import live_probability_timing as historical
from backend.market.probabilistic_execution import Distribution
from backend.tests.test_live_probability_timing import (
    NOW,
    SESSION,
    SYMBOLS,
    broker,
    intent,
)

DECISION = NOW + timedelta(seconds=5)
SOURCE = {key: "a" * 64 for key in ("model_receipt", "residual_receipt", "observation")}


# Supply independently published raw quotes and the original next-bar opening.
def snapshot(price=10):
    return {
        "quotes": {
            symbol: {
                "bid": price - 0.005,
                "ask": price + 0.005,
                "bid_size": 100,
                "ask_size": 100,
                "last": price,
                "open": 10,
                "bar": (NOW - timedelta(minutes=15)).isoformat(),
                "as_of": (DECISION - timedelta(seconds=1)).isoformat(),
                "received_at": DECISION.isoformat(),
                "feed": "iex",
                "basis": "raw_current_shares",
                "next_open": 10,
                "next_open_at": NOW.isoformat(),
                "next_open_published_at": (NOW + timedelta(seconds=1)).isoformat(),
            }
            for symbol in ("AAA", "BBB")
        }
    }


# Supply positive-risk empirical forecasts without acquiring market data or orders.
def forecasts(mean=-0.01):
    return {
        symbol: Distribution(mean, 0.0001, np.array([-1.0, 1.0]), np.array([1.0, 1.0]))
        if symbol in ("AAA", "BBB")
        else None
        for symbol in SYMBOLS
    }


# Run actual sender persistence with quote, forecast and account clocks kept separate.
def send(root, rows=None, *, mean=-0.01, quotes=None, client=None, captured=None):
    client = client or broker(now=DECISION - timedelta(seconds=1))
    account = captured or forward.capture_account(client, NOW, clock=lambda: DECISION)
    client.observe(DECISION, {"AAA": 10, "BBB": 10}, True)
    state = paper.PaperState()
    state.pending = deepcopy(rows or [intent()])
    for row in state.pending:
        row["timing_policy"] = historical.POLICY
    paper.save_state(root, state)
    quotes, trace = quotes or snapshot(), []
    reader = forward.build_reader(
        forecasts(mean),
        SYMBOLS,
        0,
        SESSION,
        DECISION,
        quotes,
        state.pending,
        account,
        10,
        trace,
        forecast_available_at=NOW + timedelta(seconds=2),
        source_identity=SOURCE,
    )
    lines = intraday_orders.send_due(
        root, quotes, DECISION, lambda: client, timing_reader=reader
    )
    return trace, paper.load_state(root), client, lines


# The actual acknowledgment retains the delayed receipt without claiming an execution.
def test_delayed_buy_persists_receipt_without_one_percent_gate(tmp_path):
    trace, state, client, lines = send(tmp_path)
    assert len(lines) == 1
    evidence = state.pending[0]["sent"]["forward_timing"]
    assert evidence["receipt_sha256"] == trace[0]["forward_receipt_sha256"]
    assert evidence["receipt"]["completed_at"] == NOW.isoformat()
    assert (
        evidence["receipt"]["forecast_available_at"]
        == (NOW + timedelta(seconds=2)).isoformat()
    )
    assert evidence["receipt"]["decided_at"] == DECISION.isoformat()
    assert evidence["receipt"]["midpoint_fill_proven"] is False
    assert evidence["trade_fraction"] == 0.05
    assert state.pending[0]["sent"]["qty"] == 5
    assert client.ledger()["holdings"] == {}


# Known price movement transports the opening target with opposite buy/sell directions.
@pytest.mark.parametrize(
    ("side", "price", "expected"),
    [
        ("buy", 10, "execute"),
        ("sell", 10, "wait"),
        ("buy", 10.3, "wait"),
        ("sell", 10.3, "execute"),
    ],
)
def test_observed_price_transport(tmp_path, side, price, expected):
    trace, state, _, _ = send(
        tmp_path,
        [intent(side=side)],
        quotes=snapshot(price),
        client=broker(holdings={"AAA": 10}, now=DECISION),
    )
    assert trace[0]["state"] == expected
    assert bool(state.pending[0].get("sent")) == (expected == "execute")


# Defective evidence remains unavailable instead of falling back to fixed-price timing.
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("as_of", (DECISION + timedelta(seconds=1)).isoformat()),
        ("received_at", (DECISION + timedelta(seconds=1)).isoformat()),
        ("next_open_published_at", (DECISION + timedelta(seconds=1)).isoformat()),
        ("next_open_at", DECISION.isoformat()),
        ("next_open", None),
        ("as_of", (NOW - timedelta(seconds=1)).isoformat()),
        ("basis", "adjusted"),
        ("bid", 9),
        ("last", 10.1),
    ],
)
def test_invalid_evidence_blocks_actual_sender(tmp_path, key, value):
    quotes = snapshot()
    quotes["quotes"]["AAA"][key] = value
    trace, state, client, lines = send(tmp_path, quotes=quotes)
    assert trace[0]["state"] == "unavailable"
    assert not state.pending[0].get("sent")
    assert client.attempt_history == () and lines == []


# No cash cannot be replaced by the hoped-for proceeds of a held position.
def test_zero_cash_preserves_pending(tmp_path):
    trace, state, client, _ = send(
        tmp_path, client=broker(0, holdings={"AAA": 10}, now=DECISION)
    )
    assert trace[0]["state"] == "no_trade"
    assert trace[0]["buying_power_budget"] == 0
    assert not state.pending[0].get("sent") and client.ledger()["cash"] == 0


# Different current feed marks do not permit selling more shares than actually held.
def test_independent_marks_and_covered_sell(tmp_path):
    trace, state, _, _ = send(
        tmp_path,
        [intent(side="sell")],
        mean=0.01,
        client=broker(holdings={"AAA": 3}, now=DECISION),
        quotes=snapshot(10.01),
    )
    assert trace[0]["observed_qty"] == 3
    assert state.pending[0]["sent"]["qty"] == 3


# Concurrent funds, shares or impossible source clocks fail the actual GET boundary.
@pytest.mark.parametrize("field", ["cash", "shares", "future_clock"])
def test_concurrent_account_change_is_unavailable(field):
    client = broker(now=DECISION)
    account, positions, source_clock, calls = (
        client.account,
        client.positions,
        client.clock,
        [0],
    )

    # Alter only the second real account response to reproduce changing funds.
    def changed():
        calls[0] += 1
        value = account()
        return (
            replace(value, cash=value.cash + 1)
            if calls[0] == 2 and field == "cash"
            else value
        )

    # Reproduce a held-share change without changing either account valuation.
    def changed_positions():
        values = positions()
        if field == "shares" and calls[0] == 2:
            values = [
                type("Position", (), {"symbol": "AAA", "qty": 1, "current_price": 10})()
            ]
        return values

    # Reproduce a source clock that was not yet known when its response was captured.
    def changed_clock():
        value = source_clock()
        if field == "future_clock":
            value["timestamp"] = (DECISION + timedelta(seconds=1)).isoformat()
        return value

    client.account, client.positions, client.clock = (
        changed,
        changed_positions,
        changed_clock,
    )
    result = forward.capture_account(client, NOW, clock=lambda: DECISION)
    assert result["receipt"]["reason"] and result["receipt"]["budget"] is None


# Receipt tampering cannot manufacture funds while retaining the captured identity.
def test_changed_receipt_rejected(tmp_path):
    captured = forward.capture_account(
        broker(now=DECISION), NOW, clock=lambda: DECISION
    )
    captured["receipt"]["budget"] += 1000
    with pytest.raises(ValueError, match="account receipt"):
        send(tmp_path, captured=captured)


# The original client identity prevents another submission on a repeated observation.
def test_repeated_sender_does_not_submit_twice(tmp_path):
    _, state, client, _ = send(tmp_path)
    captured = forward.capture_account(client, NOW, clock=lambda: DECISION)
    reader = forward.build_reader(
        forecasts(),
        SYMBOLS,
        0,
        SESSION,
        DECISION,
        snapshot(),
        state.pending,
        captured,
        10,
        [],
        forecast_available_at=NOW + timedelta(seconds=2),
        source_identity=SOURCE,
    )
    before = client.attempt_history
    assert (
        intraday_orders.send_due(
            tmp_path, snapshot(), DECISION, lambda: client, timing_reader=reader
        )
        == []
    )
    assert client.attempt_history == before


# Actual publication cannot precede the prefix, arrive in the future or expire.
@pytest.mark.parametrize(
    ("available", "decision"),
    [
        (NOW - timedelta(seconds=1), DECISION),
        (DECISION + timedelta(seconds=1), DECISION),
        (DECISION, NOW + timedelta(minutes=15)),
    ],
)
def test_impossible_or_expired_forecast_publication_rejected(available, decision):
    captured = forward.capture_account(
        broker(now=DECISION), NOW, clock=lambda: DECISION
    )
    with pytest.raises(ValueError, match="forecast publication"):
        forward.build_reader(
            forecasts(),
            SYMBOLS,
            0,
            SESSION,
            decision,
            snapshot(),
            [intent()],
            captured,
            10,
            [],
            forecast_available_at=available,
            source_identity=SOURCE,
        )


# Missing stock risk remains unavailable rather than inventing a tiny variance.
def test_missing_distribution_keeps_actual_order_pending(tmp_path):
    client = broker(now=DECISION)
    captured = forward.capture_account(client, NOW, clock=lambda: DECISION)
    supplied = forecasts()
    supplied["AAA"] = None
    state = paper.PaperState()
    state.pending = [intent()]
    state.pending[0]["timing_policy"] = historical.POLICY
    paper.save_state(tmp_path, state)
    trace = []
    reader = forward.build_reader(
        supplied,
        SYMBOLS,
        0,
        SESSION,
        DECISION,
        snapshot(),
        state.pending,
        captured,
        10,
        trace,
        forecast_available_at=DECISION,
        source_identity=SOURCE,
    )
    assert (
        intraday_orders.send_due(
            tmp_path, snapshot(), DECISION, lambda: client, timing_reader=reader
        )
        == []
    )
    assert trace[0]["state"] == "unavailable"
    assert not paper.load_state(tmp_path).pending[0].get("sent")
    assert client.attempt_history == ()


# The original historical reader still rejects observations after its exact boundary.
def test_historical_contract_unchanged():
    with pytest.raises(ValueError, match="exact current completed"):
        historical.build_reader(
            None,
            SYMBOLS,
            0,
            0,
            SESSION,
            DECISION,
            snapshot(),
            [intent()],
            broker(now=DECISION),
            10,
            [],
        )
