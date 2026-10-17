"""Private native paper reconciliation for an already resolved conditional broker.

This is not a venue, live broker, clock source, persistence boundary or a replay of
an actual account. The caller must retain the returned state with its original
outcome before starting another decision. All native status meanings are retained,
including a terminal partial when submitted shares were below desired shares.
"""

import hashlib
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.cli import market_daily
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand
from backend.market import replay_broker as native


# Hash detached finite evidence without manufacturing missing account values.
def _sha(value):
    return hashlib.sha256(demand.encoded(value)).hexdigest()


# Require original unique identities without silently merging duplicate outcomes.
def _unique(rows):
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise ValueError("Original paper request rows required")
    identifiers = [row.get("client_order_id") for row in rows]
    if any(type(cid) is not str or not cid for cid in identifiers) or len(
        identifiers
    ) != len(set(identifiers)):
        raise ValueError("Original unique paper request identities required")


# Bind pending requests to acknowledged native receipts before native settlement.
def _requests(prior, orders, observed):
    _unique(prior.pending)
    _unique(prior.journal)
    known = {row["client_order_id"] for row in orders}
    if any(
        (market_daily._acknowledged(row) or row.get("sent"))
        and row["client_order_id"] not in known
        for row in prior.pending
    ):
        raise ValueError("Acknowledged request lacks original native broker receipt")
    if any(
        row["status"] == "accepted" and row["execution_phase"] == "market"
        for row in orders
    ):
        raise ValueError("Conditional market outcome remains unresolved")
    by_id = {row["client_order_id"]: row for row in orders}
    for row in prior.pending:
        codec.symbol(row.get("symbol"))
        if row.get("side") not in ("buy", "sell"):
            raise ValueError("Original buy/sell request side required")
        if type(row.get("qty")) is not int or row["qty"] <= 0:
            raise ValueError("Original positive whole desired quantity required")
        order = by_id.get(row["client_order_id"])
        if order is not None and (
            order["symbol"] != row.get("symbol")
            or order["side"] != row.get("side")
            or not 0 < int(order["qty"]) <= row["qty"]
            or native._instant(order["submitted_at"]) > observed
        ):
            raise ValueError("Original desired/submitted request binding differs")
    return known


# Reconcile through native rules without mutating the broker or original state.
def reconcile(client, state, *, pins, outcome_sha256, observed_at):
    if type(client) is not native.ReplayBroker or type(state) is not paper.PaperState:
        raise ValueError("Exact private native broker and paper state required")
    if pins["identity"]["source_revision"] != (
        "3b72cd4e0bc15acd24432d501918c721685a5333"
    ):
        raise ValueError("Exact current settlement metadata source required")
    codec.digest(outcome_sha256)
    observed = native._instant(observed_at)
    if observed != client._now:
        raise ValueError("Exact original conditional observation clock required")
    before_broker = codec.encode(client, **pins)
    original = asdict(state)
    prior = paper.PaperState(**deepcopy(original))
    orders = deepcopy(list(client._orders.values()))
    known = _requests(prior, orders, observed)
    due = market_daily._reconciliation_pending(prior.pending, known, observed)
    settled = paper.settle(due, orders)
    updated = paper.apply_settlements(prior, settled)
    after_broker = codec.encode(client, **pins)
    if before_broker != after_broker or asdict(state) != original:
        raise ValueError("Native reconciliation changed original broker or input state")
    detail = {
        "schema": "private-conditional-paper-reconciliation/1",
        "origin": "CONDITIONAL_REPLAY_BROKER_NOT_ACTUAL_EXECUTION",
        "outcome_sha256": outcome_sha256,
        "identity_sha256": pins["identity_sha256"],
        "broker_checkpoint_sha256": hashlib.sha256(before_broker).hexdigest(),
        "prior_paper_sha256": _sha(original),
        "reconciled_paper_sha256": _sha(asdict(updated)),
        "conditional_observed_at": observed.isoformat(),
        "source_sha256": {
            name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name, module in (
                ("paper", paper),
                ("market_daily", market_daily),
                ("codec", codec),
            )
        },
        "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "settled": [asdict(row) for row in settled],
        "unreconciled_pending": [row["client_order_id"] for row in updated.pending],
        "durable_state_committed": False,
        "actual_execution_claim": False,
    }
    return updated, detail
