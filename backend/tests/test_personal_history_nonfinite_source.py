"""Legacy source values may be fingerprinted, but never admitted into advice."""

import hashlib
import json
import math

import pytest

from backend.market import personal_history
from backend.tests.test_decision_view import FIRING
from backend.tests.test_personal_history import generated


# An unrelated legacy missing close must not prevent recording valid generated advice.
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_source_only_is_hashed_without_changing_advice(value):
    decisions, record, snapshot, _now = generated()
    record["levels"] = {"Q": {"last_close": value}}
    before = json.dumps(record, sort_keys=True, allow_nan=True)
    receipt = personal_history.project(decisions, record, snapshot, FIRING)
    assert receipt["record_sha256"] == hashlib.sha256(before.encode()).hexdigest()
    for field in personal_history.ROW_FIELDS:
        assert receipt["rows"]["S11"][field] == decisions["rows"]["S11"][field]
    json.dumps(receipt, allow_nan=False)
    assert json.dumps(record, sort_keys=True, allow_nan=True) == before
    assert not math.isfinite(record["levels"]["Q"]["last_close"])


# Keep valid source fingerprints byte-for-byte compatible with saved receipts.
def test_finite_source_hash_keeps_existing_serialization():
    decisions, record, snapshot, _now = generated()
    expected = hashlib.sha256(
        json.dumps(record, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    receipt = personal_history.project(decisions, record, snapshot, FIRING)
    assert receipt["record_sha256"] == expected


# Absent, null, special floats, literal strings and zero remain distinct source states.
def test_source_hash_does_not_conflate_missing_null_nonfinite_or_zero():
    decisions, record, snapshot, _now = generated()
    alternatives = [
        {},
        *(
            {"last_close": value}
            for value in (
                None,
                float("nan"),
                float("inf"),
                -float("inf"),
                0.0,
                "NaN",
                "Infinity",
            )
        ),
    ]
    digests = []
    for level in alternatives:
        record["levels"] = {"Q": level}
        receipt = personal_history.project(decisions, record, snapshot, FIRING)
        digests.append(receipt["record_sha256"])
    assert len(set(digests)) == len(alternatives)


# Nonfinite numbers in actual retained evidence or advice still fail strict projection.
@pytest.mark.parametrize("field", ["move", "quote", "bar", "band", "risk", "event"])
def test_nonfinite_retained_outputs_still_reject(field):
    decisions, record, snapshot, _now = generated()
    record["levels"] = {"Q": {"last_close": float("nan")}}
    entries = dict(FIRING)
    if field == "move":
        decisions["rows"]["S11"]["move_weight"] = float("nan")
    elif field == "quote":
        decisions["rows"]["S11"]["quote"]["bid"] = float("inf")
    elif field == "bar":
        snapshot["quotes"]["S11"]["last"] = float("nan")
    elif field == "band":
        entries["S11"] = float("nan")
    elif field == "risk":
        decisions["rows"]["S11"]["risk_plan"] = {"risk_pct": float("inf")}
    else:
        record["event_risk"] = {"factor": float("nan")}
    with pytest.raises(ValueError, match="Out of range float"):
        personal_history.project(decisions, record, snapshot, entries)
