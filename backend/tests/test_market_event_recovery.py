"""Walk missed FOMC reductions through real persistence and broker boundaries."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk import paper
from backend.cli import market_daily
from backend.cli import market_event_recovery as recovery
from backend.market import event_status

NOW = datetime(2026, 9, 14, 14, 20, tzinfo=UTC)
LATEST = {"session": "2026-09-11"}
POLICY = {"factor": 0.5, "calendar_known": True, "decision_date": "2026-09-16"}


# Provide completed regular-session bars with a separate collection timestamp.
def snapshot():
    return {
        "decision_session": LATEST["session"],
        "as_of": "2026-09-14T14:15:00Z",
        "quotes": {
            s: {"last": 100, "bar": "2026-09-14T14:00:00Z"} for s in ("AAA", "SPY")
        },
    }


class Broker:
    base_url = "https://paper-api.alpaca.markets/v2"

    # Model fills and uncertain acknowledgments without connecting to a broker.
    def __init__(self, root):
        self.root, self.qty, self.rows, self.calls = root, 100, {}, []
        self.crash = False
        self.is_open = True

    # Expose the authoritative regular-session clock.
    def clock(self):
        return {"is_open": self.is_open}

    # Return positions after the fills actually applied below.
    def positions(self):
        return [SimpleNamespace(symbol="AAA", qty=self.qty)]

    # Supply cash independently from the reduction's reference prices.
    def account(self):
        return SimpleNamespace(cash=0)

    # Return all observed outcomes, including terminal partial executions.
    def orders_since(self, after):
        return list(self.rows.values())

    # No separate working orders exist in this fixture.
    def open_orders(self):
        return []

    # Assert durable intent exists before applying one idempotent broker fill.
    def submit_market_on_open(self, symbol, qty, side, client_id):
        assert side == "sell"
        assert any(
            p["client_order_id"] == client_id
            for p in paper.load_state(self.root).pending
        )
        self.calls.append(client_id)
        if client_id not in self.rows:
            self.qty -= qty
            self.rows[client_id] = {
                "client_order_id": client_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "filled_qty": qty,
                "filled_avg_price": 100,
                "status": "filled",
                "filled_at": NOW.isoformat(),
            }
        if self.crash:
            self.crash = False
            raise OSError("connection lost after broker accepted")
        return self.rows[client_id]


# A missed nightly reduction cuts once and never advances the rebalance clock.
def test_reduction_and_restart_reconcile_actual_fills(tmp_path):
    paper.save_state(tmp_path, paper.PaperState(sessions_since_rebalance=3))
    broker = Broker(tmp_path)
    result = recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert result["status"] == "reduction pending"
    assert broker.qty == 50
    for _ in range(3):
        result = recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert len(broker.calls) == 1
    assert result["sold"] == {"AAA": 50}
    state = paper.load_state(tmp_path)
    assert state.event_cycle["baseline"] == {"AAA": 100}
    assert state.sessions_since_rebalance == 3
    assert not state.sessions_seen
    assert not state.pending
    assert event_status.for_planning(LATEST, tmp_path)["event_risk"][
        "execution_pending"
    ]
    assert "event_risk" not in LATEST


# Losing the acknowledgment must not create a second cut after process restart.
def test_accepted_order_survives_lost_acknowledgment(tmp_path):
    broker = Broker(tmp_path)
    broker.crash = True
    with pytest.raises(OSError, match="connection lost"):
        recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert paper.load_state(tmp_path).pending
    recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert broker.qty == 50
    assert len(broker.calls) == 1
    assert not paper.load_state(tmp_path).pending


# An absent receipt retries the exact persisted ID instead of inventing another order.
def test_missing_receipt_reuses_the_id_even_if_broker_listing_lags(tmp_path):
    broker = Broker(tmp_path)
    recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    original = broker.calls[0]
    broker.orders_since = lambda after: []
    recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert broker.calls == [original, original]
    assert broker.qty == 50
    assert paper.load_state(tmp_path).pending[0]["client_order_id"] == original
    state, settled = market_daily._reconcile(
        broker, paper.load_state(tmp_path), tmp_path, True
    )
    assert not settled
    assert state.pending[0]["client_order_id"] == original


# A terminal partial fill authorizes only its remainder on the next attempt.
# A changed holding cannot turn a retry into a new short position.
def test_missing_receipt_with_smaller_holdings_is_not_resubmitted(tmp_path):
    broker = Broker(tmp_path)
    recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    broker.qty = 0
    broker.orders_since = lambda after: []
    result = recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert result["status"] == "holdings below pending reduction"
    assert len(broker.calls) == 1
    assert paper.load_state(tmp_path).pending


# A terminal partial fill authorizes only its remainder on the next attempt.
def test_partial_fill_does_not_reset_the_reduction_baseline(tmp_path):
    broker = Broker(tmp_path)
    recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    first = broker.calls[0]
    broker.rows[first].update(status="canceled", filled_qty=20)
    broker.qty = 80
    recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert broker.qty == 50
    assert broker.rows[broker.calls[-1]]["qty"] == 30
    assert broker.calls[-1] != first
    recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert paper.load_state(tmp_path).event_cycle["baseline"]["AAA"] == 100


# Missing evidence and invalid execution windows must never submit a reduction.
@pytest.mark.parametrize(
    "case", ["stale", "missing", "closed", "expired", "wrong_decision", "old_record"]
)
def test_recovery_withholds_on_unknown_or_expired_evidence(tmp_path, case):
    broker, snap, latest, now = Broker(tmp_path), snapshot(), LATEST, NOW
    if case == "stale":
        snap["as_of"] = "2026-09-14T13:00:00Z"
    elif case == "missing":
        del snap["quotes"]["AAA"]
    elif case == "closed":
        broker.is_open = False
    elif case == "expired":
        now = datetime(2026, 9, 17, 14, 20, tzinfo=UTC)
    elif case == "wrong_decision":
        snap["decision_session"] = "2026-09-10"
    else:
        latest = {"session": "2026-09-10"}
        snap["decision_session"] = latest["session"]
    recovery.recover(tmp_path, latest, snap, POLICY, broker, now)
    assert broker.qty == 100
    assert not broker.calls


# Source-only updates cannot activate order recovery before the deployed code matches.
def test_activation_is_bound_to_the_execution_artifact(tmp_path, monkeypatch):
    assert not recovery.activated(tmp_path)
    assert (
        recovery.run(tmp_path, LATEST, snapshot())["status"]
        == "waiting for gated deployment"
    )
    recovery.activate(tmp_path)
    assert recovery.activated(tmp_path)
    monkeypatch.setattr(recovery, "execution_hash", lambda: "different code")
    assert not recovery.activated(tmp_path)


# An endpoint whose name merely contains 'paper' cannot receive recovery orders.
def test_recovery_rejects_non_paper_hosts(tmp_path):
    broker = Broker(tmp_path)
    broker.base_url = "https://api.alpaca.markets/v2?paper=true"
    with pytest.raises(ValueError, match="official paper endpoint"):
        recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, NOW)
    assert not broker.calls


# The intraday exception is structurally restricted to event sells while open.
# Competing execution processes serialize their read-modify-write transaction.
def test_paper_transaction_preserves_competing_updates(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    first_entered, second_entered, release = Event(), Event(), Event()

    # Hold the first update until the competing writer has tried to acquire the lock.
    def update(first):
        with paper.transaction(tmp_path):
            state = paper.load_state(tmp_path)
            (first_entered if first else second_entered).set()
            if first:
                assert release.wait(5)
            state.order_seq += 1
            paper.save_state(tmp_path, state)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(update, True)
        assert first_entered.wait(5)
        second = pool.submit(update, False)
        try:
            assert not second_entered.wait(0.1)
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert paper.load_state(tmp_path).order_seq == 2


# The intraday exception is structurally restricted to event sells while open.
# A qualified cut pauses additions even if execution is waiting for better data.
def test_qualified_recovery_pauses_planning_before_orders_exist(tmp_path):
    import json

    folder = tmp_path / "desk"
    folder.mkdir()
    (folder / "event-live.json").write_text(
        json.dumps(
            {
                "as_of": datetime.now(UTC).isoformat(),
                "policy": POLICY,
                "status": "fresh completed prices required",
            }
        )
    )
    status = event_status.load(tmp_path)
    assert not status["active"]
    assert status["planning_paused"]
    assert event_status.for_planning(LATEST, tmp_path)["event_risk"][
        "execution_pending"
    ]


# A record frozen with a finished cycle's pending flag must not keep planning
# paused once the live event state has moved on.
def test_stale_execution_pending_clears_when_the_cycle_is_over(tmp_path):
    record = {
        "session": "2026-09-11",
        "event_risk": {"factor": 1.0, "execution_pending": True},
    }
    paper.save_state(tmp_path, paper.PaperState())
    assert event_status.for_planning(record, tmp_path)["event_risk"][
        "execution_pending"
    ] is False


# The intraday exception is structurally restricted to event sells while open.
@pytest.mark.parametrize(
    ("side", "event_id", "opened"),
    [("buy", "event", True), ("sell", None, True), ("sell", "event", False)],
)
def test_dispatcher_rejects_non_reduction_orders(tmp_path, side, event_id, opened):
    broker = Broker(tmp_path)
    broker.is_open = opened
    order = paper.PaperOrder("AAA", side, 5, "test", "id", event_id)
    submitted, refused = market_daily._submit(
        broker, [order], "2026-09-14", True, intraday_event_reduction=True
    )
    assert not submitted
    assert refused
    assert not broker.calls


# The morning after the decision, the restoration orders the nightly queued
# for the open are reconciled from broker evidence and the cycle is released
# once every share is back; an order still working keeps the cycle open,
# and an order the broker does not list waits for the nightly.
@pytest.mark.parametrize("outcome", ["filled", "working", "unlisted"])
def test_the_morning_after_learns_the_restoration_fills(tmp_path, outcome):
    broker = Broker(tmp_path)
    now = datetime(2026, 9, 17, 14, 20, tzinfo=UTC)
    state = paper.PaperState()
    state.event_cycle = {
        "id": "fomc-3-session-weakness/2:2026-09-16",
        "decision_date": "2026-09-16",
        "baseline": {"AAA": 100.0},
    }
    state.journal = [
        {
            "client_order_id": "anios-2026-09-14-sell-aaa-1",
            "symbol": "AAA",
            "side": "sell",
            "qty": 50,
            "filled_qty": 50,
            "status": "filled",
            "event_id": state.event_cycle["id"],
            "session": "2026-09-14",
        }
    ]
    state.pending = [
        {
            "client_order_id": "anios-2026-09-16-buy-aaa-2",
            "symbol": "AAA",
            "side": "buy",
            "qty": 50,
            "session": "2026-09-16",
            "reason": "FOMC risk restoration",
            "event_id": state.event_cycle["id"],
            "execution": {
                "created_at": "2026-09-17T00:24:51Z",
                "submitted_at": "2026-09-17T00:24:51Z",
            },
        }
    ]
    paper.save_state(tmp_path, state)
    if outcome != "unlisted":
        broker.rows["anios-2026-09-16-buy-aaa-2"] = {
            "client_order_id": "anios-2026-09-16-buy-aaa-2",
            "symbol": "AAA",
            "side": "buy",
            "qty": 50,
            "filled_qty": 50 if outcome == "filled" else 0,
            "filled_avg_price": 100 if outcome == "filled" else None,
            "status": "filled" if outcome == "filled" else "accepted",
            "filled_at": now.isoformat() if outcome == "filled" else None,
        }
    broker.qty = 100 if outcome == "filled" else 50
    result = recovery.recover(tmp_path, LATEST, snapshot(), POLICY, broker, now)
    back = paper.load_state(tmp_path)
    assert not broker.calls  # nothing is submitted after the decision
    if outcome == "filled":
        assert result["status"] == "restoration filled; the cycle is closed"
        assert result["active"] is False
        assert back.event_cycle == {}
        assert back.pending == []
    elif outcome == "working":
        assert result["status"] == "restoration orders working at the broker"
        assert back.event_cycle["decision_date"] == "2026-09-16"
        assert len(back.pending) == 1
    else:
        assert result["status"] == "awaiting nightly restoration"
        assert back.event_cycle["decision_date"] == "2026-09-16"
