"""Saved-only fill/account reconciliation and unaltered original evidence."""

import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.cli import market_execution_reconciliation as cli
from backend.market import execution_reconciliation_audit as audit


# Supply a saved synthetic exit with separate sizing, snapshot and broker clocks.
def documents():
    positions = [
        {"symbol": "AAA", "qty": 12, "current_price": 101, "market_value": 1212},
        {"symbol": "BBB", "qty": 8, "current_price": 99, "market_value": 792},
    ]
    execution = {
        "decision_at": "2026-10-13T19:46:40.304631-04:00",
        "created_at": "2026-10-13T23:46:44.596904903Z",
        "submitted_at": "2026-10-13T23:46:44.596904903Z",
        "reference_price": 100,
        "time_in_force": "day",
    }
    order = {
        "symbol": "AAA",
        "side": "sell",
        "qty": 12,
        "client_order_id": "original-exit-id",
        "execution": dict(execution),
    }
    receipt = {
        "policy": "grade-led-learned-sizing/1",
        "session": "2026-10-13",
        "status": "available",
        "observed_equity": 2100,
        "observed_cash": 100,
        "current_weights": {"AAA": 1200 / 2100, "BBB": 800 / 2100},
        "targets": {"AAA": 0, "BBB": 800 / 2100},
        "grade_signals": {"AAA": {"action": "sell"}, "BBB": {"action": "hold"}},
        "company_exits": ["AAA"],
        "grade_preserved_holdings": ["BBB"],
        "execution_timing": {"orders": {"original-exit-id": "next_open"}},
        "execution": {"missing": [], "blocked": []},
    }
    paper = {
        "policy": receipt["policy"],
        "session": receipt["session"],
        "equity": 2100,
        "cash": 100,
        "positions": positions,
        "orders": [order],
        "planned": [],
        "joint_funded": {
            "policy": receipt["policy"],
            "targets": dict(receipt["targets"]),
            "receipt": receipt,
        },
    }
    record = {
        "session": "2026-10-13",
        "paper": paper,
        "provenance": {"code_revision": "synthetic-source"},
        "grade_parity": {
            "date": "2026-10-13",
            "ok": False,
            "mismatches": [{"kind": "targets"}],
        },
    }
    state = {
        "pending": [
            {**order, "session": "2026-10-13", "execution_timing": "next_open"}
        ],
        "history": [{"session": "2026-10-13", "positions": copy.deepcopy(positions)}],
        "journal": [],
    }
    queued = {
        **order,
        "created_at": execution["created_at"],
        "qty": "12",
        "submitted_at": execution["submitted_at"],
        "filled_at": None,
        "filled_qty": "0",
        "status": "accepted",
        "filled_avg_price": None,
    }
    before = {
        "clock": {"timestamp": "2026-10-14T00:02:19+00:00"},
        "account": {"cash": 100},
        "positions": copy.deepcopy(positions),
        "open_orders": [queued],
    }
    filled = {
        **queued,
        "status": "filled",
        "filled_qty": "12",
        "filled_avg_price": "99.12",
        "created_at": "2026-10-13T23:46:44.596905Z",
        "submitted_at": "2026-10-14T08:00:28.163303Z",
        "filled_at": "2026-10-14T13:32:46.922719Z",
    }
    later = {
        "clock": {"timestamp": "2026-10-14T23:49:30+00:00"},
        "account": {"cash": 1289.44},
        "positions": [dict(positions[1])],
        "orders": [filled],
    }
    close_receipt = {
        "identity": {
            "published_at": "2026-10-13T19:46:40.294838-04:00",
            "expires_at": "2026-10-14T09:30:00-04:00",
        }
    }
    return record, state, before, later, close_receipt


# Verify actual saved quantities while keeping original failed parity and timing gaps.
def test_saved_exit_conserves_quantity_without_claiming_learned_timing():
    saved = documents()
    before = copy.deepcopy(saved)
    result = audit.audit_documents(*saved, later_state=saved[1])
    assert saved == before
    assert result["status"] == "VERIFIED_SAVED_ORDER_AND_QUANTITY_RECONCILIATION"
    assert result["account"]["positions"] == "VERIFIED_SAVED_QUANTITY_DELTA"
    assert result["account"]["cash"] == "CONSISTENT_TO_BROKER_CENTS"
    assert (
        result["account"]["cash_from_aggregate_fills_before_unobserved_fees"]
        == "1289.44"
    )
    assert result["orders"][0]["original_qty"] == 12
    assert result["orders"][0]["filled_qty"] == "12"
    assert result["orders"][0]["learned_timing"] == "NOT_EXERCISED_COMPANY_EXIT"
    assert result["learned_intraday_path"] == "UNVERIFIED_NOT_EXERCISED"
    assert result["original_parity"] == {"ok": False, "mismatches": 1}
    assert (
        "ORIGINAL_PENDING_RETAINED"
        in result["durable_reconciliation"]["original-exit-id"]
    )


# Preserve original clocks separately from later broker rounding and submission.
def test_original_created_timestamp_is_not_replaced_by_later_broker_precision():
    result = audit.audit_documents(*documents())
    row = result["orders"][0]
    assert row["original_created_at"] == "2026-10-13T23:46:44.596904903Z"
    assert row["broker_created_at"] == "2026-10-13T23:46:44.596905Z"
    assert row["original_submitted_at"].startswith("2026-10-13")
    assert row["broker_submitted_at"].startswith("2026-10-14")
    assert row["filled_at"].startswith("2026-10-14")


# Derive reference prices from original receipt marks and quantities.
def test_later_prices_cannot_reprice_original_decision():
    saved = documents()
    saved[3]["positions"][0].update(current_price=9999, market_value=79992)
    result = audit.audit_documents(*saved)
    assert float(result["sizing_marks"]["AAA"]) == pytest.approx(100)
    assert result["later_snapshot_mark_substitution"] is False
    assert result["orders"][0]["original_reference_price"] == 100


# Reject changed source quantities, clocks, target links and later share outcomes.
@pytest.mark.parametrize(
    ("part", "path", "value"),
    [
        (0, ("paper", "orders", 0, "qty"), 11),
        (0, ("paper", "joint_funded", "receipt", "status"), "unavailable"),
        (0, ("paper", "joint_funded", "targets", "AAA"), 0.25),
        (1, ("pending", 0, "execution_timing"), "intraday"),
        (1, ("pending", 0, "execution", "reference_price"), 100.5),
        (2, ("open_orders", 0, "filled_qty"), "12"),
        (3, ("orders", 0, "symbol"), "OTHER"),
        (3, ("orders", 0, "qty"), "11"),
        (3, ("orders", 0, "filled_at"), "2026-10-13T13:32:46Z"),
        (3, ("orders", 0, "created_at"), "2026-10-13T23:46:45Z"),
        (3, ("positions", 0, "qty"), 9),
    ],
)
def test_saved_receipt_tampering_is_rejected(part, path, value):
    saved = documents()
    container = saved[part]
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value
    with pytest.raises(ValueError, match="differs|required|relabelled"):
        audit.audit_documents(*saved)


# Keep missing broker outcomes unknown despite a position disappearing.
def test_missing_later_broker_receipt_is_not_a_fill():
    saved = documents()
    saved[3]["orders"] = []
    result = audit.audit_documents(*saved)
    assert result["status"] == "UNVERIFIED_INCOMPLETE_BROKER_OUTCOME"
    assert result["orders"][0]["filled_qty"] is None
    assert result["account"]["positions"] == "UNVERIFIED_MISSING_ORDER_OUTCOME"


# Distinguish unexplained cash movement from fees that were never observed.
def test_cash_difference_remains_an_unresolved_activity_gap():
    saved = documents()
    saved[3]["account"]["cash"] += 100
    result = audit.audit_documents(*saved)
    assert result["account"]["cash"] == "UNEXPLAINED_CASH_DIFFERENCE"
    assert result["account"]["fees_transfers_corporate_actions"].startswith(
        "UNVERIFIED"
    )


# Do not promote a routed intraday order to proof without its authenticated forecast.
def test_intraday_label_alone_does_not_prove_a_model_decision():
    saved = documents()
    receipt = saved[0]["paper"]["joint_funded"]["receipt"]
    receipt["company_exits"] = []
    receipt["execution_timing"]["orders"]["original-exit-id"] = "intraday"
    saved[1]["pending"][0]["execution_timing"] = "intraday"
    result = audit.audit_documents(*saved)
    assert result["learned_intraday_path"].startswith(
        "UNVERIFIED_REQUIRES_AUTHENTICATED"
    )
    assert result["orders"][0]["learned_timing"] == "UNVERIFIED_NO_LINKED_OBSERVATION"


# Build explicit synthetic saved capture files for the independently executable CLI.
def captures(tmp_path):
    record, state, before, later, close_receipt = documents()
    original, following = tmp_path / "original", tmp_path / "later"
    original.mkdir()
    following.mkdir()
    config = {"policy": record["paper"]["policy"]}
    payloads = {
        "paper/state.json": state,
        "broker-get-only.json": before,
        "observation/close.json": close_receipt,
        "desk/learned-holding/config.json": config,
        "desk/grade_parity.json": {"rows": [record["grade_parity"]]},
    }
    hashes = {}
    for name, value in payloads.items():
        path = original / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        hashes[name] = audit.file_hash(path)
    record["paper"]["learned_holding"] = {
        "close_receipt_sha256": hashes["observation/close.json"],
        "config_sha256": hashes["desk/learned-holding/config.json"],
    }
    path = original / "desk/asof=2026-10-13/desk.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    hashes[str(path.relative_to(original))] = audit.file_hash(path)
    path = original / "learned_inputs/asof=2026-10-13.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps({"record_sha256": hashes["desk/asof=2026-10-13/desk.json"]})
    )
    hashes[str(path.relative_to(original))] = audit.file_hash(path)
    (original / "observation-proof.json").write_text(
        json.dumps({"files_sha256": hashes, "ordinary_session": "2026-10-13"})
    )
    (following / "broker-get-only.json").write_text(json.dumps(later))
    (following / "observation-proof.json").write_text(
        json.dumps(
            {
                "files_sha256": {
                    "broker-get-only.json": audit.file_hash(
                        following / "broker-get-only.json"
                    )
                },
                "missing_original_records": {"desk/asof=2026-10-14/desk.json": True},
            }
        )
    )
    return SimpleNamespace(
        original_root=original,
        later_root=following,
        original_proof_sha256=audit.file_hash(original / "observation-proof.json"),
        later_proof_sha256=audit.file_hash(following / "observation-proof.json"),
        output=tmp_path / "proof.json",
    )


# Run the actual CLI lifecycle while preserving every original byte and absent record.
def test_cli_saved_capture_acceptance_and_fresh_output(tmp_path):
    args = captures(tmp_path)
    hashes = {path: audit.file_hash(path) for path in tmp_path.rglob("*.json")}
    result = cli.verify(args)
    assert args.output.is_file()
    assert result["original_parity"]["ok"] is False
    assert result["later_capture_missing_records"] == {
        "desk/asof=2026-10-14/desk.json": True
    }
    assert all(audit.file_hash(path) == value for path, value in hashes.items())
    with pytest.raises(ValueError, match="Fresh proof"):
        cli.verify(args)


# Refuse modified captured inputs even when their altered JSON still parses.
def test_original_byte_tamper_is_rejected(tmp_path):
    args = captures(tmp_path)
    (args.original_root / "paper/state.json").write_text("{}")
    with pytest.raises(ValueError, match="Original capture differs"):
        cli.verify(args)
    assert not args.output.exists()


# Reject proof output inside a capture, symlink escapes and invalid numeric evidence.
def test_read_only_boundaries_and_bad_numeric_values(tmp_path):
    args = captures(tmp_path)
    args.output = args.original_root / "new-proof.json"
    with pytest.raises(ValueError, match="outside"):
        cli.verify(args)
    with pytest.raises(ValueError, match="Unsafe"):
        audit.evidence_path(args.original_root, "../outside")
    for value in (True, "NaN", "Infinity", None):
        with pytest.raises(ValueError, match="numeric|Numeric"):
            audit.number(value)


# Check that this verifier cannot call senders, planners or inference services.
def test_audit_has_no_runtime_trading_or_inference_dependencies():
    tree = ast.parse(Path(audit.__file__).read_text())
    forbidden = {
        "alpaca_trading",
        "market_daily",
        "intraday_orders",
        "learned_live_holding",
        "forward_probability_timing",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not forbidden.intersection((node.module or "").split("."))
        if isinstance(node, ast.Call):
            assert getattr(node.func, "attr", "") not in {
                "submit_market",
                "save_state",
                "run_account",
                "prepare",
                "predict",
            }
