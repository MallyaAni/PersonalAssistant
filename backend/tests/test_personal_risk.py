"""Check personal scenario sizing without introducing a new strategy signal."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.market.personal_risk import build

NOW = datetime(2026, 9, 24, 14, 15, tzinfo=UTC)


# Build one dated, explicitly funded risk scenario for boundary comparisons.
def scenario(**changes):
    inputs = dict(
        entry_price=100.0,
        support_distance=0.05,
        resistance_distance=0.10,
        current_weight=0.02,
        policy_max_add_weight=0.15,
        observed_at=NOW - timedelta(seconds=10),
        valid_until=NOW + timedelta(seconds=10),
        now=NOW,
        fresh=True,
        risk_budget_pct=0.5,
    )
    inputs.update(changes)
    return build(**inputs)


# Existing exposure consumes the account's risk allowance before an addition.
def test_budget_applies_to_whole_position_and_reports_percentage_units():
    result = scenario()
    assert result["status"] == "available"
    assert result["entry"] == 100
    assert result["reference_support"] == 95
    assert result["reference_resistance"] == pytest.approx(110)
    assert result["risk_pct"] == 5
    assert result["reward_pct"] == 10
    assert result["reward_risk_ratio"] == 2
    assert result["max_add_weight"] == pytest.approx(0.08)


# A missing user budget never silently changes the existing entry size.
def test_no_budget_is_informational_only():
    result = scenario(risk_budget_pct=None)
    assert result["status"] == "budget_required"
    assert result["max_add_weight"] is None
    assert result["reward_risk_ratio"] == 2


# No resistance means unknown reward, not an invented target or infinite ratio.
@pytest.mark.parametrize("distance", [None, float("nan"), 0, -0.1])
def test_missing_overhead_reference_blocks_opt_in_sizing(distance):
    result = scenario(resistance_distance=distance)
    assert result["status"] == "unavailable"
    assert result["max_add_weight"] == 0
    assert result["reward_risk_ratio"] is None
    assert result["reference_resistance"] is None


# Neither stale market evidence nor a future observation can produce a risk cap.
@pytest.mark.parametrize(
    "changes",
    [
        {"fresh": False},
        {"fresh": 1},
        {"observed_at": NOW + timedelta(seconds=1)},
        {"valid_until": NOW},
        {"now": NOW.replace(tzinfo=None)},
        {"observed_at": None},
    ],
)
def test_freshness_is_enforced(changes):
    result = scenario(**changes)
    assert result["status"] == "unavailable"
    assert result["max_add_weight"] == 0


# Malformed account values and impossible price references fail closed.
@pytest.mark.parametrize(
    "changes",
    [
        {"risk_budget_pct": 0},
        {"risk_budget_pct": -1},
        {"risk_budget_pct": 101},
        {"risk_budget_pct": float("nan")},
        {"risk_budget_pct": True},
        {"risk_budget_pct": "0.5"},
        {"current_weight": -0.01},
        {"current_weight": 1.01},
        {"policy_max_add_weight": -0.1},
        {"policy_max_add_weight": 2},
        {"entry_price": 0},
        {"entry_price": float("inf")},
        {"support_distance": 0},
        {"support_distance": 1},
        {"support_distance": float("nan")},
        {"resistance_distance": float("inf")},
        {"entry_price": 1e308, "resistance_distance": 10},
    ],
)
def test_invalid_inputs_never_escape_as_nonfinite_json(changes):
    result = scenario(**changes)
    assert result["status"] == "unavailable"
    assert result["max_add_weight"] == 0
    json.dumps(result, allow_nan=False)


# A positive scenario does not override the existing strategy limit.
def test_policy_cap_and_already_used_budget_win():
    assert scenario(policy_max_add_weight=0.01)["max_add_weight"] == 0.01
    assert scenario(current_weight=0.12)["max_add_weight"] == 0


# Risk/reward remains descriptive rather than imposing a newly fitted threshold.
def test_low_reward_ratio_does_not_create_a_new_entry_gate():
    result = scenario(resistance_distance=0.01)
    assert result["status"] == "available"
    assert result["reward_risk_ratio"] == pytest.approx(0.2)
    assert result["max_add_weight"] == pytest.approx(0.08)


# Scale-invariant distances yield equivalent position limits at any raw price.
def test_price_scale_changes_references_without_changing_the_risk_cap():
    first, second = scenario(), scenario(entry_price=10)
    assert second["reference_support"] == first["reference_support"] / 10
    assert second["reference_resistance"] == pytest.approx(
        first["reference_resistance"] / 10
    )
    assert second["max_add_weight"] == first["max_add_weight"]
    assert second["reward_risk_ratio"] == first["reward_risk_ratio"]
