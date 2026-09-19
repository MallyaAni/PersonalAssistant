"""The market gate: half the book while SPY is under its 50-day."""

import numpy as np

from backend.agents.trading.desk import market_gate, paper
from backend.tests.test_trading_simulate import _report

ROWS = 80


def _spy(close, level=100.0):
    out = close.copy()
    out[:, -1] = level
    return out


# SPY below its 50-day halves the exposure path from that session on.
def test_exposure_path_halves_when_spy_is_under_its_50_day():
    close = np.full((ROWS, 6), 100.0)
    close = _spy(close, 100.0)
    close[50:, -1] = 50.0  # SPY drops to 50 from session 50
    path = market_gate.exposure_path(_report(close).panel)
    assert np.all(path[:50] == 1.0)
    assert np.all(path[52:] == 0.5)


# The decision names the factor and the prices it was read from.
def test_decision_reports_the_gate_state():
    close = np.full((ROWS, 6), 100.0)
    above = market_gate.decision(_report(_spy(close, 100.0)).panel)
    assert above["factor"] == 1.0 and above["below"] is False
    close[50:, -1] = 50.0
    below = market_gate.decision(_report(close).panel)
    assert below["factor"] == 0.5 and below["below"] is True
    assert below["version"] == market_gate.VERSION


# A cut sells the same fraction of every holding, exactly, to cash.
def test_transition_cuts_exactly_half_to_cash():
    state = paper.PaperState(gate_factor=1.0, order_seq=0)
    orders = market_gate.transition_orders(
        "2026-09-18", state, {"MU": 100.0, "AMD": 200.0},
        {"MU": 200.0, "AMD": 100.0}, cash=0.0, desired=0.5,
    )
    by = {o.symbol: o for o in orders}
    assert by["MU"].side == "sell" and by["MU"].qty == 50
    assert by["AMD"].side == "sell" and by["AMD"].qty == 100
    assert all(o.reason.startswith("market gate") for o in orders)
    assert state.order_seq == 2


# A restore buys back the same fraction, capped by the cash on hand.
def test_transition_restore_is_cash_capped():
    state = paper.PaperState(gate_factor=0.5, order_seq=0)
    orders = market_gate.transition_orders(
        "2026-09-18", state, {"MU": 50.0}, {"MU": 200.0}, cash=5000.0, desired=1.0,
    )
    assert len(orders) == 1
    order = orders[0]
    assert order.side == "buy"
    # Full restore needs 50 shares * $202 (1% allowance) = $10,100 > $5,000.
    assert order.qty == int(5000 / (200 * 1.01))
    assert order.reason.startswith("market gate restored")


# No transition when the desired factor is unchanged.
def test_transition_is_a_noop_when_the_factor_is_unchanged():
    state = paper.PaperState(gate_factor=0.5)
    orders = market_gate.transition_orders(
        "2026-09-18", state, {"MU": 50.0}, {"MU": 200.0}, cash=0.0, desired=0.5,
    )
    assert orders == []
