"""Learned targets must never be compared with the incumbent's equal weights."""

from copy import deepcopy

import pytest

from backend.market import grade_led_policy, grade_parity
from backend.tests import test_grade_parity as parity_cases
from backend.tests.test_market_pit_scorecard import NAMES, _report

LAST = parity_cases.LAST


# Reuse the original checker suite's complete membership history.
@pytest.fixture
def full_history(tmp_path):
    return parity_cases.full_history.__wrapped__(tmp_path)


# Build unequal learned sizes with a retained holding in the saved record shape.
def _learned_record(report):
    record = parity_cases._record(report)
    policy = grade_led_policy.POLICY
    model = dict.fromkeys(NAMES, 0.0)
    model["CCC"] = 0.2
    current = {"AAA": 0.25}
    signals = grade_led_policy.signals(report, {"AAA": 25})
    targets, receipt = grade_led_policy.preserve_grade_holdings(
        model, {"current_weights": current}, signals, {"AAA": 1.0}, 100.0
    )
    receipt.update(
        policy=policy,
        session=LAST,
        status="available",
        observed_equity=100.0,
        sizing_model_targets=model,
        grades=dict.fromkeys(NAMES, 3),
    )
    record["targets"] = {"policy": policy, "weights": dict(targets)}
    record["paper"] = {
        "policy": policy,
        "session": LAST,
        "selected_targets": {"policy": policy, "weights": dict(targets)},
        "joint_funded": {
            "policy": policy,
            "as_of": LAST,
            "targets": dict(targets),
            "receipt": receipt,
        },
        "positions": [{"symbol": "AAA", "qty": 25, "market_value": 25.0}],
    }
    return record


# Check learned sizes and account preservation without converting to equal weights.
def test_grade_led_targets_use_the_original_model_and_account_snapshot(full_history):
    report = _report()
    record = _learned_record(report)
    before = deepcopy(record)
    result = grade_parity.compare(record, report, LAST, full_history)
    assert result["ok"]
    assert result["targets_compared"]
    assert result["mismatches"] == []
    assert "not a new model inference" in result["target_basis"]
    assert record == before
    assert record["targets"]["weights"]["AAA"] == 0.25
    assert record["targets"]["weights"]["CCC"] == 0.2


# A modified chart target remains a failure even when all grade letters still agree.
def test_grade_led_display_target_corruption_is_detected(full_history):
    report = _report()
    record = _learned_record(report)
    record["targets"]["weights"]["CCC"] += 0.01
    result = grade_parity.compare(record, report, LAST, full_history)
    assert not result["ok"]
    assert result["targets_compared"]
    assert result["mismatches"][0]["ticker"] == "CCC"
    assert result["mismatches"][0]["replay"] == 0.2


# Later broker marks cannot replace the model's original observed holding weights.
def test_later_broker_mark_does_not_reprice_the_recorded_proposal(full_history):
    report = _report()
    record = _learned_record(report)
    record["paper"]["positions"][0]["market_value"] = 25.01
    result = grade_parity.compare(record, report, LAST, full_history)
    assert result["ok"]
    assert result["targets_compared"]


# Missing or stale evidence fails instead of silently bypassing target checks.
@pytest.mark.parametrize(
    "broken", ["receipt", "session", "model", "holding", "selection", "grade"]
)
def test_grade_led_receipt_corruption_fails_closed(full_history, broken):
    report = _report()
    record = _learned_record(report)
    allocation = record["paper"]["joint_funded"]
    if broken == "receipt":
        allocation.pop("receipt")
    elif broken == "session":
        allocation["as_of"] = "2024-03-21"
    elif broken == "model":
        allocation["receipt"]["sizing_model_targets"]["CCC"] = float("nan")
    elif broken == "holding":
        allocation["receipt"]["current_weights"]["AAA"] = 0.1
    elif broken == "selection":
        record["paper"]["selected_targets"]["weights"]["CCC"] = 0.1
    else:
        allocation["receipt"]["grades"]["CCC"] = 1
    result = grade_parity.compare(record, report, LAST, full_history)
    assert not result["ok"]
    assert not result["targets_compared"]
    assert result["mismatches"][0]["kind"] == grade_parity.TARGETS


# Independent grade replay still rejects a wrong visible letter.
def test_grade_led_grade_mismatch_stays_visible(full_history):
    report = _report()
    record = _learned_record(report)
    record["grades"]["CCC"]["grade"] = "B"
    result = grade_parity.compare(record, report, LAST, full_history)
    assert not result["ok"]
    assert any(row["kind"] == grade_parity.GRADE for row in result["mismatches"])
