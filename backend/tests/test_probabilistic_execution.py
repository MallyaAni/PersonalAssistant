"""Pure synthetic acceptance for causal execution distributions and funded utility."""

from datetime import UTC, datetime

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import probabilistic_execution as model


# Build an actual reviewed session grid with unequal observed counts per day.
def fixture(start="2023-01-03", stop="2026-10-01", clocks=3):
    _, calendar = exchange.reviewed_sessions()
    dates = np.arange(np.datetime64(start), np.datetime64(stop))
    dates = dates[np.is_busday(dates, busdaycal=calendar)]
    shape = (len(dates), clocks, 2)
    means = np.zeros(shape)
    second = np.full(shape, 0.01)
    labels = np.broadcast_to(
        np.resize(np.array([-0.1, 0.0, 0.1]), clocks)[None, :, None], shape
    ).copy()
    valid = np.ones(shape, dtype=bool)
    valid[::2, 1:, :] = False
    return dict(
        dates=dates,
        symbols=("AAOI", "COHR"),
        means=means,
        second_moments=second,
        labels=labels,
        valid=valid,
        outcome_end_dates=dates.copy(),
        data_as_of=datetime(2026, 10, 1, tzinfo=UTC),
        horizon=model.HORIZON,
    )


# Calculate a past-only result without modifying the supplied fixture arrays.
def result(**changes):
    inputs = fixture()
    inputs.update(changes)
    return model.calibrate(**inputs)


# A waiting open at an early closing instant has no regular-session price support.
def test_early_close_excludes_waiting_endpoint_at_session_close():
    data = fixture(start="2024-01-02", stop="2025-11-29", clocks=25)
    data["valid"][:] = True
    calibrated = model.calibrate(**data)
    day = int(np.flatnonzero(data["dates"] == np.datetime64("2025-11-28"))[0])
    assert calibrated.causal_mask[day, 11].all()
    assert not calibrated.causal_mask[day, 12:].any()
    assert np.isnan(calibrated.probability_positive[day, 12:]).all()


# Pin strict-positive mass and non-interpolated weighted empirical quantiles.
def test_weighted_quantiles_and_probability():
    assert np.array_equal(model.weighted_quantiles([-1, 0, 2], [1, 7, 2]), [-1, 0, 2])
    calibrated = result()
    index = np.flatnonzero(calibrated.score_mask[:, 0, 0])[0]
    month = str(calibrated.dates[index].astype("datetime64[M]"))
    sample = calibrated.samples[month]["AAOI"]
    expected = sample.weights[sample.residuals > 0].sum() / sample.weights.sum()
    assert calibrated.probability_positive[index, 0, 0] == pytest.approx(expected)
    for day in np.unique(sample.day_indices):
        assert sample.weights[sample.day_indices == day].sum() == pytest.approx(1)
    probabilities = calibrated.probability_positive[calibrated.score_mask]
    assert np.all((probabilities >= 0) & (probabilities <= 1))


# Prove stock-conditioned location and variance alter forecasts independently.
def test_stock_specific_moments():
    data = fixture()
    day = int(np.searchsorted(data["dates"], np.datetime64("2026-09-01")))
    data["means"][day:, :, 0] = 0.2
    data["second_moments"][day:, :, 0] = 0.05
    data["means"][day:, :, 1] = -0.2
    data["second_moments"][day:, :, 1] = 0.08
    calibrated = model.calibrate(**data)
    assert calibrated.probability_positive[day, 0, 0] == 1
    assert calibrated.probability_positive[day, 0, 1] == 0
    assert np.all(calibrated.quantiles[day, 0, 0] > calibrated.quantiles[day, 0, 1])
    assert calibrated.manifest["confidence_guarantee"] is False


# Retain scoring when future target values disappear, including a frozen final month.
def test_future_labels_and_freeze_do_not_gate_predictions():
    data = fixture()
    original = model.calibrate(**data)
    future = data["dates"] >= model.FREEZE
    data["labels"][future] = np.nan
    changed = model.calibrate(**data)
    assert np.array_equal(
        original.probability_positive, changed.probability_positive, equal_nan=True
    )
    assert np.array_equal(original.quantiles, changed.quantiles, equal_nan=True)
    for receipt in original.manifest["months"]:
        for stock in receipt["stocks"]:
            if stock["maximum_endpoint"] is not None:
                assert np.datetime64(stock["maximum_endpoint"]) < min(
                    np.datetime64(receipt["fit_date"]), model.FREEZE
                )


# Current and later forecast changes cannot alter an earlier monthly prefix.
def test_future_forecast_prefix_invariance():
    data = fixture()
    original = model.calibrate(**data)
    cutoff = data["dates"] >= np.datetime64("2026-03-01")
    data["means"][cutoff] = 0.7
    data["second_moments"][cutoff] = 0.8
    changed = model.calibrate(**data)
    assert np.array_equal(
        original.probability_positive[~cutoff],
        changed.probability_positive[~cutoff],
        equal_nan=True,
    )


# Cold starts and inconsistent or degenerate variances remain explicit missing evidence.
def test_minimum_days_and_invalid_moments():
    short = fixture(start="2026-01-02")
    assert not model.calibrate(**short).score_mask.any()
    data = fixture()
    data["second_moments"][-1, :, 0] = 0
    data["means"][-1, :, 1] = 2
    calibrated = model.calibrate(**data)
    assert not calibrated.score_mask[-1].any()
    assert calibrated.distribution(len(data["dates"]) - 1, 0, 0) is None
    assert calibrated.manifest["invalid_moment_rows"] >= 2


# Bind all original typed inputs and detect changed endpoint or outcome lineage.
def test_input_lineage_and_no_mutation():
    data = fixture()
    copies = {
        key: value.copy()
        for key, value in data.items()
        if isinstance(value, np.ndarray)
    }
    original = model.calibrate(**data)
    assert all(
        np.array_equal(data[key], value, equal_nan=True)
        for key, value in copies.items()
    )
    data["labels"][-1, 0, 0] = 7
    changed = model.calibrate(**data)
    assert (
        original.manifest["identity"]["inputs"]["labels"]
        != changed.manifest["identity"]["inputs"]["labels"]
    )


# Admit only completed bars and reject supplied endpoint clocks preceding observations.
def test_as_of_and_endpoint_clocks():
    data = fixture(start="2024-01-02", stop="2026-09-02")
    data["data_as_of"] = "2026-09-01T09:46:00-04:00"
    calibrated = model.calibrate(**data)
    assert calibrated.score_mask[-1, 0].all()
    assert not calibrated.score_mask[-1, 1:].any()
    shape = data["means"].shape
    data["outcome_end_dates"] = np.broadcast_to(
        data["dates"][:, None, None], shape
    ).copy()
    data["outcome_end_dates"][1, 0, 0] = data["dates"][0]
    with pytest.raises(ValueError, match="precede"):
        model.calibrate(**data)


# Reject false calendars, untyped masks and incompatible execution targets.
@pytest.mark.parametrize("change", ["calendar", "mask", "horizon", "inf"])
def test_strict_input_contract(change):
    data = fixture()
    if change == "calendar":
        data["dates"][10] += np.timedelta64(1, "D")
    elif change == "mask":
        data["valid"] = data["valid"].astype(float)
    elif change == "horizon":
        data["horizon"] = "ten_session_holding_return"
    else:
        data["labels"][0, 0, 0] = np.inf
    with pytest.raises(ValueError, match="required"):
        model.calibrate(**data)


# Directly verify both trade directions against the fixed-quantity wealth equations.
@pytest.mark.parametrize(("side", "direction"), [("buy", -1), ("sell", 1)])
def test_funded_expected_log_equations(side, direction):
    distribution = model.Distribution(
        0.03, 0.02, np.array([-1.0, 1.0]), np.array([1.0, 3.0])
    )
    selected = model.decision(distribution, side, 0.2, 25, horizon=model.HORIZON)
    y = np.array([0.01, 0.05])
    factor = 0.2 * (1 - direction * 0.0025)
    expected = np.dot([0.25, 0.75], np.log1p(direction * factor * np.expm1(-y)))
    assert selected.expected_log_utility == pytest.approx(expected)
    assert selected.state == ("wait" if expected > 0 else "execute")


# Full-distribution downside can outweigh a majority of favorable outcomes.
def test_no_probability_threshold_or_size_multiplier():
    distribution = model.Distribution(
        0, 1, np.array([0.05, -1.0]), np.array([9.0, 1.0])
    )
    assert (
        model.decision(distribution, "buy", 0.4, 10, horizon=model.HORIZON).state
        == "execute"
    )
    assert (
        model.decision(
            distribution, "buy", 0.001, 10, horizon=model.HORIZON
        ).expected_log_utility
        != model.decision(
            distribution, "buy", 0.4, 10, horizon=model.HORIZON
        ).expected_log_utility
    )


# Refuse unfunded and unsupported wealth rather than clipping empirical downside.
def test_unavailable_wealth_and_funding():
    distribution = model.Distribution(-5, 0, np.array([0.0]), np.array([1.0]))
    assert (
        model.decision(distribution, "buy", 0.1, 10, horizon=model.HORIZON).state
        == "unavailable"
    )
    assert (
        model.decision(distribution, "buy", 0, 10, horizon=model.HORIZON).state
        == "no_trade"
    )
    assert (
        model.decision(None, "sell", 0.1, 10, horizon=model.HORIZON).state
        == "unavailable"
    )
    assert (
        model.decision(distribution, "sell", True, 10, horizon=model.HORIZON).state
        == "unavailable"
    )
    with pytest.raises(ValueError, match="horizon"):
        model.decision(distribution, "sell", 0.1, 10, horizon="holding")


# Keep unavailable early-close, benchmark and terminal clocks out of causal support.
def test_early_closes_benchmarks_and_original_clock_support():
    data = fixture(clocks=25)
    data["symbols"] = ("AAOI", "SPY")
    calibrated = model.calibrate(**data)
    early = int(np.flatnonzero(data["dates"] == np.datetime64("2025-11-28"))[0])
    assert calibrated.causal_mask[early, :13, 0].any()
    assert not calibrated.causal_mask[early, 13:, 0].any()
    assert not calibrated.causal_mask[:, 23:, :].any()
    assert not calibrated.causal_mask[:, :, 1].any()
    assert all(
        month["stocks"][1]["status"] == "excluded_benchmark"
        for month in calibrated.manifest["months"]
    )
    assert calibrated.manifest["causal_opportunities"] == int(
        calibrated.causal_mask.sum()
    )
    assert (
        calibrated.manifest["unavailable"] + calibrated.manifest["available"]
        == calibrated.manifest["causal_opportunities"]
    )


# Refuse unsupported timestamp schemas and preserve integer-weight arithmetic.
def test_endpoint_schema_and_large_integer_weights():
    data = fixture()
    data["outcome_end_dates"] = data["outcome_end_dates"].astype("datetime64[ns]")
    with pytest.raises(ValueError, match="day endpoints"):
        model.calibrate(**data)
    weights = np.array([2**62, 2**62], dtype=np.int64)
    assert model.weighted_quantiles([-1, 1], weights, [0.5])[0] == -1


# Preserve exact zero-advantage ties and cost-sensitive buy/sell directions.
def test_deterministic_ties_and_directions():
    for side in ("buy", "sell"):
        zero = model.Distribution(0, 0, np.array([0.0]), np.array([1.0]))
        assert (
            model.decision(zero, side, 0.2, 25, horizon=model.HORIZON).state
            == "execute"
        )
    positive = model.Distribution(0.01, 0, np.array([0.0]), np.array([1.0]))
    assert (
        model.decision(positive, "buy", 0.2, 25, horizon=model.HORIZON).state == "wait"
    )
    assert (
        model.decision(positive, "sell", 0.2, 25, horizon=model.HORIZON).state
        == "execute"
    )
