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


# Put the board on the active equal-weight policy (`live_policy.ACTIVE`) with
# S11's close grade A and a fresh intraday reading that downgrades it to B.
def close_grade_policy(record, snapshot):
    from backend.agents.trading.desk import live_policy

    record["targets"] = {
        "policy": live_policy.ACTIVE,
        "weights": {
            symbol: 0.1 if symbol == "S11" else 0 for symbol in record["grades"]
        },
    }
    record["grades"]["S11"]["grade"] = "A"
    record["grades"]["S11"]["stances"]["sentiment"] = 0
    record["levels"] = {"S11": {"rejecting_band": False}}
    snapshot["technical"]["S11"].update(now=0.1, stance=-1)


# Keep the close-based action grade distinct from its intraday reading.
def test_active_receipt_keeps_close_grade_separate_from_intraday_reading():
    record, snapshot, quoted, now = setup()
    record["written"] = now.isoformat()
    close_grade_policy(record, snapshot)
    decisions = decision_view.build(
        record, [], 98765.43, snapshot, quoted, now, entries=FIRING, cash=87654.32
    )
    decision = decisions["rows"]["S11"]
    assert decision["grade"] == "A"
    assert decision["grade_intraday"] == "B"
    receipt = personal_history.project(decisions, record, snapshot, FIRING)
    row = receipt["rows"]["S11"]
    assert row["grade"] == decision["grade"]
    assert row["grade_intraday"] == decision["grade_intraday"]
    assert row["grade_basis"] == "recorded_close"
    assert row["grade_session"] == record["session"]
    assert row["grade_intraday_bar_at"] == snapshot["quotes"]["S11"]["bar"]
    assert row["grade_intraday_as_of"] == snapshot["as_of"]
    assert row["grade_intraday_valid_until"] == "2026-09-14T14:15:00+00:00"
    assert receipt["schema_version"] == "personal-decision-receipt/2"


# Keep explicit missing `/4` evidence missing without recalculating another decision.
@pytest.mark.parametrize("missing", ["grade", "grade_intraday"])
def test_stamped_grades_are_not_recomputed_or_backfilled(missing, monkeypatch):
    from backend.market import holdings

    record, snapshot, quoted, now = setup()
    close_grade_policy(record, snapshot)
    decisions = decision_view.build(
        record, [], 98765.43, snapshot, quoted, now, entries=FIRING, cash=87654.32
    )
    decisions["rows"]["S11"][missing] = None

    # Record the accepted `/4` judgement without running the analyst again.
    def forbid_regrading(*args):
        raise AssertionError("Receipt must not recompute stamped decision grades")

    monkeypatch.setattr(holdings, "live_grades", forbid_regrading)
    row = personal_history.project(decisions, record, snapshot, FIRING)["rows"]["S11"]
    assert row[missing] is None
    if missing == "grade":
        assert row["grade_basis"] == "unavailable"
        assert row["grade_session"] is None
        assert row["grade_intraday"] == "B"
    else:
        assert row["grade"] == "A"
        assert row["grade_basis"] == "recorded_close"
        assert row["grade_intraday_bar_at"] is None
        assert row["grade_intraday_as_of"] is None
        assert row["grade_intraday_valid_until"] is None


# Preserve the older planner's live-first grade selection and identify its basis.
@pytest.mark.parametrize("stale", [False, True])
def test_unstamped_planner_keeps_its_existing_grade_selection(stale):
    from backend.market import desk_freshness, holdings

    decisions, record, snapshot, now = generated()
    if stale:
        snapshot["as_of"] = (now - timedelta(hours=1)).isoformat()
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    live = holdings.live_grades(record, technical, value)
    expected = (live.get("S11") or {}).get("grade_live") or record["grades"]["S11"][
        "grade"
    ]
    row = personal_history.project(decisions, record, snapshot, FIRING)["rows"]["S11"]
    assert row["grade"] == expected
    assert row["grade_basis"] == ("recorded_close" if stale else "intraday")
    assert row["grade_session"] == (record["session"] if stale else None)
    assert row["grade_intraday"] == (None if stale else expected)
    assert "timing" not in row
    assert "structure_gate" not in row


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
