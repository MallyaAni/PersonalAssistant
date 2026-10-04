"""Exercise the actual funded solver with one-session arithmetic forecast units."""

import numpy as np
import pytest
from sklearn.covariance import LedoitWolf

from backend.market import adaptive_growth_policy as model


# Construct known stock risks and the two excluded benchmark positions.
def inputs():
    returns = np.random.default_rng(51).normal(size=(252, 4)) * [0.01, 0.03, 0.02, 0.01]
    return {
        "history": 100 * np.exp(np.vstack((np.zeros(4), np.cumsum(returns, axis=0)))),
        "grades": np.array([2, 3, 2, 2]),
        "eligible": np.ones(4, dtype=bool),
        "means": np.array([0.0001, 0.0001, 0.0, 0.0]),
        "current_weights": np.zeros(4),
        "cash_weight": 1.0,
        "cost_bps": 0,
        "benchmark_indices": np.array([2, 3]),
    }


# Confirm risk scaling against the directly fitted daily covariance.
def test_one_session_covariance_matches_daily_return_estimate():
    data = inputs()
    returns = np.diff(np.log(data["history"]), axis=0)
    expected = LedoitWolf().fit(returns).covariance_
    np.testing.assert_array_equal(
        model.covariance(data["history"], horizon_sessions=1), expected
    )
    np.testing.assert_array_equal(model.covariance(data["history"]), expected * 10)


# Arithmetic mean forecasts reach the solver without another variance return bonus.
def test_arithmetic_means_and_one_session_risk_are_retained():
    data = inputs()
    target, receipt = model.allocate(
        **data, mean_units="arithmetic", horizon_sessions=1
    )
    assert receipt["status"] == "optimized"
    assert receipt["certificate"]["certified"]
    np.testing.assert_array_equal(receipt["arithmetic_means"], data["means"][:2])
    np.testing.assert_array_equal(
        receipt["covariance"],
        model.covariance(data["history"][:, :2], horizon_sessions=1),
    )
    assert 0 < target[1] < target[0] <= model.CAP
    assert not target[2:].any()


# Zero or adverse expected arithmetic return cannot manufacture a purchase from risk.
@pytest.mark.parametrize("mean", [0.0, -0.01])
def test_no_variance_driven_buy_for_nonpositive_arithmetic_forecast(mean):
    data = inputs()
    data["means"][:2] = mean
    target, receipt = model.allocate(
        **data, mean_units="arithmetic", horizon_sessions=1
    )
    assert receipt["status"] == "optimized"
    np.testing.assert_allclose(target, 0, atol=1e-12)


# Sale proceeds remain unavailable to an otherwise attractive new daily purchase.
@pytest.mark.parametrize("cost", [0, 10, 25])
def test_daily_arithmetic_target_respects_presale_funding(cost):
    data = inputs()
    data.update(
        current_weights=np.array([0.4, 0, 0, 0]), cash_weight=0.03, cost_bps=cost
    )
    data["means"][:2] = [-0.01, 0.1]
    target, receipt = model.allocate(
        **data, mean_units="arithmetic", horizon_sessions=1
    )
    assert receipt["status"] == "optimized"
    assert target[0] == pytest.approx(0, abs=1e-10)
    assert 0 < target[1] <= 0.03 / (1 + cost / 10000) + 1e-10


# Supplying the declared original units preserves exact default targets and receipts.
def test_original_log_mode_remains_exactly_unchanged():
    data = inputs()
    implicit = model.allocate(**data)
    explicit = model.allocate(**data, mean_units="log", horizon_sessions=10)
    np.testing.assert_array_equal(implicit[0], explicit[0])
    assert implicit[1] == explicit[1]
    assert implicit[1]["policy"] == model.POLICY
    assert "mean_units" not in implicit[1]


# Mixed horizons, unknown units and boolean controls are invalid forecast contracts.
@pytest.mark.parametrize(
    ("units", "horizon"),
    [
        ("log", 1),
        ("arithmetic", 10),
        ("unknown", 1),
        ("arithmetic", True),
        ("arithmetic", 1.0),
    ],
)
def test_incompatible_forecast_contract_is_rejected(units, horizon):
    with pytest.raises(ValueError, match="Matching declared"):
        model.allocate(**inputs(), mean_units=units, horizon_sessions=horizon)
