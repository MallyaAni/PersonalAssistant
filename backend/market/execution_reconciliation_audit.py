"""Saved-only order reconciliation, without predictions, broker calls or state writes.

The original decision, a later account snapshot and subsequent broker receipts
are distinct observations. Matching quantities is not proof of learned timing,
cash activity completeness, fresh admission or the quality of an investment.
"""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from backend.market.labels import ExecutionTiming, OrderSide

SCHEMA = "saved-execution-reconciliation/1"


# Refuse inconsistent evidence rather than manufacture a missing decision or fill.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Parse finite decimal evidence without accepting booleans as quantities or money.
def number(value):
    require(not isinstance(value, bool), "Numeric evidence cannot be boolean")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Finite numeric evidence required") from exc
    require(result.is_finite(), "Finite numeric evidence required")
    return result


# Require positive whole planned shares while preserving original broker strings.
def whole(value):
    result = number(value)
    require(
        result > 0 and result == result.to_integral_value(), "Whole shares required"
    )
    return result


# Read an aware instant without rewriting its original timestamp representation.
def instant(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.utcoffset() is not None, "Aware original timestamp required")
    return parsed.astimezone(UTC)


# Compare decimal arithmetic within an explicit absolute evidence tolerance.
def close(actual, expected, label, tolerance=Decimal("0.00000001")):
    require(abs(number(actual) - number(expected)) <= tolerance, f"{label} differs")


# Hash a regular evidence file without accepting replacement through a symlink.
def file_hash(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Regular saved evidence required")
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Reject nonfinite JSON values rather than interpreting them as known evidence.
def reject_constant(value):
    raise ValueError(f"Nonfinite JSON evidence: {value}")


# Refuse duplicate keys that could bind two readers to different saved evidence.
def unique_object(items):
    result = {}
    for key, value in items:
        require(key not in result, "Duplicate JSON evidence key")
        result[key] = value
    return result


# Read authenticated JSON bytes once and reject concurrent evidence replacement.
def read_json(path, expected):
    require(file_hash(path) == expected, f"Saved evidence hash differs: {path}")
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, "Saved evidence changed")
    result = json.loads(
        raw, parse_constant=reject_constant, object_pairs_hook=unique_object
    )
    require(file_hash(path) == expected, "Saved evidence changed while reading")
    return result


# Resolve only an original regular file underneath the supplied saved capture.
def evidence_path(root, name):
    relative = Path(name)
    require(
        not relative.is_absolute() and ".." not in relative.parts,
        "Unsafe evidence path",
    )
    target = Path(root) / relative
    require(
        target.resolve().is_relative_to(Path(root).resolve()),
        "Evidence path escaped capture",
    )
    return target


# Authenticate every original capture byte against a separately supplied proof hash.
def original_capture(root, expected):
    proof_path = Path(root) / "observation-proof.json"
    proof = read_json(proof_path, expected)
    files = proof["files_sha256"]
    require(isinstance(files, dict) and files, "Original byte manifest required")
    for name, digest in files.items():
        require(
            file_hash(evidence_path(root, name)) == digest, "Original capture differs"
        )
    return proof


# Index original objects by their unmodified identity without selecting a duplicate.
def indexed(rows, key):
    result = {}
    for row in rows:
        identity = row[key]
        require(identity not in result, f"Duplicate original {key}")
        result[identity] = row
    return result


# Check the original sizing/account boundary without importing a later price snapshot.
def decision_basis(record, state):
    paper = record["paper"]
    selected = paper["joint_funded"]
    receipt = selected["receipt"]
    require(
        selected["policy"] == receipt["policy"] == paper["policy"],
        "Policy binding differs",
    )
    require(
        receipt["session"] == paper["session"] == record["session"],
        "Decision session differs",
    )
    require(receipt["status"] == "available", "Accepted sizing receipt required")
    require(selected["targets"] == receipt["targets"], "Saved target binding differs")
    require(
        set(receipt["grade_signals"]) == set(receipt["targets"]),
        "All original signals required",
    )
    require(
        all(number(value) >= 0 for value in receipt["targets"].values()),
        "Negative target weight",
    )
    positions = indexed(paper["positions"], "symbol")
    history = [row for row in state["history"] if row["session"] == record["session"]]
    require(len(history) == 1, "One original account snapshot required")
    require(
        history[0]["positions"] == paper["positions"], "Original share snapshot differs"
    )
    close(paper["equity"], receipt["observed_equity"], "Original observed equity")
    close(paper["cash"], receipt["observed_cash"], "Original observed cash")
    prices = {}
    for name, position in positions.items():
        quantity = whole(position["qty"])
        require(name in receipt["current_weights"], "Held sizing weight missing")
        prices[name] = (
            number(receipt["current_weights"][name])
            * number(receipt["observed_equity"])
            / quantity
        )
        require(prices[name] > 0, "Positive original sizing mark required")
    return receipt, positions, prices


# Bind submitted and unsent original legs to the saved policy's timing choices.
def original_orders(record, state, receipt):
    paper = record["paper"]
    orders = indexed([*paper["orders"], *paper["planned"]], "client_order_id")
    pending = indexed(state["pending"], "client_order_id")
    timing = receipt["execution_timing"]["orders"]
    require(set(orders) == set(timing), "Original order/timing identity differs")
    for identity, row in orders.items():
        whole(row["qty"])
        require(identity in pending, "Original pending leg missing")
        saved = pending[identity]
        require(
            all(saved[key] == row[key] for key in ("symbol", "side", "qty")),
            "Original quantity/side identity differs",
        )
        require(
            saved["session"] == record["session"]
            and saved["execution_timing"] == timing[identity],
            "Original leg timing differs",
        )
        require(row["side"] in OrderSide, "Original side invalid")
        if row["symbol"] in receipt["company_exits"]:
            require(
                timing[identity] == ExecutionTiming.NEXT_OPEN
                and OrderSide(row["side"]) is OrderSide.SELL,
                "Company exit routing differs",
            )
    return orders, pending


# Compare immutable planned legs with actual broker outcomes by their original IDs.
def order_outcome(identity, row, pending, queued, later, prices, close_published):
    original = pending[identity]
    before = queued.get(identity)
    require(before is not None, "Original queued broker receipt missing")
    require(
        all(before[key] == row[key] for key in ("symbol", "side")),
        "Queued order identity differs",
    )
    close(before["qty"], whole(row["qty"]), "Queued whole quantity")
    close(before["filled_qty"], 0, "Original queued fill quantity")
    require(
        before["status"] != "filled" and before["filled_at"] is None,
        "Queued order was relabelled filled",
    )
    execution = original["execution"]
    decision = instant(execution["decision_at"])
    created = instant(execution["created_at"])
    require(
        instant(close_published) <= decision <= created,
        "Original publication/decision/submission clock differs",
    )
    require(
        number(execution["reference_price"]) > 0,
        "Positive original reference price required",
    )
    if row["symbol"] in prices:
        close(
            execution["reference_price"],
            prices[row["symbol"]],
            "Original sizing reference price",
        )
    require(
        execution["created_at"]
        == row["execution"]["created_at"]
        == before["created_at"],
        "Original created clock differs",
    )
    trace = {
        "client_order_id": identity,
        "symbol": row["symbol"],
        "side": row["side"],
        "original_qty": int(whole(row["qty"])),
        "original_decision_at": execution["decision_at"],
        "original_created_at": execution["created_at"],
        "original_submitted_at": execution["submitted_at"],
        "original_reference_price": execution["reference_price"],
        "execution_timing": original["execution_timing"],
        "queued_status": before["status"],
        "reference_crosscheck": (
            "original_marked_weight_and_quantity"
            if row["symbol"] in prices
            else "UNVERIFIED_NO_ORIGINAL_HELD_MARK"
        ),
        "learned_timing": "UNVERIFIED_NO_LINKED_OBSERVATION",
        "broker_outcome": "UNVERIFIED_MISSING_ORDER",
        "filled_qty": None,
    }
    if original["execution_timing"] == ExecutionTiming.NEXT_OPEN:
        trace["learned_timing"] = "NOT_EXERCISED_NEXT_OPEN"
    broker = later.get(identity)
    if broker is None:
        return trace
    require(
        all(broker[key] == row[key] for key in ("symbol", "side")),
        "Later broker identity differs",
    )
    close(broker["qty"], row["qty"], "Later broker requested quantity")
    require(
        abs(instant(broker["created_at"]) - created).total_seconds() <= 0.000001,
        "Later original created clock differs",
    )
    filled = number(broker["filled_qty"])
    require(0 <= filled <= whole(row["qty"]), "Invalid actual filled quantity")
    if filled:
        require(
            number(broker["filled_avg_price"]) > 0 and broker["filled_at"],
            "Actual fill price/time missing",
        )
        require(
            created <= instant(broker["submitted_at"]) <= instant(broker["filled_at"]),
            "Actual fill chronology differs",
        )
    trace.update(
        broker_outcome=broker["status"],
        filled_qty=str(filled),
        filled_avg_price=broker["filled_avg_price"],
        filled_at=broker["filled_at"],
        broker_created_at=broker["created_at"],
        broker_submitted_at=broker["submitted_at"],
        broker_completion_basis="aggregate_order_completion_not_each_partial_fill",
    )
    return trace


# Reconcile shares and conditionally compare cash to aggregate fills.
def account_delta(positions, before, later, traces):
    before_positions = indexed(before["positions"], "symbol")
    after = indexed(later["positions"], "symbol")
    require(
        set(before_positions) == set(positions), "Original queued account names differ"
    )
    for name, position in positions.items():
        close(
            before_positions[name]["qty"],
            position["qty"],
            "Original queued share quantity",
        )
    if any(row["filled_qty"] is None for row in traces):
        return {
            "positions": "UNVERIFIED_MISSING_ORDER_OUTCOME",
            "cash": "UNVERIFIED_MISSING_ORDER_OUTCOME",
        }
    expected = {name: number(row["qty"]) for name, row in positions.items()}
    cash = number(before["account"]["cash"])
    for row in traces:
        filled = number(row["filled_qty"])
        sign = 1 if OrderSide(row["side"]) is OrderSide.BUY else -1
        expected[row["symbol"]] = (
            expected.get(row["symbol"], Decimal(0)) + sign * filled
        )
        require(expected[row["symbol"]] >= 0, "Filled sale exceeds original shares")
        if filled:
            cash -= sign * filled * number(row["filled_avg_price"])
    expected = {name: qty for name, qty in expected.items() if qty}
    require(
        set(after) == set(expected), "Observed position names differ from saved fills"
    )
    for name, quantity in expected.items():
        close(after[name]["qty"], quantity, "Observed share delta")
    residual = number(later["account"]["cash"]) - cash
    return {
        "positions": "VERIFIED_SAVED_QUANTITY_DELTA",
        "remaining_positions": len(after),
        "original_cash": before["account"]["cash"],
        "cash_from_aggregate_fills_before_unobserved_fees": str(cash),
        "later_cash": later["account"]["cash"],
        "cash_residual": str(residual),
        "cash": "CONSISTENT_TO_BROKER_CENTS"
        if abs(residual) <= Decimal("0.01")
        else "UNEXPLAINED_CASH_DIFFERENCE",
        "fees_transfers_corporate_actions": "UNVERIFIED_NO_ACCOUNT_ACTIVITY_LEDGER",
    }


# Report whether a later saved journal actually retained the observed completed orders.
def durable_status(state, traces):
    pending = indexed(state["pending"], "client_order_id")
    journal = indexed(state["journal"], "client_order_id")
    result = {}
    for row in traces:
        identity = row["client_order_id"]
        if identity in pending:
            result[identity] = "ORIGINAL_PENDING_RETAINED_NO_LATER_JOURNAL_SETTLEMENT"
        elif identity not in journal:
            result[identity] = "UNVERIFIED_NO_PENDING_OR_JOURNAL_RECEIPT"
        else:
            settled = journal[identity]
            close(settled["qty"], row["original_qty"], "Durable original quantity")
            if row["filled_qty"] is None:
                result[identity] = "UNVERIFIED_BROKER_OUTCOME_MISSING"
            else:
                close(
                    settled["filled_qty"],
                    row["filled_qty"],
                    "Durable actual fill quantity",
                )
                result[identity] = settled["status"]
    return result


# Audit saved decisions through queued broker receipts and later observed fills only.
def audit_documents(record, state, before, later, close_receipt, later_state=None):
    receipt, positions, prices = decision_basis(record, state)
    orders, pending = original_orders(record, state, receipt)
    queued = indexed(before["open_orders"], "client_order_id")
    outcomes = indexed(later.get("orders", []), "client_order_id")
    require(
        instant(before["clock"]["timestamp"]) < instant(later["clock"]["timestamp"]),
        "Broker observation chronology differs",
    )
    traces = [
        order_outcome(
            identity,
            row,
            pending,
            queued,
            outcomes,
            prices,
            close_receipt["identity"]["published_at"],
        )
        for identity, row in orders.items()
    ]
    for row in traces:
        if row["symbol"] in receipt["company_exits"]:
            row["learned_timing"] = "NOT_EXERCISED_COMPANY_EXIT"
    account = account_delta(positions, before, later, traces)
    preserved = receipt.get("grade_preserved_holdings", [])
    return {
        "schema": SCHEMA,
        "status": (
            "VERIFIED_SAVED_ORDER_AND_QUANTITY_RECONCILIATION"
            if account["positions"] == "VERIFIED_SAVED_QUANTITY_DELTA"
            else "UNVERIFIED_INCOMPLETE_BROKER_OUTCOME"
        ),
        "session": record["session"],
        "source_revision": record["provenance"]["code_revision"],
        "policy": receipt["policy"],
        "all_stock_signals": len(receipt["grade_signals"]),
        "sizing_observed_equity": receipt["observed_equity"],
        "sizing_observed_cash": receipt["observed_cash"],
        "sizing_marks": {name: str(prices[name]) for name in sorted(prices)},
        "later_snapshot_mark_substitution": False,
        "grade_preserved_holdings": preserved,
        "execution_missing": receipt["execution"]["missing"],
        "execution_blocked": receipt["execution"]["blocked"],
        "orders": traces,
        "account": account,
        "durable_reconciliation": durable_status(later_state, traces)
        if later_state
        else "UNVERIFIED_NO_LATER_STATE",
        "learned_intraday_path": "UNVERIFIED_NOT_EXERCISED"
        if all(row["execution_timing"] == ExecutionTiming.NEXT_OPEN for row in traces)
        else "UNVERIFIED_REQUIRES_AUTHENTICATED_FORECAST_AND_SENDER_RECEIPTS",
        "original_parity": {
            "ok": record["grade_parity"]["ok"],
            "mismatches": len(record["grade_parity"].get("mismatches", [])),
        },
        "fresh_current_decision": "UNVERIFIED_DATED_SAVED_OBSERVATION_ONLY",
        "learned_close_expires_at": close_receipt["identity"]["expires_at"],
        "unverified": [
            "fresh_ordinary_nightly_acceptance",
            "full_learned_intraday_wait_execute_and_actual_UI",
            "account_activity_fees_transfers_and_corporate_actions",
            "numerical_model_inference_and_investment_quality",
            "present_source_approval_and_owner_API_isolation",
        ],
    }


# Authenticate saved input captures and recheck every read byte without modifying them.
def audit_saved(original_root, later_root, original_proof_sha256, later_proof_sha256):
    original_root, later_root = Path(original_root), Path(later_root)
    proof = original_capture(original_root, original_proof_sha256)
    later_proof = read_json(later_root / "observation-proof.json", later_proof_sha256)
    files, later_files = proof["files_sha256"], later_proof["files_sha256"]
    session = proof["ordinary_session"]
    record_path = f"desk/asof={session}/desk.json"
    record = read_json(evidence_path(original_root, record_path), files[record_path])
    state = read_json(original_root / "paper/state.json", files["paper/state.json"])
    before = read_json(
        original_root / "broker-get-only.json", files["broker-get-only.json"]
    )
    later = read_json(
        later_root / "broker-get-only.json", later_files["broker-get-only.json"]
    )
    close_receipt = read_json(
        original_root / "observation/close.json", files["observation/close.json"]
    )
    admission = record["paper"]["learned_holding"]
    require(
        admission["close_receipt_sha256"] == files["observation/close.json"]
        and admission["config_sha256"] == files["desk/learned-holding/config.json"],
        "Original model admission binding differs",
    )
    parity = read_json(
        original_root / "desk/grade_parity.json", files["desk/grade_parity.json"]
    )
    rows = [row for row in parity["rows"] if row["date"] == session]
    require(
        len(rows) == 1 and record["grade_parity"] == rows[0],
        "Original parity evidence differs",
    )
    learned_inputs = read_json(
        original_root / f"learned_inputs/asof={session}.json",
        files[f"learned_inputs/asof={session}.json"],
    )
    require(
        learned_inputs["record_sha256"] == files[record_path],
        "Original learned inputs bind another record",
    )
    later_state_path = later_root / "paper/state.json"
    later_state = (
        read_json(later_state_path, later_files["paper/state.json"])
        if later_state_path.exists()
        else None
    )
    result = audit_documents(record, state, before, later, close_receipt, later_state)
    result["original_proof_sha256"] = original_proof_sha256
    result["later_proof_sha256"] = later_proof_sha256
    result["original_record_sha256"] = files[record_path]
    result["later_capture_missing_records"] = later_proof.get(
        "missing_original_records", {}
    )
    original_capture(original_root, original_proof_sha256)
    read_json(later_root / "observation-proof.json", later_proof_sha256)
    require(
        file_hash(later_root / "broker-get-only.json")
        == later_files["broker-get-only.json"],
        "Later broker capture changed",
    )
    if later_state is not None:
        require(
            file_hash(later_state_path) == later_files["paper/state.json"],
            "Later state changed",
        )
    return result
