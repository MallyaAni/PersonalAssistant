"""Funded reductions keep their timing and cannot be cancelled by legacy policy."""

from datetime import UTC, datetime

import pytest

from backend.agents.trading.desk import paper
from backend.cli import market_balancer, market_daily
from backend.market import alpaca_trading


class Broker:
    # Keep a local queue so tests inspect what the broker would actually retain.
    def __init__(self):
        self.queued = []
        self.cancelled = []

    # Establish the existing safe overnight submission window.
    def clock(self):
        return {"is_open": False}

    # Retain the exact opening-auction instruction.
    def submit_market_on_open(self, symbol, qty, side, order_id):
        self.queued.append(("open", symbol, qty, side, order_id))

    # Retain the exact closing-auction instruction.
    def submit_market_on_close(self, symbol, qty, side, order_id):
        self.queued.append(("close", symbol, qty, side, order_id))

    # Confirm requested cancellations in this entirely local test broker.
    def cancel_orders(self, ids):
        self.cancelled.extend(ids)
        return {order_id: "cancelled" for order_id in ids}


# A risk label must affect dispatch, not merely appear in display metadata.
def test_risk_reduction_dispatches_at_next_open():
    broker = Broker()
    order = paper.PaperOrder("AAA", "sell", 10, "risk reduction", priority="event cap")
    submitted, refused = market_daily._submit(broker, [order], "2026-09-10", live=True)
    assert not refused
    assert len(submitted) == 1
    assert broker.queued[0][:4] == ("open", "AAA", 10, "sell")


class OpeningTime(datetime):
    # Exercise the actual green-day cancellation window on a trading day.
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 11, 14, 30, tzinfo=UTC)


# Reload persisted state after a green open; the mandatory reduction must survive.
@pytest.mark.parametrize(
    "metadata",
    [
        {"priority": "event cap"},
        {"execution_timing": "next_open"},
    ],
)
def test_green_open_cannot_cancel_persisted_risk_reduction(
    tmp_path, monkeypatch, metadata
):
    broker = Broker()
    monkeypatch.setattr(market_balancer, "datetime", OpeningTime)
    # Use the local test broker; no external order is sent or cancelled.
    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: broker)
    row = {
        "client_order_id": "anios-2026-09-10-sell-aaa-0",
        "symbol": "AAA",
        "side": "sell",
        "qty": 10,
        "session": "2026-09-10",
        "reason": "funded reduction",
        **metadata,
    }
    paper.save_state(tmp_path, paper.PaperState(pending=[row]))
    market_balancer._green_day_skip(
        tmp_path,
        {"session": "2026-09-10", "actions": [{"ticker": "AAA", "last_close": 100.0}]},
        {"AAA": {"open": 105.0, "bar": "2026-09-11T14:15:00+00:00"}},
        tmp_path / "intraday.log",
    )
    assert paper.load_state(tmp_path).pending == [row]
    assert broker.cancelled == []


# A funded rotation also keeps next-open timing even when no risk cap is binding.
def test_funded_rotation_dispatches_at_next_open():
    broker = Broker()
    order = paper.PaperOrder(
        "AAA",
        "sell",
        10,
        "rebalance",
        execution_timing="next_open",
    )
    submitted, refused = market_daily._submit(broker, [order], "2026-09-10", live=True)
    assert not refused
    assert len(submitted) == 1
    assert broker.queued[0][:4] == ("open", "AAA", 10, "sell")


# Walk the real planner, pending serializer, disk state and submission boundary.
def test_funded_plan_retains_execution_policy_through_persistence(tmp_path):
    from backend.tests.test_paper_funded_allocation import _context

    session = "2026-09-10"
    orders, state, _ = paper.plan(
        session,
        paper.PaperState(),
        100000.0,
        {"AAA": 500.0},
        {"AAA": 100.0, "BBB": 100.0, "SPY": 100.0},
        {},
        {},
        cash=50000.0,
        allocation_context=_context(session=session, event_cap=0.1),
    )
    sells = [order for order in orders if order.side == "sell"]
    assert sells
    assert all(order.execution_timing == "next_open" for order in orders)
    assert all(order.priority for order in sells)
    state.pending = market_daily._pending_orders(
        orders,
        session,
        {"AAA": 100.0, "BBB": 100.0, "SPY": 100.0},
        session,
    )
    paper.save_state(tmp_path, state)
    restored = paper.load_state(tmp_path)
    assert restored.pending == state.pending
    assert all(row["execution_timing"] == "next_open" for row in restored.pending)
    assert all(row["priority"] for row in restored.pending if row["side"] == "sell")
    broker = Broker()
    submitted, refused = market_daily._submit(broker, orders, session, live=True)
    assert not refused
    assert len(submitted) == len(orders)
    assert all(row[0] == "open" for row in broker.queued)


# The existing explicit-exit argument must remain effective on the funded path.
def test_funded_plan_honors_existing_finished_argument():
    from backend.tests.test_paper_funded_allocation import _context

    session = "2026-09-10"
    orders, state, _ = paper.plan(
        session,
        paper.PaperState(),
        100000.0,
        {"AAA": 500.0},
        {"AAA": 100.0, "BBB": 100.0, "SPY": 100.0},
        {},
        {},
        cash=50000.0,
        finished={"AAA": "explicit company exit"},
        allocation_context=_context(session=session),
    )
    assert sum(o.qty for o in orders if o.symbol == "AAA" and o.side == "sell") == 500
    assert "AAA" not in state.allocation_state["stable_desired"]
