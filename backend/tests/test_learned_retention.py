"""Acceptance of causal B retention without trading or model fitting."""

import numpy as np
import pytest

from backend.market.learned_retention import plan_retention, reset_targets


# Supply one held B and two A destinations on a fully funded account grid.
def inputs():
    return {
        "grades": np.array([1, 2, 3]),
        "eligible": np.ones(3, dtype=bool),
        "prices": np.array([10.0, 20.0, 25.0]),
        "held": np.array([10.0, 10.0, 0.0]),
        "nav": 1000.0,
        "forecasts": np.array([0.02, 0.01, 0.01]),
        "recipient_weights": np.array([0.0, 0.5, 0.5]),
        "hard_cap": 0.25,
        "cost_bps": 10.0,
    }


# Retain only the owned B quantity while buy blocking excludes new B purchases.
def test_blocked_b_can_be_held_without_becoming_a_buy():
    data = inputs()
    data["blocked"] = np.array([True, False, False])
    plan = plan_retention(**data)
    np.testing.assert_array_equal(plan.retained_shares, [10, 0, 0])
    np.testing.assert_array_equal(plan.buy_eligible, [False, True, True])
    assert plan.reasons[0] == "retain"
    np.testing.assert_array_equal(data["held"], [10, 10, 0])


# Preserve a retained B across resets and cap the remaining A composition.
def test_reset_reserves_b_and_leaves_cap_excess_in_cash():
    plan = plan_retention(**inputs())
    targets = reset_targets([0.0, 0.25, 0.25], plan, hard_cap=0.25)
    np.testing.assert_allclose(targets, [0.1, 0.25, 0.25])
    assert targets.sum() == pytest.approx(0.6)
    np.testing.assert_array_equal(plan.retained_shares, [10, 0, 0])


# Switching fees can make retention preferable despite a weaker gross forecast.
def test_exact_two_leg_fees_have_correct_sign():
    data = inputs()
    data["forecasts"] = np.array([0.0, 0.001, 0.001])
    data["cost_bps"] = 0
    assert not plan_retention(**data).retain_mask[0]
    data["cost_bps"] = 10
    plan = plan_retention(**data)
    expected = -0.001 - np.log(0.999 / 1.001)
    assert plan.edge[0] == pytest.approx(expected)
    assert plan.retain_mask[0]


# Keep a losing forecast when the declared replacement basket is worse.
def test_negative_return_does_not_force_sale_if_alternative_is_worse():
    data = inputs()
    data["forecasts"] = np.array([-0.02, -0.04, -0.03])
    plan = plan_retention(**data)
    expected = -0.02 - np.log(
        0.999 / 1.001 * (0.5 * np.exp(-0.04) + 0.5 * np.exp(-0.03))
    )
    assert plan.edge[0] == pytest.approx(expected)
    assert plan.retain_mask[0]


# Missing or invalid forecasts retain baseline exits rather than inventing an edge.
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_missing_held_forecast_falls_back(value):
    data = inputs()
    data["forecasts"][0] = value
    plan = plan_retention(**data)
    assert not plan.retain_mask[0]
    assert plan.reasons[0] == "forecast_unavailable"


# Never renormalize around a missing or prohibited destination forecast.
@pytest.mark.parametrize(
    "failure", ["forecast", "price", "grade", "blocked", "eligible"]
)
def test_unavailable_destination_is_not_dropped(failure):
    data = inputs()
    if failure == "forecast":
        data["forecasts"][2] = np.nan
    elif failure == "price":
        data["prices"][2] = np.nan
    elif failure == "grade":
        data["grades"][2] = 1
    elif failure == "blocked":
        data["blocked"] = np.array([False, False, True])
    else:
        data["eligible"][2] = False
    plan = plan_retention(**data)
    assert not plan.retain_mask[0]
    assert plan.reasons[0] == "destination_unavailable"


# Cash comparisons require an absolute return forecast rather than relative-SPY alone.
def test_cash_destination_requires_spy_and_does_not_false_hold():
    data = inputs()
    data["recipient_weights"] = np.zeros(3)
    data["forecasts"][0] = 0.01
    plan = plan_retention(**data)
    assert plan.reasons[0] == "cash_forecast_unavailable"
    data["spy_forecast"] = -0.05
    plan = plan_retention(**data)
    assert not plan.retain_mask[0]
    assert plan.edge[0] == pytest.approx(-0.04 - np.log(0.999))
    data["spy_forecast"] = 0.01
    assert plan_retention(**data).retain_mask[0]


# Cash residues incur only a sell fee while invested proceeds incur both fees.
def test_partial_cash_uses_exact_mixture_wealth():
    data = inputs()
    data["recipient_weights"] = np.array([0.0, 0.3, 0.2])
    data["spy_forecast"] = -0.02
    plan = plan_retention(**data)
    replacement = 0.999 * (0.5 * np.exp(-0.01) / 1.001 + 0.5)
    assert plan.edge[0] == pytest.approx(0.0 - np.log(replacement))


# Mandatory thesis and event exits always defeat a favorable retention forecast.
@pytest.mark.parametrize("key", ["event_exits", "thesis_exits"])
def test_mandatory_exits_preserved(key):
    data = inputs()
    data[key] = np.array([True, False, False])
    plan = plan_retention(**data)
    assert not plan.retain_mask[0]
    assert plan.reasons[0] == "mandatory_exit"


# The planner never retains C, unheld B, or B lacking declared eligibility.
@pytest.mark.parametrize("failure", ["C", "unheld", "eligibility"])
def test_only_eligible_held_b_can_be_retained(failure):
    data = inputs()
    if failure == "C":
        data["grades"][0] = 0
    elif failure == "unheld":
        data["held"][0] = 0
    else:
        data["eligible"][0] = False
    assert not plan_retention(**data).retain_mask[0]


# Explicit cap trims never increase whole or fractional units.
def test_declared_cap_trim_is_bounded_and_whole_share_aware():
    data = inputs()
    data["held"][0] = 30
    data["prices"][0] = 11
    assert plan_retention(**data).reasons[0] == "hard_cap_requires_trim"
    data["trim_to_cap"] = True
    plan = plan_retention(**data)
    assert plan.retained_shares[0] == pytest.approx(250 / 11)
    data["whole_shares"] = True
    plan = plan_retention(**data)
    assert plan.retained_shares[0] == 22
    assert plan.retained_weights[0] <= 0.25
    data["held"][0] = 5
    assert plan_retention(**data).retained_shares[0] == 5


# Invalid account and destination representations fail before any decision is returned.
@pytest.mark.parametrize(
    "failure", ["nav", "held_price", "negative_held", "weight", "mask", "text", "whole"]
)
def test_invalid_account_inputs_rejected(failure):
    data = inputs()
    if failure == "nav":
        data["nav"] = 100
    elif failure == "held_price":
        data["prices"][0] = np.nan
    elif failure == "negative_held":
        data["held"][0] = -1
    elif failure == "weight":
        data["recipient_weights"] = np.array([0.0, 0.7, 0.7])
    elif failure == "mask":
        data["eligible"] = np.ones(3, dtype=int)
    elif failure == "text":
        data["held"] = ["10", "10", "0"]
    else:
        data["held"][0] = 1.5
        data["whole_shares"] = True
    with pytest.raises(ValueError, match="NAV|prices|holdings|weights|mask|array"):
        plan_retention(**data)


# Reset proposals cannot purchase B or consume a budget smaller than retained holdings.
def test_reset_rejects_b_additions_and_insufficient_budget():
    plan = plan_retention(**inputs())
    with pytest.raises(ValueError, match="A/A"):
        reset_targets([0.1, 0.25, 0.25], plan, hard_cap=0.25)
    with pytest.raises(ValueError, match="budget"):
        reset_targets([0.0, 0.25, 0.25], plan, hard_cap=0.25, stock_budget=0.05)


# Distinct B intentions keep their own declared replacement rows.
def test_per_position_recipient_rows_are_preserved():
    data = inputs()
    data["grades"] = np.array([1, 1, 2])
    data["forecasts"] = np.array([0.02, -0.02, 0.01])
    data["recipient_weights"] = np.array(
        [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]]
    )
    plan = plan_retention(**data)
    np.testing.assert_array_equal(plan.retain_mask, [True, False, False])


# Very large finite forecasts compare in log units without exponential overflow.
def test_extreme_finite_forecasts_do_not_overflow():
    data = inputs()
    data["forecasts"] = np.array([1000.01, 1000.0, 1000.0])
    plan = plan_retention(**data)
    assert np.isfinite(plan.edge[0])
    assert plan.retain_mask[0]


# Reject a modified planning result that would add shares to a reserved holding.
def test_reset_rechecks_reserved_purchase_exclusion():
    plan = plan_retention(**inputs())
    plan.buy_eligible[0] = True
    with pytest.raises(ValueError, match="excluded from purchases"):
        reset_targets([0.2, 0.2, 0.2], plan, hard_cap=0.25)


# Refuse inconsistent reserved weights instead of inventing an unheld position.
def test_reset_rechecks_held_quantity_identity():
    plan = plan_retention(**inputs())
    plan.retained_shares[0] = 0
    with pytest.raises(ValueError, match="must be held"):
        reset_targets([0.0, 0.25, 0.25], plan, hard_cap=0.25)
