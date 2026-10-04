"""Actual fixed fits exercise independent feature support and OOS error evidence."""

from copy import deepcopy
from datetime import datetime

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_feature_arithmetic as feature
from backend.tests.test_direct_daily_arithmetic import fixture as original_fixture


# Reproduce all missing old predictions while retaining original known features.
def fixture(count=570, start="2023-01-03"):
    prepared, parent = original_fixture(count=count, start=start)
    dates = prepared["dates"]
    prices = np.full(parent.labels.shape, 100.0)
    for day in range(count - 2):
        prices[day + 2] = prices[day + 1] * (1 + parent.labels[day])
    prepared["absolute_forecasts"] = np.full(prices.shape, np.nan)
    grades, eligible = np.full(prices.shape, 2), np.ones(prices.shape, bool)
    parent = reference.walk_forward(
        dates,
        prepared["symbols"],
        prices,
        grades,
        eligible,
        prepared["absolute_forecasts"],
        dates,
        data_as_of=datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        ),
    )
    return prepared, parent, grades, eligible


# A real fixed model learns even when the old predictor supplied no forecasts.
def test_actual_head_learns_without_original_predictor():
    prepared, parent, grades, eligible = fixture()
    assert not parent.score_mask.any()
    result = feature.walk_forward(prepared, parent, grades, eligible)
    known = np.isfinite(result.forecasts) & np.isfinite(parent.labels)
    assert known.any()
    assert np.corrcoef(result.forecasts[known], parent.labels[known])[0, 1] > 0.8
    assert result.manifest["support_counts"]["added_opportunities"] == 1140
    assert np.isnan(result.forecasts[:, 2:]).all()
    assert np.isfinite(result.forecasts[-2:, :2]).all()
    for row in result.manifest["months"]:
        if row["status"] == "fitted":
            assert row["training_days"] >= 504
            assert np.datetime64(row["maximum_label_end"]) < np.datetime64(
                row["label_end_before"]
            )
            assert row["model"]["iterations"] == 64


# Explicit causal grades and membership gate opportunities without future labels.
def test_support_gates_state_and_preserves_missing_outcome_tail():
    prepared, parent, grades, eligible = fixture(count=530)
    grades[-4:, 0] = 1
    eligible[-3:, 1] = False
    prepared["valid"][-5, 0] = False
    result = feature.walk_forward(prepared, parent, grades, eligible)
    assert not result.score_mask[-4:, 0].any()
    assert not result.score_mask[-3:, 1].any()
    assert not result.score_mask[-5, 0]
    assert np.isnan(result.forecasts[-3:, :2]).all()
    assert result.score_mask[-4, 1]


# A changed future feature suffix cannot revise past heads or predictions.
def test_future_features_do_not_change_prior_months():
    prepared, parent, grades, eligible = fixture()
    before = feature.walk_forward(prepared, parent, grades, eligible)
    future = prepared["dates"].astype("datetime64[M]") == prepared["dates"][-1].astype(
        "datetime64[M]"
    )
    prepared["X"][future] *= -5
    after = feature.walk_forward(prepared, parent, grades, eligible)
    np.testing.assert_array_equal(before.forecasts[~future], after.forecasts[~future])
    assert before.manifest["months"][:-1] == after.manifest["months"][:-1]


# The fixed band consumes only genuine matured OOS scores under its new identity.
def test_actual_band_has_new_lineage_and_past_only_residuals():
    prepared, parent, grades, eligible = fixture(count=630)
    result = feature.walk_forward(prepared, parent, grades, eligible)
    bands = feature.calibrate(result, parent)
    assert np.isfinite(bands.radii).any()
    assert (
        bands.manifest["identity"]["policy"] == "direct-feature-error-band/1-research"
    )
    for receipt in bands.manifest["months"]:
        for stock in receipt["stocks"]:
            if stock["status"] == "available":
                assert stock["clusters"] >= 2
                assert np.datetime64(stock["maximum_endpoint"]) < np.datetime64(
                    receipt["label_end_before"]
                )
    future = prepared["dates"].astype("datetime64[M]") == prepared["dates"][-1].astype(
        "datetime64[M]"
    )
    changed = deepcopy(result)
    changed.forecasts[future, :2] += 0.2
    changed.manifest["forecasts_sha256"] = reference._hash(changed.forecasts)
    changed.manifest["months"][-1]["prediction_sha256"] = reference._hash(
        changed.forecasts[future]
    )
    later = feature.calibrate(changed, parent)
    np.testing.assert_array_equal(bands.radii, later.radii)


# Altered forecast or monthly prediction bytes are rejected before calibration.
@pytest.mark.parametrize("change", ["forecast", "clock", "mask", "identity"])
def test_calibration_rejects_changed_lineage(change):
    prepared, parent, grades, eligible = fixture(count=530)
    result = feature.walk_forward(prepared, parent, grades, eligible)
    if change == "forecast":
        result.forecasts[-1, 0] += 0.1
    elif change == "clock":
        result.manifest["months"][-1]["fit_index"] += 1
    elif change == "mask":
        result.score_mask[-1, 0] = False
    else:
        result.manifest["identity"]["policy"] = "old-direct"
    with pytest.raises(ValueError, match="bytes mismatch|support|monthly|identity"):
        feature.calibrate(result, parent)


# Ambiguous eligibility and unrecognized grades cannot become decision support.
@pytest.mark.parametrize("change", ["grade", "membership", "shape"])
def test_support_rejects_invalid_inputs(change):
    prepared, parent, grades, eligible = fixture(count=20)
    if change == "grade":
        grades[0, 0] = 5
    elif change == "membership":
        eligible = eligible.astype(int)
    else:
        eligible = eligible[:-1]
    with pytest.raises(ValueError, match="ordinal grades"):
        feature.walk_forward(prepared, parent, grades, eligible)
