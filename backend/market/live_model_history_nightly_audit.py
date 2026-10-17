"""Pure saved-night reconstruction; never broker execution or publication approval."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta

import numpy as np

from backend.agents.trading.desk import event_risk, nightly_plan, paper
from backend.cli import market_daily
from backend.market import calendar
from backend.market.live_model_history_receipts import instant, require, whole


# Derive a known request's venue evidence solely from conserved submission/outcome rows.
def broker_receipt(original, accepted, outcome, observed):
    cid = original["client_order_id"]
    require(accepted["client_order_id"] == cid, "Accepted nightly identity differs")
    require(
        accepted["accepted"] is True
        and accepted["symbol"] == original["symbol"]
        and accepted["side"] == original["side"]
        and whole(accepted["qty"]) <= whole(original["qty"])
        and instant(original["execution"]["decision_at"])
        <= instant(accepted["at"])
        <= observed,
        "Original nightly submission evidence differs",
    )
    require(
        "execution_policy" not in original
        and original.get("execution", {}).get("time_in_force", "day") == "day",
        "Only original current-model day-market venue is supported",
    )
    row = {
        "client_order_id": cid,
        "symbol": original["symbol"],
        "side": original["side"],
        "qty": str(accepted["qty"]),
        "filled_qty": "0",
        "filled_avg_price": None,
        "status": "accepted",
        "time_in_force": "day",
        "created_at": accepted["at"],
        "submitted_at": accepted["at"],
    }
    if outcome is not None:
        quantity = whole(outcome["filled_qty"], zero=True)
        require(
            outcome["client_order_id"] == cid
            and outcome["symbol"] == original["symbol"]
            and outcome["side"] == original["side"]
            and outcome["requested_qty"] == accepted["qty"]
            and quantity <= accepted["qty"]
            and outcome["status"]
            == ("filled" if quantity == accepted["qty"] else "expired")
            and instant(accepted["at"]) <= instant(outcome["at"]) <= observed,
            "Original nightly terminal outcome differs",
        )
        row.update(
            filled_qty=str(quantity),
            filled_avg_price=str(outcome["price"]) if quantity else None,
            status=outcome["status"],
        )
        if quantity:
            row["filled_at"] = outcome["at"]
        if outcome["status"] == "expired":
            row["expired_at"] = outcome["at"]
    return row


# Reconcile only due original legs against detached receipt dictionaries.
def reconcile(state, receipts, observed):
    known = set(receipts)
    missing = [
        row["client_order_id"]
        for row in state.pending
        if market_daily._acknowledged(row) and row["client_order_id"] not in known
    ]
    require(not missing, "Acknowledged nightly request lacks original submission")
    pending = market_daily._reconciliation_pending(state.pending, known, observed)
    settled = paper.settle(pending, list(receipts.values()))
    return paper.apply_settlements(state, settled), settled


# Authenticate confirmed cancellation without inventing an acknowledgment or clock.
def canceled_receipt(saved, original, accepted, observed):
    evidence = saved.get("execution", {})
    require(
        saved.get("client_order_id") == original["client_order_id"]
        and saved.get("symbol") == original["symbol"]
        and saved.get("side") == original["side"]
        and type(saved.get("qty")) is int
        and saved["qty"] == original["qty"]
        and saved.get("status") == "dead"
        and saved.get("terminal") is True
        and type(saved.get("filled_qty")) is int
        and saved["filled_qty"] == 0
        and "filled_at" not in evidence
        and "expired_at" not in evidence
        and instant(evidence.get("created_at")) == instant(accepted["at"])
        and instant(evidence.get("submitted_at")) == instant(accepted["at"])
        and instant(evidence.get("canceled_at")) == observed,
        "Original confirmed nightly cancellation evidence differs",
    )
    return evidence["canceled_at"]


# Derive before-plan controls from previous state and original confirmed receipts.
def before_plan(previous, accepted, outcomes, session, at, *, cancellations=None):
    observed = instant(at)
    local = observed.astimezone(calendar.NEW_YORK)
    years, sessions = calendar.reviewed_sessions()
    require(
        local.year in years
        and np.is_busday(np.datetime64(local.date()), busdaycal=sessions)
        and local.date().isoformat() == session
        and local
        == datetime.combine(
            local.date(), calendar.session_close(local.date()), calendar.NEW_YORK
        )
        + timedelta(minutes=1),
        "Exact original nightly completed-close clock required",
    )
    state = paper.PaperState(**asdict(previous))
    receipts = {}
    for original in state.pending:
        cid = original["client_order_id"]
        if cid in accepted:
            receipts[cid] = broker_receipt(
                original, accepted[cid], outcomes.get(cid), observed
            )
        else:
            require(cid not in outcomes, "Nightly outcome lacks accepted request")
    state, settled = reconcile(state, receipts, observed)
    withdrawn = market_daily._ids_to_withdraw(state, session, False)
    cancellation_evidence = {} if cancellations is None else cancellations
    require(
        isinstance(cancellation_evidence, dict), "Cancellation receipt map required"
    )
    required = {
        row["client_order_id"]: row
        for row in state.pending
        if row["client_order_id"] in withdrawn
        and row["client_order_id"] in receipts
        and receipts[row["client_order_id"]]["status"] == "accepted"
    }
    require(
        set(cancellation_evidence) == set(required),
        "Exact original confirmed cancellation receipt set required",
    )
    for cid, original in required.items():
        receipts[cid].update(
            status="canceled",
            canceled_at=canceled_receipt(
                cancellation_evidence[cid], original, accepted[cid], observed
            ),
        )
    if withdrawn:
        state, more = reconcile(state, receipts, observed)
        settled.extend(more)
    return state, settled, withdrawn


# Classify missing evidence and event bypasses without pretending a model was evaluated.
def branch(state, event_policy, session, *, account_problem=None):
    if account_problem is not None:
        require(
            account_problem
            in (
                "missing_held_close",
                "unknown_distribution_cash_in_lieu",
                "unknown_consolidation_cash_in_lieu",
                "unknown_exchange_cash_in_lieu",
            ),
            "Independently proven nightly account problem required",
        )
        return {
            "path": "nightly_broker_unavailable",
            "reason": account_problem,
            "model_required": False,
        }
    require(
        isinstance(event_policy, dict)
        and type(event_policy.get("calendar_known")) is bool,
        "Independent nightly event policy required",
    )
    factor = event_policy.get("factor")
    require(
        (
            type(factor) in (int, float) and factor in (1, event_risk.REDUCED)
            if event_policy["calendar_known"]
            else factor is None
        ),
        "Complete independent nightly event decision required",
    )
    if nightly_plan.event_plan_required(state, event_policy):
        return {
            "path": "event_priority",
            "reason": "pending_settlement"
            if state.pending
            else "calendar_unavailable"
            if not event_policy["calendar_known"]
            else "existing_event_cycle"
            if state.event_cycle
            else "event_reduction",
            "model_required": False,
        }
    return {
        "path": "already_planned" if session in state.sessions_seen else "model",
        "reason": None,
        "model_required": session not in state.sessions_seen,
    }


# Match saved settlement content while leaving later mark-based metrics to model audit.
def compare_settled(saved, expected):
    rows = [
        {
            "client_order_id": row.client_order_id,
            "symbol": row.symbol,
            "side": row.side,
            "qty": row.qty,
            "status": row.status,
            "terminal": row.terminal,
            "filled": row.filled_qty,
            "filled_price": row.filled_price,
            "kind": row.kind,
            "execution": row.execution,
        }
        for row in expected
    ]
    actual = [
        {key: deepcopy(row[key]) for key in model}
        for row, model in zip(saved, rows, strict=True)
    ]
    require(actual == rows, "Archived before-plan settlement evidence differs")
