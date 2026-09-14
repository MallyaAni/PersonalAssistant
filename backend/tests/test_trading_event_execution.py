"""Exercise durable FOMC intent and broker receipts without placing broker orders."""

from dataclasses import asdict

import pytest

from backend.agents.trading.desk import event_execution, event_risk, paper
from backend.cli import market_daily


# Supply one scheduled meeting and a close-time policy decision.
def policy(factor=0.5):
    return {"calendar_known": True, "factor": factor, "decision_date": "2026-09-16"}


# Write planned intent and read it back as the next process would.
def persist(root, state, orders, session):
    state.pending = [{**asdict(o), "session": session} for o in orders]
    paper.save_state(root, state)
    return paper.load_state(root)


# Confirm an order through the production settlement boundary and durable state file.
def receipt(root, state, status, qty):
    row = state.pending[0]
    outcome = {**row, "status": status, "filled_qty": qty, "filled_avg_price": 100}
    updated = paper.apply_settlements(state, paper.settle(state.pending, [outcome]))
    paper.save_state(root, updated)
    return paper.load_state(root)


# A partial reduction survives restart, retries only its remainder, then restores fills.
def test_partial_reduction_retry_and_restoration_persist(tmp_path):
    state = paper.PaperState(last_rebalance="2026-09-10", sessions_since_rebalance=3)
    args = ({"AAA": 100}, {"AAA": 100}, 10000)
    orders, state, _ = event_execution.plan("2026-09-11", state, *args, policy())
    assert [(o.side, o.qty) for o in orders] == [("sell", 50)]
    state = persist(tmp_path, state, orders, "2026-09-11")
    first_id = orders[0].client_order_id
    state = receipt(tmp_path, state, "canceled", 20)
    orders, state, _ = event_execution.plan(
        "2026-09-14", state, {"AAA": 80}, {"AAA": 100}, 12000, policy()
    )
    assert orders[0].qty == 30
    assert orders[0].client_order_id != first_id
    state = persist(tmp_path, state, orders, "2026-09-14")
    state = receipt(tmp_path, state, "filled", 30)
    orders, state, _ = event_execution.plan(
        "2026-09-15", state, {"AAA": 50}, {"AAA": 100}, 15000, policy()
    )
    assert not orders
    orders, state, _ = event_execution.plan(
        "2026-09-16", state, {"AAA": 50}, {"AAA": 100}, 15000, policy(1)
    )
    assert [(o.side, o.qty) for o in orders] == [("buy", 50)]
    state = persist(tmp_path, state, orders, "2026-09-16")
    state = receipt(tmp_path, state, "filled", 50)
    orders, state, what = event_execution.plan("2026-09-17", state, *args, policy(1))
    paper.save_state(tmp_path, state)
    saved = paper.load_state(tmp_path)
    assert not orders
    assert not saved.event_cycle
    assert "complete" in what
    assert saved.last_rebalance == "2026-09-10"
    assert saved.sessions_since_rebalance == 8
    assert len(saved.journal) == 3


# Rejected reductions never authorize a buy, and a pending cancel cannot be replaced.
@pytest.mark.parametrize(
    ("status", "filled", "working"),
    [("rejected", 0, False), ("pending_cancel", 20, True)],
)
def test_failed_or_working_reduction_cannot_create_extra_exposure(
    tmp_path, status, filled, working
):
    orders, state, _ = event_execution.plan(
        "2026-09-11", paper.PaperState(), {"AAA": 100}, {"AAA": 100}, 10000, policy()
    )
    state = persist(tmp_path, state, orders, "2026-09-11")
    state = receipt(tmp_path, state, status, filled)
    orders, state, _ = event_execution.plan(
        "2026-09-16", state, {"AAA": 100 - filled}, {"AAA": 100}, 10000, policy(1)
    )
    assert not orders
    assert bool(state.pending) is working


# Restoration is cash bounded, and missing prices or calendar coverage preserve intent.
def test_restoration_constraints_preserve_remaining_intent(tmp_path):
    orders, state, _ = event_execution.plan(
        "2026-09-11", paper.PaperState(), {"AAA": 100}, {"AAA": 100}, 0, policy()
    )
    state = persist(tmp_path, state, orders, "2026-09-11")
    state = receipt(tmp_path, state, "filled", 50)
    for prices, cash, expected in (({}, 10000, 0), ({"AAA": 100}, 1000, 9)):
        orders, next_state, _ = event_execution.plan(
            "2026-09-16", state, {"AAA": 50}, prices, cash, policy(1)
        )
        assert sum(o.qty for o in orders) == expected
        assert next_state.event_cycle
    orders, state, _ = event_execution.plan(
        "2026-09-16",
        state,
        {"AAA": 50},
        {"AAA": 100},
        10000,
        {**policy(1), "calendar_known": False},
    )
    assert not orders
    assert state.event_cycle


# A rebound or missing weakness reading cannot unlatch a persisted pre-meeting cut.
def test_persisted_latch_survives_changed_price_history():
    _, state, _ = event_execution.plan(
        "2026-09-11", paper.PaperState(), {"AAA": 100}, {"AAA": 100}, 0, policy()
    )
    orders, _, _ = event_execution.plan(
        "2026-09-14", state, {"AAA": 100}, {"AAA": 100}, 0, policy(1)
    )
    assert orders[0].side == "sell"


# The real submission dispatcher sends event sells to the opening execution path.
def test_event_sell_uses_open_and_ordinary_sell_uses_close():
    class Broker:
        # Record which execution method the dispatcher selected.
        def __init__(self):
            self.sent = []

        # Permit the after-close submission window.
        def clock(self):
            return {"is_open": False}

        # Capture the event order's actual transport boundary.
        def submit_market_on_open(self, *args):
            self.sent.append(("open", args))

        # Capture the ordinary order's actual transport boundary.
        def submit_market_on_close(self, *args):
            self.sent.append(("close", args))

    broker = Broker()
    orders = [
        paper.PaperOrder("AAA", "sell", 50, "risk", "event-id", event_risk.VERSION),
        paper.PaperOrder("BBB", "sell", 10, "rebalance", "normal-id"),
    ]
    submitted, refused = market_daily._submit(broker, orders, "2026-09-11", True)
    assert not refused
    assert len(submitted) == 2
    assert [r[0] for r in broker.sent] == ["open", "close"]


# Exercise nightly planning, write-before-submit, repeat suppression and restored state.
def test_daily_pipeline_persists_before_submission_and_reconciles(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from backend.market import alpaca_trading
    from backend.tests.test_market_daily import _report

    class Broker:
        # Keep broker outcomes separate from the desk's persisted intents.
        def __init__(self):
            self.qty = 100
            self.orders = []

        # Return a cash account with enough money for restoration.
        def account(self):
            return SimpleNamespace(equity=100000, cash=90000)

        # Expose confirmed positions to the same production planner.
        def positions(self):
            return [
                SimpleNamespace(
                    symbol="SNDK",
                    qty=self.qty,
                    market_value=self.qty * 100,
                    avg_entry_price=100,
                    current_price=100,
                    unrealized_pl=0,
                )
            ]

        # Allow after-close submissions in this transport fixture.
        def clock(self):
            return {"is_open": False}

        # Read back durable intent before accepting a simulated broker request.
        def submit_market_on_open(self, symbol, qty, side, client_order_id):
            stored = paper.load_state(tmp_path)
            assert stored.pending[0]["client_order_id"] == client_order_id
            assert stored.pending[0]["event_id"]
            evidence = stored.pending[0]["execution"]
            assert evidence["decision_at"]
            assert evidence["reference_price"] == 100
            assert evidence["reference_session"] == str(_report().panel.dates[-1])
            self.orders.append(
                {
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                    "qty": qty,
                    "side": side,
                    "status": "new",
                    "filled_qty": 0,
                }
            )
            return {"submitted_at": "2026-09-12T00:01:02Z", "time_in_force": "day"}

        # Supply actual outcomes for the reconciliation boundary.
        def orders_since(self, since):
            return self.orders

    broker = Broker()
    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: broker)
    monkeypatch.setattr(event_risk, "decision", lambda panel: policy())
    original = paper.PaperState(last_rebalance="2026-09-10", sessions_since_rebalance=1)
    paper.save_state(tmp_path, original)
    report = _report()
    market_daily.paper_trade(report, tmp_path, "2026-09-11", True)
    market_daily.paper_trade(report, tmp_path, "2026-09-11", True)
    assert len(broker.orders) == 1
    assert paper.load_state(tmp_path).pending[0]["qty"] == 50
    assert (
        paper.load_state(tmp_path).pending[0]["execution"]["submitted_at"]
        == "2026-09-12T00:01:02Z"
    )
    broker.orders[0].update(status="filled", filled_qty=50, filled_avg_price=100)
    broker.qty = 50
    market_daily.paper_trade(report, tmp_path, "2026-09-14", True)
    saved = paper.load_state(tmp_path)
    assert not saved.pending
    assert saved.journal[0]["filled_qty"] == 50
    assert saved.journal[0]["execution"]["submitted_at"] == "2026-09-12T00:01:02Z"
    assert saved.last_rebalance == original.last_rebalance
    assert saved.sessions_since_rebalance == 3
    monkeypatch.setattr(event_risk, "decision", lambda panel: policy(1))
    market_daily.paper_trade(report, tmp_path, "2026-09-16", True)
    assert broker.orders[-1]["side"] == "buy"
    assert broker.orders[-1]["qty"] == 50
    assert paper.load_state(tmp_path).pending[0]["side"] == "buy"
