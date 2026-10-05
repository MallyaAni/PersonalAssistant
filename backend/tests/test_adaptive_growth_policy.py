"""Actual convex solves verify causal risk sizing and funded position boundaries."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import adaptive_growth_policy as model


# Build deterministic complete historical returns with unequal stock risks.
def inputs():
    rng = np.random.default_rng(12)
    returns = rng.normal(size=(252, 4)) * [0.015, 0.035, 0.02, 0.01]
    history = 100 * np.exp(np.vstack((np.zeros(4), np.cumsum(returns, axis=0))))
    cov = model.covariance(history[:, :2])
    means = np.array([0.0001, 0.0001, 0.0, 0.0])
    means[:2] -= 0.5 * np.diag(cov)
    return {
        "history": history,
        "grades": np.array([2, 3, 2, 2]),
        "eligible": np.ones(4, dtype=bool),
        "means": means,
        "current_weights": np.zeros(4),
        "cash_weight": 1.0,
        "cost_bps": 0,
        "benchmark_indices": np.array([2, 3]),
    }


# Supply simultaneous holding scenarios without implying authenticated model quality.
def distribution_inputs(scenarios, *, current=None, cash=1.0, cost=0):
    values = np.asarray(scenarios, dtype=float)
    size = values.shape[1]
    return {
        "scenarios": values,
        "probabilities": np.full(len(values), 1 / len(values)),
        "grades": np.full(size, 2),
        "eligible": np.ones(size, dtype=bool),
        "current_weights": np.zeros(size) if current is None else np.array(current),
        "cash_weight": cash,
        "cost_bps": cost,
        "benchmark_indices": np.array([], dtype=int),
        "horizon": "next_open_to_following_open_arithmetic_return",
    }


# Equal win rates with different adverse outcomes must receive different funded sizes.
def test_joint_distribution_sizes_losses_instead_of_multiplying_probability():
    data = distribution_inputs([[0.03, 0.03], [-0.01, -0.05]])
    target, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "optimized"
    assert receipt["certificate"]["certified"]
    assert target[0] == model.CAP
    assert target[1] == 0
    assert receipt["estimated_positive_return_probability"] == [0.5, 0.5]
    assert not receipt["probability_guarantee"]


# Simultaneous diversified outcomes support more exposure than identical loss paths.
def test_joint_distribution_retains_cross_stock_dependence():
    correlated = distribution_inputs([[0.1, 0.1], [-0.098, -0.098]])
    diversified = distribution_inputs([[0.1, -0.098], [-0.098, 0.1]])
    first, _ = model.allocate_distribution(**correlated)
    second, receipt = model.allocate_distribution(**diversified)
    assert receipt["status"] == "optimized"
    assert second.sum() > first.sum()
    np.testing.assert_allclose(second, [model.CAP, model.CAP], atol=1e-10)


# Remaining expected utility can keep or exit a B holding without permission to add.
@pytest.mark.parametrize(
    ("outcomes", "expected"), [([[0.03], [0.01]], 0.2), ([[-0.01], [-0.03]], 0)]
)
def test_joint_distribution_retention_and_profit_exit(outcomes, expected):
    data = distribution_inputs(outcomes, current=[0.2], cash=0.8)
    data["grades"][0] = 1
    target, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "optimized"
    assert target[0] == expected
    assert not receipt["buy_eligible"][0]


# A genuine total-loss scenario is retained instead of silently clipped or discarded.
def test_joint_distribution_retains_bankruptcy_loss():
    data = distribution_inputs([[0.03], [-1.0]])
    target, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "optimized"
    assert target[0] == 0
    assert receipt["scenario_count"] == 2


# The real optimizer agrees with the exact single-stock log-growth stationary point.
def test_joint_distribution_matches_analytical_growth_size():
    up, down, win = 0.1, -0.1, 0.505
    data = distribution_inputs([[up], [down]])
    data["probabilities"] = np.array([win, 1 - win])
    target, receipt = model.allocate_distribution(**data)
    expected = -(win * up + (1 - win) * down) / (up * down)
    assert receipt["status"] == "optimized"
    assert target[0] == pytest.approx(expected, abs=1e-7)
    assert receipt["certificate"]["expected_log_growth"] == pytest.approx(
        win * np.log1p(expected * up) + (1 - win) * np.log1p(expected * down)
    )


# Small cash and cap drift cannot make a monotone, analytically solved book unavailable.
@pytest.mark.parametrize("cost", [0, 10, 25])
def test_joint_distribution_certifies_small_cash_at_drifted_ownership_cap(cost):
    data = distribution_inputs(
        [[0.003, 0.001, 0.005]] * 3,
        current=[0.25, 0.25001, 0],
        cash=0.000955,
        cost=cost,
    )
    target, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "optimized"
    assert receipt["certificate"]["certified"]
    assert receipt["certificate"]["gap"] <= model.CERTIFICATE_TOLERANCE
    np.testing.assert_allclose(
        target,
        [0.25, 0.25, data["cash_weight"] / (1 + cost / 10000)],
        atol=1e-10,
    )
    assert receipt["purchases"] * (1 + cost / 10000) <= data["cash_weight"] + 1e-12


# The original dated scenario must pass the unchanged global certificate and cash limit.
def test_joint_distribution_reproduced_small_cash_boundary():
    path = Path(__file__).parent / "fixtures/joint_optimizer_2019-05-02.npz"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "e302a298f69eff4188fc2253954c65f03565c51a76bd68c16d2e501a1bc74323"
    )
    # Original simultaneous bank and private-account inputs; never resampled or fitted.
    with np.load(path, allow_pickle=False) as source:
        data = distribution_inputs(
            source["scenarios"],
            current=source["current"],
            cash=float(source["cash"]),
            cost=float(source["cost_bps"]),
        )
        data["probabilities"] = source["probabilities"]
        data["grades"] = source["grades"]
    target, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "optimized"
    assert receipt["certificate"]["certified"]
    assert receipt["certificate"]["gap"] <= model.CERTIFICATE_TOLERANCE
    assert np.all(target <= model.CAP)
    assert receipt["purchases"] <= data["cash_weight"] + 1e-12
    reference = np.array([0.24998186930881294, 0.25, 0.25, 0, 0, 0, 0.25, 0])
    expected = data["probabilities"] @ np.log1p(data["scenarios"] @ reference)
    assert receipt["certificate"]["expected_log_growth"] >= expected - 2e-12


# False solver success, failed refinement and out-of-bounds output never authorize buys.
@pytest.mark.parametrize("failure", ["stalled", "refinement_error", "infeasible"])
def test_joint_distribution_refinement_stays_fail_closed(monkeypatch, failure):
    data = distribution_inputs([[0.05], [0.03]], current=[0.1], cash=0.9)
    calls = []

    # Return the observed holding without optimization, or a strictly invalid holding.
    def failed_solver(objective, start, **kwargs):
        calls.append(start.copy())
        if failure == "refinement_error" and len(calls) == 2:
            raise RuntimeError("numerical refinement unavailable")
        point = start.copy()
        if failure == "infeasible":
            point[0] = np.nextafter(model.CAP, np.inf)
        return SimpleNamespace(x=point, success=True, nit=1)

    monkeypatch.setattr(model, "minimize", failed_solver)
    target, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "unavailable"
    assert receipt["reason"] == "optimizer_uncertified"
    np.testing.assert_array_equal(target, data["current_weights"])
    assert not receipt["certificate"]["certified"]
    assert len(calls) == (1 if failure == "infeasible" else 2)
    if failure != "infeasible":
        assert not receipt["certificate"]["refinement"]["accepted"]
    if failure == "refinement_error":
        assert receipt["certificate"]["refinement"]["error_type"] == "RuntimeError"


# Permuting aligned stock identities cannot change their assigned capital.
def test_joint_distribution_stock_permutation_invariance():
    data = distribution_inputs([[0.03, 0.04], [-0.01, -0.05]])
    target, _ = model.allocate_distribution(**data)
    data["scenarios"] = data["scenarios"][:, ::-1]
    other, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "optimized"
    np.testing.assert_allclose(other[::-1], target, atol=1e-8)


# Covered sales never create simultaneous buying cash, even under strong forecasts.
def test_joint_distribution_no_sale_funded_purchase():
    data = distribution_inputs([[-0.1, 0.1], [-0.1, 0.1]], current=[1.0, 0], cash=0)
    target, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "optimized"
    np.testing.assert_array_equal(target, [0, 0])


# Fees preserve ownership when the forecast advantage cannot cover a sale and rebuy.
def test_joint_distribution_fee_kink_preserves_held_position():
    data = distribution_inputs([[0.0001], [-0.0001]], current=[0.2], cash=0.8, cost=25)
    target, receipt = model.allocate_distribution(**data)
    assert receipt["status"] == "optimized"
    assert target[0] == 0.2
    assert receipt["purchases"] == receipt["sales"] == 0


# Missing held cross-risk rejects additions without deleting mandatory exits.
def test_joint_distribution_missing_held_evidence():
    data = distribution_inputs(
        [[np.nan, 0.1, -0.1], [0.1, 0.1, -0.1]], current=[0.2, 0, 0.1], cash=0.7
    )
    data["grades"][2] = 0
    target, receipt = model.allocate_distribution(**data)
    np.testing.assert_array_equal(target, [0.2, 0, 0])
    assert receipt["reason"] == "missing_held_cross_risk"


# Invalid weights, return domains or an execution-price target cannot become sizes.
@pytest.mark.parametrize("mutation", ["probability", "loss", "horizon"])
def test_joint_distribution_rejects_invalid_forecast_contract(mutation):
    data = distribution_inputs([[0.03], [-0.01]])
    if mutation == "probability":
        data["probabilities"] = np.array([0.8, 0.8])
    elif mutation == "loss":
        data["scenarios"][1, 0] = -1.01
    else:
        data["horizon"] = "one_decision_log_price_advantage"
    with pytest.raises(
        ValueError, match="probabilities|arithmetic returns|holding return"
    ):
        model.allocate_distribution(**data)


# Use the real one-session risk covariance with directly declared arithmetic means.
def radius_inputs():
    data = inputs()
    data.update(mean_units="arithmetic", horizon_sessions=1)
    data["means"][:2] = 0.001
    return data


# Distinguish existing B ownership from A-only permission to make new purchases.
@pytest.mark.parametrize(("mean", "target_b"), [(0.02, 0.2), (-0.02, 0)])
def test_held_b_utility_can_retain_or_exit_without_addition(mean, target_b):
    data = radius_inputs()
    data.update(current_weights=np.array([0.2, 0, 0, 0]), cash_weight=0.8)
    data["grades"][0] = 1
    data["means"][0] = mean
    target, receipt = model.allocate(**data, hold_b=True)
    assert receipt["status"] == "optimized"
    assert receipt["certificate"]["certified"]
    assert target[0] == pytest.approx(target_b, abs=1e-10)
    assert target[0] <= 0.2
    assert not receipt["buy_eligible"][0]
    assert receipt["holding_eligible"][0]
    assert receipt["holding_upper_bounds"][0] == 0.2


# Zero ownership prevents a positive B forecast from becoming a new buy or rebuy.
def test_unheld_b_forecast_never_receives_capital():
    data = radius_inputs()
    data["grades"][0] = 1
    data["means"][0] = 0.1
    target, receipt = model.allocate(**data, hold_b=True)
    assert target[0] == 0
    assert not receipt["holding_eligible"][0]
    assert receipt["certificate"]["certified"]


# Unavailable held evidence preserves quantities and prevents cross-risk purchases.
@pytest.mark.parametrize("missing", ["mean", "radius", "history"])
def test_missing_held_b_evidence_uses_safe_account_fallback(missing):
    data = radius_inputs()
    data.update(current_weights=np.array([0.3, 0.1, 0, 0]), cash_weight=0.6)
    data["grades"][0] = 1
    radii = np.zeros(4)
    if missing == "mean":
        data["means"][0] = np.nan
    elif missing == "radius":
        radii[0] = np.nan
    else:
        data["history"][0, 0] = np.nan
    target, receipt = model.allocate(**data, hold_b=True, trade_radius=radii)
    np.testing.assert_array_equal(target, [0.25, 0.1, 0, 0])
    assert receipt["reason"] == "missing_held_cross_risk"


# Lost membership and C grades remain mandatory despite favorable B-mode forecasts.
@pytest.mark.parametrize("boundary", ["grade", "membership"])
def test_held_b_does_not_override_mandatory_exit(boundary):
    data = radius_inputs()
    data.update(current_weights=np.array([0.2, 0, 0, 0]), cash_weight=0.8)
    data["grades"][0] = 1
    data["means"][0] = 0.02
    if boundary == "grade":
        data["grades"][0] = 0
    else:
        data["eligible"][0] = False
    target, receipt = model.allocate(**data, hold_b=True)
    assert target[0] == 0
    assert receipt["mandatory_exits"][0]


# Explicitly disabled retention preserves every default output and receipt field.
def test_held_b_default_is_exact_old_allocation():
    data = radius_inputs()
    data.update(current_weights=np.array([0.2, 0.1, 0, 0]), cash_weight=0.7)
    data["grades"][0] = 1
    target, receipt = model.allocate(**data)
    same, evidence = model.allocate(**data, hold_b=False)
    np.testing.assert_array_equal(target, same)
    assert evidence == receipt
    assert receipt["mandatory_exits"][0]
    assert "hold_b" not in receipt


# Reject an ambiguous option or incompatible ten-session horizon before solving.
@pytest.mark.parametrize("option", [1, "yes", None])
def test_held_b_option_requires_explicit_boolean(option):
    with pytest.raises(ValueError, match="Boolean held-B"):
        model.allocate(**radius_inputs(), hold_b=option)


# Held-B one-day evidence cannot silently enter the old ten-session objective.
def test_held_b_requires_daily_arithmetic_units():
    with pytest.raises(ValueError, match="one-session arithmetic"):
        model.allocate(**inputs(), hold_b=True)


# Empirical resolution keeps uncertain signed advantages at the current holding.
@pytest.mark.parametrize("mean", [0.0001, -0.0001])
def test_error_radius_holds_uncertain_signed_advantage(mean):
    data = radius_inputs()
    data.update(current_weights=np.array([0.2, 0, 0, 0]), cash_weight=0.8)
    data["grades"][1] = 0
    data["means"][0] = mean
    target, receipt = model.allocate(**data, trade_radius=np.full(4, 0.001))
    assert receipt["status"] == "optimized"
    assert receipt["certificate"]["certified"]
    assert target[0] == pytest.approx(0.2, abs=1e-10)
    assert receipt["trade_radius_contract"]["confidence_guarantee"] is False


# Sufficiently strong favorable or unfavorable means overcome the same holding band.
@pytest.mark.parametrize(("mean", "expected"), [(0.01, 0.25), (-0.01, 0.0)])
def test_strong_signed_advantage_buys_or_exits(mean, expected):
    data = radius_inputs()
    data.update(current_weights=np.array([0.2, 0, 0, 0]), cash_weight=0.8)
    data["grades"][1] = 0
    data["means"][0] = mean
    target, receipt = model.allocate(**data, trade_radius=np.full(4, 0.001))
    assert receipt["certificate"]["certified"]
    assert target[0] == pytest.approx(expected, abs=1e-10)


# Different empirical stock errors change purchases without changing paid broker fees.
def test_stock_specific_radius_and_cash_constraint():
    data = radius_inputs()
    data.update(cost_bps=10, cash_weight=0.02)
    data["means"][:2] = 0.002
    target, receipt = model.allocate(**data, trade_radius=np.array([0.01, 0, 0, 0]))
    assert target[0] == pytest.approx(0, abs=1e-10)
    assert target[1] > 0
    assert target.sum() * 1.001 <= 0.02 + 1e-10
    assert receipt["selected_trade_penalties"] == [0.011, 0.001]
    assert receipt["trade_radius_contract"]["funding"] == "actual_per_side_cost_only"


# Missing radius follows existing held-risk fallback and preserves mandatory exits/caps.
def test_missing_radius_safe_fallback_and_mandatory_exits():
    data = radius_inputs()
    data.update(current_weights=np.array([0.3, 0.1, 0, 0]), cash_weight=0.6)
    target, receipt = model.allocate(**data, trade_radius=np.array([np.nan, 0, 0, 0]))
    np.testing.assert_array_equal(target, [0.25, 0.1, 0, 0])
    assert receipt["reason"] == "missing_held_cross_risk"
    assert receipt["trade_radius_contract"]["radius"][0] is None
    data["grades"][0] = 0
    data["means"][1] = -0.01
    target, receipt = model.allocate(**data, trade_radius=np.array([np.nan, 1, 0, 0]))
    assert target[0] == 0
    assert target[1] == pytest.approx(0.1, abs=1e-10)
    assert receipt["mandatory_exits"][0]


# Unheld missing radius is excluded rather than silently assigned zero uncertainty.
def test_unheld_missing_radius_does_not_poison_known_stock():
    data = radius_inputs()
    target, receipt = model.allocate(**data, trade_radius=np.array([np.nan, 0, 0, 0]))
    assert target[0] == 0
    assert target[1] > 0
    assert receipt["known"][0] is False


# Explicit zeros retain exact scalar solver targets and all original receipt fields.
@pytest.mark.parametrize("units", ["log", "arithmetic"])
def test_absent_and_zero_radius_preserve_original_numerics(units):
    data = inputs() if units == "log" else radius_inputs()
    before, original = model.allocate(**data)
    absent, same = model.allocate(**data, trade_radius=None)
    zero, expanded = model.allocate(**data, trade_radius=np.zeros(4))
    np.testing.assert_array_equal(before, absent)
    np.testing.assert_array_equal(before, zero)
    assert original == same
    expanded.pop("trade_radius_contract")
    expanded.pop("selected_trade_penalties")
    assert expanded == original


# Malformed radii cannot enter the objective or become unavailable silently.
@pytest.mark.parametrize("radius", [[0], [-1, 0, 0, 0], [np.inf, 0, 0, 0], [True] * 4])
def test_invalid_radius_is_rejected(radius):
    with pytest.raises(ValueError, match="trade_radius"):
        model.allocate(**radius_inputs(), trade_radius=np.asarray(radius))


# Daily error estimates cannot silently penalize a ten-session return objective.
def test_daily_error_radius_requires_matching_arithmetic_horizon():
    with pytest.raises(ValueError, match="one-session arithmetic"):
        model.allocate(**inputs(), trade_radius=np.full(4, 0.001))


# Equal expected arithmetic returns receive different interior quantities by risk.
def test_actual_optimizer_changes_quantity_for_stock_volatility():
    data = inputs()
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "optimized"
    assert receipt["certificate"]["certified"]
    assert 0 < target[1] < target[0] < model.CAP
    assert target[2:].sum() == 0
    assert target.sum() <= 1


# Raising a stock's mature expected return changes its target without a price gate.
def test_expected_return_changes_target_and_negative_edge_leaves_cash():
    data = inputs()
    original, _ = model.allocate(**data)
    data["means"][1] += 0.0005
    raised, _ = model.allocate(**data)
    assert raised[1] > original[1]
    data["means"][:2] = -0.2
    cash, receipt = model.allocate(**data)
    assert receipt["status"] == "optimized"
    np.testing.assert_allclose(cash, 0, atol=1e-12)


# A shared return shock changes the joint solution through observed cross-risk.
def test_correlation_changes_weights_with_other_inputs_fixed():
    data = inputs()
    first, _ = model.allocate(**data)
    returns = np.diff(np.log(data["history"]), axis=0)
    returns[:, 1] = returns[:, 0] * 2
    data["history"] = 100 * np.exp(np.vstack((np.zeros(4), np.cumsum(returns, axis=0))))
    changed, receipt = model.allocate(**data)
    assert receipt["status"] == "optimized"
    assert not np.allclose(first[:2], changed[:2], atol=1e-5)


# Purchases and their fees fit original cash even while another position is sold.
@pytest.mark.parametrize("cost", [0, 10, 25])
def test_sale_proposal_cannot_fund_new_purchases(cost):
    data = inputs()
    data.update(
        current_weights=np.array([0.4, 0, 0, 0]), cash_weight=0.03, cost_bps=cost
    )
    data["means"][:2] = [-0.1, 0.2]
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "optimized"
    assert target[0] < data["current_weights"][0]
    assert target[1] > 0
    purchases = np.maximum(target - data["current_weights"], 0).sum()
    assert purchases * (1 + cost / 10000) <= data["cash_weight"] + 1e-10
    assert np.all(target <= model.CAP + 1e-10)


# An account without cash cannot purchase using a simultaneous mandatory exit.
def test_no_cash_no_same_reset_reinvestment():
    data = inputs()
    data.update(current_weights=np.array([0.5, 0, 0, 0]), cash_weight=0.0)
    data["grades"][0] = 0
    data["means"][1] = 0.1
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "optimized"
    np.testing.assert_allclose(target, 0, atol=1e-10)
    assert receipt["mandatory_exits"][0]


# Unknown held forecasts or risk prevent new bets without erasing known ownership.
@pytest.mark.parametrize("missing", ["mean", "history"])
def test_missing_held_evidence_preserves_hold_and_cap_without_additions(missing):
    data = inputs()
    data.update(current_weights=np.array([0.3, 0.1, 0, 0]), cash_weight=0.6)
    if missing == "mean":
        data["means"][0] = np.nan
    else:
        data["history"][3, 0] = np.nan
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "unavailable"
    assert receipt["reason"] == "missing_held_cross_risk"
    np.testing.assert_array_equal(target, [0.25, 0.1, 0, 0])
    assert np.all(target <= data["current_weights"])


# Missing evidence on an unheld stock excludes it without losing known decisions.
def test_unheld_missing_evidence_is_not_imputed():
    data = inputs()
    data["means"][1] = np.nan
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "optimized"
    assert target[1] == 0
    assert receipt["known"][1] is False


# Missing ownership valuation is rejected instead of fabricating a funded target.
def test_missing_held_weight_refuses_account():
    data = inputs()
    data["current_weights"][0] = np.nan
    with pytest.raises(ValueError, match="current_weights"):
        model.allocate(**data)


# Only the last 253 completed closes determine allocation on a longer prefix.
def test_unused_earlier_prefix_cannot_change_target():
    data = inputs()
    original, _ = model.allocate(**data)
    data["history"] = np.vstack((np.full((31, 4), np.nan), data["history"]))
    longer, _ = model.allocate(**data)
    np.testing.assert_array_equal(original, longer)


# Fees discourage an otherwise small favorable purchase by the actual objective.
def test_cost_penalty_prevents_low_edge_turnover():
    data = inputs()
    free, _ = model.allocate(**data)
    data["cost_bps"] = 25
    costly, receipt = model.allocate(**data)
    assert receipt["status"] == "optimized"
    assert costly.sum() < free.sum()


# Solver failure preserves positions and still respects mandatory grade exits.
def test_solver_exception_is_unavailable_without_new_purchases(monkeypatch):
    data = inputs()
    data.update(current_weights=np.array([0.2, 0.1, 0, 0]), cash_weight=0.7)
    data["grades"][1] = 0

    # Simulate a numerical solver failure rather than a forecast or ledger mutation.
    def failed(*args):
        raise RuntimeError("numerical solve unavailable")

    monkeypatch.setattr(model, "_solve", failed)
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "unavailable"
    np.testing.assert_array_equal(target, [0.2, 0, 0, 0])


# A feasible-looking but nonoptimal returned point fails the global certificate.
def test_global_certificate_rejects_uncertified_solver_output(monkeypatch):
    data = inputs()

    # Return a bounded point with a false certificate to exercise fail-closed routing.
    def uncertified(*args):
        return np.array([0.25, 0.25]), {
            "certified": False,
            "reason": "global_convex_gap",
        }

    monkeypatch.setattr(model, "_solve", uncertified)
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "unavailable"
    np.testing.assert_array_equal(target, 0)


# An explicitly fixed position remains inside the quadratic's true cross-term.
def test_fixed_known_position_changes_free_optimum_through_cross_term():
    covariance = np.array([[0.1, 0.04], [0.04, 0.1]])
    mean = np.array([0.0, 0.02])
    target, proof = model._solve(
        mean,
        covariance,
        np.array([0.2, 0]),
        np.array([0.2, 0]),
        np.array([0.2, 0.25]),
        0.8,
        0,
    )
    assert proof["certified"]
    assert target[0] == 0.2
    assert target[1] == pytest.approx((0.02 - 0.04 * 0.2) / 0.1, abs=1e-7)


# The certificate itself rejects a feasible point with a materially improving direction.
def test_linearized_gap_detects_nonoptimal_feasible_point():
    matrix = np.array([[1.0]])
    proof = model._certificate(
        np.array([0.2]),
        lambda x: np.array([-0.1]),
        matrix,
        np.array([0.25]),
        [(0.0, 0.25)],
    )
    assert proof["gap"] == pytest.approx(0.005)
    assert not proof["certified"]


# Membership and below-A grades take priority over even very strong projections.
@pytest.mark.parametrize("field", ["grades", "eligible"])
def test_mandatory_exit_survives_missing_evidence_elsewhere(field):
    data = inputs()
    data.update(current_weights=np.array([0.2, 0.1, 0, 0]), cash_weight=0.7)
    data["means"][1] = np.nan
    data[field][0] = 0 if field == "grades" else False
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "unavailable"
    np.testing.assert_array_equal(target, [0, 0.1, 0, 0])


# A fabricated feasible point violating original cash fails before optimality testing.
def test_certificate_rejects_purchase_budget_violation():
    proof = model._certificate(
        np.array([0.1]),
        lambda x: np.array([0.0]),
        np.array([[1.0]]),
        np.array([0.03]),
        [(0.0, 0.25)],
    )
    assert not proof["certified"]
    assert proof["reason"] == "infeasible"


# Numerically overflowing finite projections are unavailable rather than clipped.
def test_extreme_projection_does_not_fabricate_finite_second_moment():
    data = inputs()
    data["means"][0] = 1e300
    target, receipt = model.allocate(**data)
    assert receipt["status"] == "unavailable"
    assert receipt["reason"] == "moment_numeric_range"
    np.testing.assert_array_equal(target, 0)


# Numerical tolerance cannot certify a negative or over-cap final holding.
@pytest.mark.parametrize("weight", [-1e-10, 0.25 + 1e-10])
def test_certificate_rejects_strict_final_bound_residue(weight):
    proof = model._certificate(
        np.array([weight]),
        lambda x: np.array([0.0]),
        np.array([[1.0]]),
        np.array([1.0]),
        [(0.0, 0.25)],
    )
    assert not proof["certified"]
