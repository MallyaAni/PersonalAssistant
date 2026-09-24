"""Receipts preserve actual generated advice without recording raw account inputs."""

import copy
import json
from datetime import timedelta

import pytest

from backend.market import decision_view, personal_history
from backend.tests.test_decision_view import FIRING, setup


# Build the real personal planner's output, not a hand-written advice fixture.
def generated():
    record, snapshot, quoted, now = setup()
    record["written"] = now.isoformat()
    decisions = decision_view.build(
        record,
        [],
        98765.43,
        snapshot,
        quoted,
        now,
        entries=FIRING,
        cash=87654.32,
    )
    return decisions, record, snapshot, now


# Prove the saved projection is exact, independent and excludes unapproved fields.
def test_projection_retains_actual_actions_but_never_account_inputs():
    decisions, record, snapshot, _now = generated()
    decisions["pending_buys"] = ["private-pending-sentinel"]
    decisions["portfolio_allocation"] = {"secret": "allocation-sentinel"}
    decisions["rows"]["S11"]["holdings"] = "private-holdings-sentinel"
    decisions["rows"]["S11"]["quote"]["token"] = "credential-sentinel"
    receipt = personal_history.project(decisions, record, snapshot, FIRING)
    row = receipt["rows"]["S11"]
    for field in personal_history.ROW_FIELDS:
        assert row[field] == decisions["rows"]["S11"][field]
    assert row["action"] == "Buy"
    assert row["band_z"] == 1.5
    assert row["bar"]["price"] == snapshot["quotes"]["S11"]["last"]
    encoded = json.dumps(receipt)
    for forbidden in (
        "98765.43",
        "87654.32",
        "private-pending-sentinel",
        "private-holdings-sentinel",
        "allocation-sentinel",
        "credential-sentinel",
    ):
        assert forbidden not in encoded
    assert len(receipt["record_sha256"]) == 64
    assert all(len(digest) == 64 for digest in receipt["code_fingerprint"].values())
    original = copy.deepcopy(receipt)
    decisions["rows"]["S11"]["action"] = "Sell"
    snapshot["quotes"]["S11"]["last"] = 1
    assert receipt == original


# A blocked Buy must stay distinct from both a funded Buy and a true Hold.
def test_receipt_preserves_blocked_intent_and_original_quote_deadline():
    decisions, record, snapshot, _now = generated()
    decisions["rows"]["S11"].update(
        action="Hold",
        executable=False,
        move_weight=0,
        blocker="available cash is unknown",
    )
    receipt = personal_history.project(decisions, record, snapshot, FIRING)
    row = receipt["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Hold"
    assert row["blocker"] == "available cash is unknown"
    assert (
        row["quote"]["valid_until"] == decisions["rows"]["S11"]["quote"]["valid_until"]
    )


# Acknowledgement cannot outlive executable evidence or a missing deadline.
def test_acknowledgement_window_fails_closed_on_expired_or_missing_evidence():
    decisions, record, snapshot, now = generated()
    payload = personal_history.project(decisions, record, snapshot, FIRING)
    assert personal_history.acknowledgement_deadline(payload, now) == now + timedelta(
        seconds=30
    )
    payload["rows"]["S11"]["valid_until"] = None
    assert personal_history.acknowledgement_deadline(payload, now) == now
    payload["rows"]["S11"]["valid_until"] = (now - timedelta(seconds=1)).isoformat()
    assert personal_history.acknowledgement_deadline(payload, now) < now


# Malformed numbers and undated instants cannot enter an immutable receipt.
def test_projection_rejects_nonfinite_values_and_naive_timestamps():
    decisions, record, snapshot, now = generated()
    decisions["rows"]["S11"]["move_weight"] = float("nan")
    with pytest.raises(ValueError):
        personal_history.project(decisions, record, snapshot, FIRING)
    decisions["as_of"] = now.replace(tzinfo=None).isoformat()
    with pytest.raises(ValueError, match="timezone"):
        personal_history.project(decisions, record, snapshot, FIRING)
