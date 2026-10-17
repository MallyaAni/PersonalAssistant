"""Saved-order auditing separates funded requests, submissions, outcomes and cash."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime

import pytest

from backend.agents.trading.desk import paper
from backend.market.live_model_history_receipts import ReceiptLedger
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_live_model_history_verification import receipts


# Construct saved requests and terminal outcomes with independently stated cash.
def recorded(rows, cash, *, observed="2021-01-05T21:01:00+00:00"):
    intents, attempts, fills, journal = {}, [], [], []
    for row in rows:
        identifier = row["id"]
        original = {
            "client_order_id": identifier,
            "symbol": row.get("symbol", identifier),
            "side": row.get("side", "buy"),
            "qty": row.get("funded", row["qty"]),
            "session": "2021-01-04",
            "execution_timing": row.get("timing", "intraday"),
            "execute_on": "2021-01-05",
            "execution": {"decision_at": "2021-01-04T16:01:00-05:00"},
        }
        at = row.get("at", "2021-01-05T14:45:00+00:00")
        intents[identifier] = original
        attempts.append(
            {
                **original,
                "qty": row["qty"],
                "at": at,
                "observed_price": row.get("observed_price", row["price"]),
                "available_cash": row["available"],
                "accepted": True,
                "reason": None,
            }
        )
        qty = row.get("filled", row["qty"])
        price = row["price"] if qty else None
        fee = qty * (price or 0) / 1000
        fill_at = row.get("fill_at", at)
        fills.append(
            {
                **original,
                "requested_qty": row["qty"],
                "filled_qty": qty,
                "price": price,
                "fee": fee,
                "at": fill_at,
                "status": "filled" if qty == row["qty"] else "expired",
                "reason": "filled" if qty == row["qty"] else "partial_cash_or_coverage",
            }
        )
        execution = {**original["execution"], "created_at": at, "submitted_at": at}
        if qty:
            execution["filled_at"] = fill_at
        if qty != row["qty"]:
            execution["expired_at"] = fill_at
        journal.append(
            {
                **original,
                "status": "filled"
                if qty == original["qty"]
                else "partial"
                if qty
                else "dead",
                "filled_qty": qty,
                "filled_price": price or 0,
                "terminal": True,
                "execution": execution,
            }
        )
    return {
        "attempts": attempts,
        "fills": fills,
        "paper_state": {"pending": [], "journal": journal},
        "broker": {"observed_at": observed, "cash": cash},
    }, intents


# A smaller timing submission retains the larger original funded instruction.
def test_submitted_three_of_funded_five_can_fill_three_without_becoming_five():
    value, intents = recorded(
        [{"id": "AAA", "funded": 5, "qty": 3, "price": 100, "available": 100000}],
        99699.7,
    )
    before = deepcopy(value)
    audit = ReceiptLedger()
    audit.check(value, intents)
    assert intents["AAA"]["qty"] == 5
    assert audit.accepted["AAA"]["qty"] == 3
    assert audit.filled["AAA"] == 3
    assert value == before


# Accept actual private-venue receipts and reconciliation with smaller submitted shares.
def test_declared_private_broker_partial_receipt_and_real_journal_shape():
    original = {
        "client_order_id": "private-fixture",
        "symbol": "AAA",
        "side": "buy",
        "qty": 5,
        "session": "2021-01-04",
        "execution_timing": "intraday",
        "execute_on": "2021-01-05",
        "execution": {"decision_at": "2021-01-04T16:01:00-05:00"},
    }
    before = deepcopy(original)
    broker = ReplayBroker(100000, 10)
    now = datetime.fromisoformat("2021-01-05T14:45:00+00:00")
    broker.observe(now, {"AAA": 100}, True)
    broker.submit_market("AAA", 3, "buy", original["client_order_id"])
    broker.flush(now, {"AAA": 40000})
    state = paper.PaperState(pending=[deepcopy(original)])
    state = paper.apply_settlements(
        state,
        paper.settle(state.pending, broker.orders_since("2021-01-04T00:00:00+00:00")),
    )
    broker.observe(
        datetime.fromisoformat("2021-01-05T21:01:00+00:00"), {"AAA": 40000}, False
    )
    value = {
        "attempts": list(broker.attempt_history),
        "fills": list(broker.fill_history),
        "paper_state": asdict(state),
        "broker": broker.ledger(),
    }
    audit = ReceiptLedger()
    audit.check(value, {original["client_order_id"]: original})
    assert original == before
    assert state.pending == []
    assert state.journal[0]["qty"] == 5
    assert state.journal[0]["status"] == "partial"
    assert state.journal[0]["filled_qty"] == 2
    assert audit.cash == 19920
    assert audit.accepted[original["client_order_id"]]["qty"] == 3


# The accepted submitted amount bounds execution even when funded shares are larger.
@pytest.mark.parametrize(
    "change",
    [
        {"requested_qty": 5},
        {"filled_qty": 4},
        {"filled_qty": True},
        {"status": "partial"},
        {"fee": 0},
        {"at": "2021-01-05T14:30:00+00:00"},
    ],
)
def test_submitted_partial_corruptions_are_rejected(change):
    value, intents = receipts()
    value["fills"][0].update(change)
    with pytest.raises(ValueError):
        ReceiptLedger().check(value, intents)


# A same-clock sale cannot increase the cash available to the batch's purchases.
def test_same_batch_sell_proceeds_cannot_fund_a_later_buy_receipt():
    value, intents = recorded(
        [
            {"id": "OLD", "side": "sell", "qty": 10, "price": 100, "available": 1000},
            {
                "id": "NEW",
                "qty": 8,
                "observed_price": 100,
                "price": 150,
                "available": 1000,
            },
        ],
        797.8,
    )
    with pytest.raises(ValueError, match="Same-batch sale"):
        ReceiptLedger(1000).check(value, intents)


# Cash from an earlier settled clock legitimately funds a later execution batch.
def test_prior_clock_settled_sale_proceeds_can_fund_next_batch():
    value, intents = recorded(
        [
            {"id": "OLD", "side": "sell", "qty": 10, "price": 100, "available": 1000},
            {
                "id": "NEW",
                "qty": 8,
                "price": 150,
                "available": 1999,
                "at": "2021-01-05T15:00:00+00:00",
            },
        ],
        797.8,
    )
    audit = ReceiptLedger(1000)
    audit.check(value, intents)
    assert audit.cash == pytest.approx(797.8)


# Unsettled accepted buys reserve their original observed notional and fees.
def test_outstanding_reservation_is_required_in_later_attempt_cash():
    value, intents = recorded(
        [
            {"id": "WAIT", "qty": 5, "price": 100, "available": 1000},
            {
                "id": "NEW",
                "qty": 2,
                "price": 100,
                "available": 499.5,
                "at": "2021-01-05T15:00:00+00:00",
            },
        ],
        799.8,
    )
    value["fills"] = value["fills"][1:]
    waiting = value["paper_state"]["journal"].pop(0)
    waiting.update(status="open", filled_qty=0, filled_price=0, terminal=False)
    waiting["execution"].pop("filled_at")
    value["paper_state"]["journal"].insert(0, deepcopy(waiting))
    value["paper_state"]["pending"] = [
        {
            **intents["WAIT"],
            "execution": waiting["execution"],
            "sent": {"at": value["attempts"][0]["at"], "qty": 5},
        }
    ]
    audit = ReceiptLedger(1000)
    audit.check(value, intents)
    assert audit.outstanding == {"WAIT": pytest.approx(500.5)}
    changed = deepcopy(value)
    changed["attempts"][1]["available_cash"] = 1000
    with pytest.raises(ValueError, match="reservation"):
        ReceiptLedger(1000).check(changed, intents)


# A recorded cancellation releases only that original request's remaining reservation.
def test_cancel_releases_reservation_without_inventing_a_fill():
    value, intents = recorded(
        [
            {"id": "WAIT", "qty": 5, "price": 100, "available": 1000},
            {
                "id": "NEW",
                "qty": 8,
                "price": 100,
                "available": 1000,
                "at": "2021-01-05T15:00:00+00:00",
            },
        ],
        199.2,
    )
    value["fills"] = value["fills"][1:]
    waiting = value["paper_state"]["journal"][0]
    waiting.update(status="dead", filled_qty=0, filled_price=0, terminal=True)
    waiting["execution"].pop("filled_at")
    waiting["execution"]["canceled_at"] = "2021-01-05T14:59:00+00:00"
    audit = ReceiptLedger(1000)
    audit.check(value, intents)
    assert audit.outstanding == {}
    assert audit.filled.get("WAIT", 0) == 0


# An outcome may be known before the next saved reconciliation removes its pending row.
def test_terminal_outcome_can_remain_pending_until_recorded_reconciliation():
    value, intents = receipts()
    original = intents["original-id"]
    execution = value["paper_state"]["journal"][0]["execution"]
    value["paper_state"] = {
        "pending": [
            {
                **original,
                "execution": execution,
                "sent": {"at": value["attempts"][0]["at"], "qty": 3},
            }
        ],
        "journal": [],
    }
    audit = ReceiptLedger()
    audit.check(value, intents)
    assert audit.filled["original-id"] == 2
    assert audit.journal == {}


# An unsubmitted expired intent remains explicit missing evidence rather than a fill.
def test_unsent_missing_intent_remains_in_terminal_journal():
    value, intents = receipts()
    value["attempts"], value["fills"] = [], []
    value["broker"]["cash"] = 100000
    value["paper_state"]["journal"] = [
        {
            **intents["original-id"],
            "status": "missing",
            "filled_qty": 0,
            "filled_price": 0,
            "terminal": True,
        }
    ]
    ReceiptLedger().check(value, intents)


# Rejected requests keep their observed cash refusal and never create a fabricated fill.
def test_insufficient_cash_attempt_retains_unfilled_missing_state():
    value, intents = receipts()
    value["attempts"][0].update(
        accepted=False, reason="insufficient_reserved_cash", observed_price=50000
    )
    value["fills"] = []
    value["broker"]["cash"] = 100000
    value["paper_state"]["journal"] = [
        {
            **intents["original-id"],
            "status": "missing",
            "filled_qty": 0,
            "filled_price": 0,
            "terminal": True,
        }
    ]
    ReceiptLedger().check(value, intents)
    changed = deepcopy(value)
    changed["attempts"][0]["observed_price"] = 1
    with pytest.raises(ValueError, match="refusal"):
        ReceiptLedger().check(changed, intents)


# A terminal outcome can appear only once under the original accepted identity.
def test_duplicate_terminal_execution_receipt_is_rejected():
    value, intents = receipts()
    value["fills"].append(deepcopy(value["fills"][0]))
    with pytest.raises(ValueError, match="Duplicate terminal"):
        ReceiptLedger().check(value, intents)


# A newly seen journal must retain its original event and plan-leg identity too.
@pytest.mark.parametrize("name", ["kind", "event_id"])
def test_first_durable_snapshot_rejects_changed_original_leg(name):
    value, intents = receipts()
    value["paper_state"]["journal"][0][name] = "invented-leg"
    with pytest.raises(ValueError, match="leg identity"):
        ReceiptLedger().check(value, intents)


# Reconciled terminal journal entries cannot disappear or regress in later saved states.
@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "clock", "terminal", "filled", "sent"]
)
def test_original_durable_identity_clock_status_and_quantity_are_conserved(change):
    value, intents = receipts()
    audit = ReceiptLedger()
    audit.check(value, intents)
    changed = deepcopy(value)
    changed["attempts"], changed["fills"] = [], []
    changed["broker"]["observed_at"] = "2021-01-06T21:01:00+00:00"
    row = changed["paper_state"]["journal"][0]
    if change == "missing":
        changed["paper_state"]["journal"] = []
    elif change == "duplicate":
        changed["paper_state"]["journal"].append(deepcopy(row))
    elif change == "clock":
        row["execution"]["decision_at"] = "2021-01-04T16:02:00-05:00"
    elif change == "terminal":
        row["terminal"] = False
    elif change == "filled":
        row["filled_qty"] = 1
    else:
        row["execution"]["submitted_at"] = "2021-01-05T15:00:00+00:00"
    with pytest.raises(ValueError):
        audit.check(changed, intents)


# Duplicate attempts, altered accepted clocks and invalid acceptance states cannot hide.
@pytest.mark.parametrize(
    "change", ["duplicate", "clock", "decision", "accepted", "reason", "cash", "qty"]
)
def test_original_attempt_identity_clock_status_and_quantity_are_checked(change):
    value, intents = receipts()
    row = value["attempts"][0]
    if change == "duplicate":
        value["attempts"].append(deepcopy(row))
    elif change == "clock":
        row["at"] = "2021-01-05T15:00:00+00:00"
    elif change == "decision":
        row["at"] = intents["original-id"]["execution"]["decision_at"]
    elif change == "accepted":
        row["accepted"] = "true"
    elif change == "reason":
        row["reason"] = "uncovered_sell"
    elif change == "cash":
        row["available_cash"] = 100001
    else:
        row["qty"] = 6
    with pytest.raises(ValueError):
        ReceiptLedger().check(value, intents)
