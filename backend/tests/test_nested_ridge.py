"""Numerical and causal proof for the isolated NumPy ridge fitting kernel."""

import json
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import numpy as np
import pytest

from backend.market.nested_ridge import RegressionInputs, fit

DAY = np.timedelta64(1, "D")


# Build small deterministic features and variable-capable future outcome evidence.
def _inputs(rows=16, columns=2):
    dates = np.datetime64("2020-01-01", "D") + np.arange(rows).astype("timedelta64[D]")
    features = np.column_stack(
        [np.arange(rows, dtype=float) ** (j + 1) for j in range(columns)]
    )
    labels = np.column_stack(
        [3.0 + np.arange(rows) * slope for slope in (1.0, -0.5, 2.0)]
    )
    return RegressionInputs(
        dates=dates,
        features=features,
        feature_available_on=np.broadcast_to(dates[:, None], features.shape),
        labels=labels,
        label_end_on=np.broadcast_to(dates[:, None] + DAY, labels.shape),
        label_available_on=np.broadcast_to(dates[:, None] + DAY, labels.shape),
        feature_names=tuple(f"observed_{j}" for j in range(columns)),
    )


# Independently hash JSON evidence using the published canonical representation.
def _hash(payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


# Compare actual predictions with an independent augmented normal-equation solution.
def test_ridge_matches_closed_form_with_unpenalized_intercept():
    inputs = _inputs(columns=1)
    fitted = fit(inputs, 11, 8.0, min_train_rows=10)
    training = inputs.features[:10, 0]
    standardized = (training - training.mean()) / training.std()
    design = np.column_stack([np.ones(10), standardized, np.zeros(10)])
    regularizer = np.diag([0.0, 8.0, 8.0])
    coefficients = np.linalg.solve(
        design.T @ design + regularizer, design.T @ inputs.labels[:10]
    )
    evaluation = np.column_stack(
        [
            np.ones(3),
            (inputs.features[11:14, 0] - training.mean()) / training.std(),
            np.zeros(3),
        ]
    )
    np.testing.assert_allclose(
        fitted.predict(inputs, [11, 12, 13]),
        evaluation @ coefficients,
        rtol=1e-13,
        atol=1e-13,
    )
    target = fitted.receipt["targets"]["stock"]
    assert target["eligible_rows"] == list(range(10))
    assert target["dropped_rows"] == [10]
    np.testing.assert_allclose(target["coefficients"], coefficients[1:, 0])
    assert target["intercept"] == pytest.approx(coefficients[0, 0])
    assert fitted.receipt["target_order"] == ["stock", "SPY", "QQQ"]


# Keep a constant response in the intercept even under very strong regularization.
def test_intercept_is_not_penalized():
    inputs = _inputs()
    labels = np.broadcast_to([7.0, -2.0, 0.25], inputs.labels.shape)
    fitted = fit(replace(inputs, labels=labels), 11, 1e12, min_train_rows=10)
    np.testing.assert_array_equal(
        fitted.predict(inputs, [11, 15]), np.tile([7.0, -2.0, 0.25], (2, 1))
    )
    for target in fitted.receipt["targets"].values():
        np.testing.assert_array_equal(target["coefficients"], np.zeros(4))


# Independently fit each target's imputation and scaling on its own eligible rows.
def test_each_target_uses_its_own_training_transform():
    inputs = _inputs(columns=1)
    labels = inputs.labels.copy()
    labels[0, 1] = np.nan
    labels[9, 2] = np.nan
    fitted = fit(replace(inputs, labels=labels), 11, 2.0, min_train_rows=9)
    expected = {"stock": np.arange(10), "SPY": np.arange(1, 10), "QQQ": np.arange(9)}
    for name, rows in expected.items():
        target = fitted.receipt["targets"][name]
        assert target["eligible_rows"] == rows.tolist()
        assert target["transform"]["median"] == [float(np.median(rows))]
        assert target["transform"]["mean"] == [float(np.mean(rows))]
        assert target["transform"]["scale"] == pytest.approx([float(np.std(rows))])
        assert target["training_inputs"]["rows"] == rows.tolist()


# Both the actual endpoint and its publication must be strictly before fitting.
def test_variable_label_endpoints_and_publication_control_eligibility():
    inputs = _inputs()
    ends, available = inputs.label_end_on.copy(), inputs.label_available_on.copy()
    ends[0, 0] = inputs.dates[10]
    available[0, 0] = inputs.dates[10]
    ends[2, 0] = inputs.dates[11]
    available[2, 0] = inputs.dates[11]
    available[3, 1] = inputs.dates[11]
    ends[4, 2] = inputs.dates[-1] + 100 * DAY
    available[4, 2] = inputs.dates[-1] + 102 * DAY
    fitted = fit(
        replace(inputs, label_end_on=ends, label_available_on=available),
        11,
        1.0,
        min_train_rows=8,
    )
    targets = fitted.receipt["targets"]
    assert 0 in targets["stock"]["eligible_rows"]
    assert 2 not in targets["stock"]["eligible_rows"]
    assert 3 not in targets["SPY"]["eligible_rows"]
    assert 4 not in targets["QQQ"]["eligible_rows"]
    assert targets["stock"]["dropped_by_reason"]["endpoint_not_before_fit"] == [2, 10]
    assert targets["SPY"]["dropped_by_reason"]["label_not_available_before_fit"] == [
        3,
        10,
    ]


# Later publication never makes an old feature known at its original decision.
def test_late_features_equal_missing_cells_even_when_known_by_fit():
    inputs = _inputs(columns=1)
    features, available = inputs.features.copy(), inputs.feature_available_on.copy()
    features[0, 0] = 1e9
    available[0, 0] = inputs.dates[2]
    delayed = replace(inputs, features=features, feature_available_on=available)
    features[0, 0] = np.nan
    available[0, 0] = np.datetime64("NaT", "D")
    absent = replace(inputs, features=features, feature_available_on=available)
    late_fit = fit(delayed, 11, 1.0, min_train_rows=10)
    missing_fit = fit(absent, 11, 1.0, min_train_rows=10)
    assert late_fit.sha256 == missing_fit.sha256
    target = late_fit.receipt["targets"]["stock"]
    assert target["feature_known_mask"][0] == [False]
    assert target["feature_missing_mask"][0] == [True]
    assert target["training_inputs"]["known_features"][0] == [None]
    assert target["training_inputs"]["feature_available_on"][0] == [None]
    assert target["transform"]["median"] == [5.0]
    np.testing.assert_array_equal(
        late_fit.predict(inputs, [11]), missing_fit.predict(inputs, [11])
    )


# Entirely unavailable feature columns have a stable zero/unit transformation.
def test_all_missing_columns_and_missingness_indicators_are_retained():
    inputs = _inputs()
    features = inputs.features.copy()
    features[:, 0] = np.nan
    features[::2, 1] = np.nan
    labels = np.tile(np.isnan(features[:, 1, None]).astype(float), (1, 3))
    modified = replace(inputs, features=features, labels=labels)
    fitted = fit(modified, 11, 0.1, min_train_rows=10)
    target = fitted.receipt["targets"]["stock"]
    assert target["transform"]["all_missing"] == [True, False]
    assert target["transform"]["median"][0] == 0.0
    assert target["transform"]["mean"][0] == 0.0
    assert target["transform"]["scale"][0] == 1.0
    assert len(target["coefficients"]) == 4
    assert target["coefficients"][2] == 0.0
    assert target["coefficients"][3] > 0.5
    prediction = fitted.predict(modified, [12, 13])
    assert np.all(prediction[0] > prediction[1])


# Unknown prediction features use the frozen imputer, never their later values.
def test_prediction_masks_features_published_after_the_prediction_date():
    inputs = _inputs(columns=1)
    fitted = fit(inputs, 11, 1.0, min_train_rows=10)
    features, available = inputs.features.copy(), inputs.feature_available_on.copy()
    features[12, 0] = 1e12
    available[12, 0] = inputs.dates[13]
    delayed = replace(inputs, features=features, feature_available_on=available)
    features[12, 0] = np.nan
    missing = replace(inputs, features=features)
    np.testing.assert_array_equal(
        fitted.predict(delayed, [12]), fitted.predict(missing, [12])
    )


# Future outcomes and features do not change an earlier fit or earlier predictions.
def test_future_input_perturbations_preserve_fit_and_prefix_predictions():
    inputs = _inputs()
    fitted = fit(inputs, 11, 1.0, min_train_rows=10)
    features, labels = inputs.features.copy(), inputs.labels.copy()
    ends, available = inputs.label_end_on.copy(), inputs.label_available_on.copy()
    features[13:] *= -1000
    labels[11:] *= 7000
    ends[11:] += 100 * DAY
    available[11:] += 200 * DAY
    changed = replace(
        inputs,
        features=features,
        labels=labels,
        label_end_on=ends,
        label_available_on=available,
    )
    repeated = fit(changed, 11, 1.0, min_train_rows=10)
    assert repeated.sha256 == fitted.sha256
    assert repeated.model_state_sha256 == fitted.model_state_sha256
    assert repeated.receipt == fitted.receipt
    np.testing.assert_array_equal(
        repeated.predict(changed, [11, 12]), fitted.predict(inputs, [11, 12])
    )


# The inference path can be exercised while access to any outcome field is forbidden.
def test_prediction_never_reads_outcomes(monkeypatch):
    inputs = _inputs()
    fitted = fit(inputs, 11, 1.0, min_train_rows=10)
    expected = fitted.predict(inputs, [11, 12])
    original = RegressionInputs.__getattribute__

    # Raise at the first attempted outcome read rather than allowing hidden leakage.
    def reject_outcomes(self, name):
        if name in {"labels", "label_end_on", "label_available_on"}:
            raise AssertionError("prediction read an outcome")
        return original(self, name)

    monkeypatch.setattr(RegressionInputs, "__getattribute__", reject_outcomes)
    np.testing.assert_array_equal(fitted.predict(inputs, [11, 12]), expected)


# Receipts pin all used data and model state with reproducible JSON-only hashes.
def test_receipt_hashes_reconstruct_and_ignore_unconsumed_values():
    inputs = _inputs()
    fitted = fit(inputs, 11, 1.0, min_train_rows=10)
    receipt = fitted.receipt
    assert receipt.pop("sha256") == fitted.sha256 == _hash(receipt)
    evidence = {
        "fit_on": receipt["fit_on"],
        "feature_names": receipt["feature_names"],
        "targets": {
            name: target["training_inputs"]
            for name, target in receipt["targets"].items()
        },
    }
    assert receipt["fitted_input_sha256"] == _hash(evidence)
    state = {
        key: receipt[key]
        for key in (
            "schema",
            "fit_index",
            "fit_on",
            "alpha",
            "feature_names",
            "target_order",
            "fitted_input_sha256",
        )
    }
    state["targets"] = {
        name: {key: target[key] for key in ("transform", "coefficients", "intercept")}
        for name, target in receipt["targets"].items()
    }
    assert fitted.model_state_sha256 == receipt["model_state_sha256"] == _hash(state)
    for target in receipt["targets"].values():
        assert target["fitted_input_sha256"] == _hash(target["training_inputs"])
        assert max(target["eligible_rows"]) < fitted.fit_index
    features = inputs.features.copy()
    features[0, 0] += 0.5
    changed = fit(replace(inputs, features=features), 11, 1.0, min_train_rows=10)
    assert changed.sha256 != fitted.sha256
    assert changed.model_state_sha256 != fitted.model_state_sha256
    assert (
        changed.receipt["fitted_input_sha256"] != fitted.receipt["fitted_input_sha256"]
    )
    assert (
        fit(inputs, 11, 2.0, min_train_rows=10).receipt["fitted_input_sha256"]
        == fitted.receipt["fitted_input_sha256"]
    )


# Caller buffers, exposed arrays and returned receipts cannot mutate retained state.
def test_inputs_and_fit_own_immutable_arrays_and_receipts():
    original = _inputs()
    buffers = {
        name: getattr(original, name).copy()
        for name in (
            "dates",
            "features",
            "feature_available_on",
            "labels",
            "label_end_on",
            "label_available_on",
        )
    }
    inputs = RegressionInputs(**buffers)
    fitted = fit(inputs, 11, 1.0, min_train_rows=10)
    prediction, fingerprint = fitted.predict(inputs, [11]), fitted.sha256
    buffers["features"][:] = 900
    buffers["labels"][:] = -800
    buffers["dates"][:] += 100 * DAY
    np.testing.assert_array_equal(fitted.predict(inputs, [11]), prediction)
    for name in buffers:
        with pytest.raises(ValueError, match="WRITEABLE"):
            getattr(inputs, name).setflags(write=True)
    with pytest.raises(ValueError, match="WRITEABLE"):
        fitted._models[0].coefficients.setflags(write=True)
    with pytest.raises(FrozenInstanceError):
        fitted.alpha = 2.0
    receipt = fitted.receipt
    receipt["targets"]["stock"]["coefficients"][0] = -900
    assert fitted.sha256 == fingerprint
    assert fitted.receipt["targets"]["stock"]["coefficients"][0] != -900


# Every target must independently meet the minimum number of matured observations.
def test_too_few_rows_refuses_the_whole_fit():
    inputs = _inputs()
    labels = inputs.labels.copy()
    labels[:2, 2] = np.nan
    with pytest.raises(
        ValueError, match="QQQ has 8 eligible training rows; requires 9"
    ):
        fit(replace(inputs, labels=labels), 11, 1.0, min_train_rows=9)
    with pytest.raises(ValueError, match="requires 504"):
        fit(inputs, 11, 1.0)


# Dates must already be daily, complete and strictly ordered rather than coerced.
@pytest.mark.parametrize(
    "kind",
    ["strings", "hours", "nat", "reverse", "duplicate", "empty", "matrix", "integer"],
)
def test_malformed_calendars_are_rejected(kind):
    inputs = _inputs()
    dates = inputs.dates.copy()
    if kind == "strings":
        dates = dates.astype(str)
    elif kind == "hours":
        dates = dates.astype("datetime64[h]")
    elif kind == "nat":
        dates[0] = np.datetime64("NaT", "D")
    elif kind == "reverse":
        dates = dates[::-1]
    elif kind == "duplicate":
        dates[1] = dates[0]
    elif kind == "empty":
        dates = dates[:0]
    elif kind == "matrix":
        dates = dates[:, None]
    else:
        dates = dates.astype(int)
    with pytest.raises(ValueError, match="dates"):
        replace(inputs, dates=dates)


# A real matrix cannot acquire its meaning through boolean, complex or text casting.
@pytest.mark.parametrize("field", ["features", "labels"])
@pytest.mark.parametrize(
    "kind",
    [
        "boolean",
        "complex",
        "string",
        "object",
        "positive_inf",
        "negative_inf",
        "mixed_boolean",
    ],
)
def test_nonreal_or_infinite_data_are_rejected(field, kind):
    inputs = _inputs()
    values = getattr(inputs, field).copy()
    if kind == "boolean":
        values = values.astype(bool)
    elif kind == "complex":
        values = values.astype(complex)
    elif kind == "string":
        values = values.astype(str)
    elif kind == "object":
        values = values.astype(object)
    elif kind == "mixed_boolean":
        values = values.tolist()
        values[0][0] = True
    else:
        values[0, 0] = np.inf if kind == "positive_inf" else -np.inf
    with pytest.raises(ValueError, match=field):
        replace(inputs, **{field: values})


# Outcome and feature evidence must keep exact session/column alignment.
@pytest.mark.parametrize(
    "field",
    [
        "features",
        "feature_available_on",
        "labels",
        "label_end_on",
        "label_available_on",
    ],
)
@pytest.mark.parametrize("shape", ["short_rows", "short_columns", "vector"])
def test_misaligned_evidence_is_rejected(field, shape):
    inputs = _inputs()
    value = getattr(inputs, field)
    value = (
        value[:-1]
        if shape == "short_rows"
        else value[:, :-1]
        if shape == "short_columns"
        else value[:, 0]
    )
    with pytest.raises(ValueError, match="shape|align|feature_names"):
        replace(inputs, **{field: value})


# A finite observation requires a genuine daily evidence date, with valid ordering.
@pytest.mark.parametrize(
    "field", ["feature_available_on", "label_end_on", "label_available_on"]
)
@pytest.mark.parametrize("kind", ["nat", "string", "hours"])
def test_missing_or_coerced_evidence_dates_are_rejected(field, kind):
    inputs = _inputs()
    dates = getattr(inputs, field).copy()
    if kind == "nat":
        dates[0, 0] = np.datetime64("NaT", "D")
    elif kind == "string":
        dates = dates.astype(str)
    else:
        dates = dates.astype("datetime64[h]")
    with pytest.raises(ValueError, match="dates|datetime64"):
        replace(inputs, **{field: dates})


# A label cannot end at its decision or become available before it ends.
@pytest.mark.parametrize(
    "kind", ["same_decision", "before_decision", "early_publication"]
)
def test_invalid_outcome_chronology_is_rejected(kind):
    inputs = _inputs()
    ends, available = inputs.label_end_on.copy(), inputs.label_available_on.copy()
    if kind == "early_publication":
        available[0, 0] = ends[0, 0] - DAY
    else:
        ends[0, 0] = inputs.dates[0] - (1 if kind == "before_decision" else 0) * DAY
    with pytest.raises(ValueError, match="endpoint|availability"):
        replace(inputs, label_end_on=ends, label_available_on=available)


# Missing cells may carry NaT and outcome endpoints may extend past the input grid.
def test_missing_evidence_and_beyond_grid_outcomes_are_valid():
    inputs = _inputs()
    features, feature_dates = inputs.features.copy(), inputs.feature_available_on.copy()
    labels, ends, available = (
        inputs.labels.copy(),
        inputs.label_end_on.copy(),
        inputs.label_available_on.copy(),
    )
    features[0, 0], labels[0, 0] = np.nan, np.nan
    feature_dates[0, 0] = ends[0, 0] = available[0, 0] = np.datetime64("NaT", "D")
    ends[-1] += 500 * DAY
    available[-1] += 600 * DAY
    changed = replace(
        inputs,
        features=features,
        feature_available_on=feature_dates,
        labels=labels,
        label_end_on=ends,
        label_available_on=available,
    )
    assert fit(changed, 11, 1.0, min_train_rows=9).predict(changed, [15]).shape == (
        1,
        3,
    )


# Parameters must be finite positive regularization and literal bounded row counts.
@pytest.mark.parametrize("alpha", [0, -1, np.inf, -np.inf, np.nan, True, "1", 1 + 0j])
def test_invalid_ridge_penalties_are_rejected(alpha):
    with pytest.raises(ValueError, match="alpha"):
        fit(_inputs(), 11, alpha, min_train_rows=9)


# Index and minimum-count controls never silently truncate floats or booleans.
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("fit_index", -1),
        ("fit_index", 16),
        ("fit_index", True),
        ("fit_index", 11.0),
        ("min_train_rows", 0),
        ("min_train_rows", 1.0),
        ("min_train_rows", False),
    ],
)
def test_invalid_fit_controls_are_rejected(name, value):
    options = {"fit_index": 11, "alpha": 1.0, "min_train_rows": 9}
    options[name] = value
    with pytest.raises(ValueError, match=name):
        fit(_inputs(), **options)


# Prediction refuses training rows, out-of-range rows and coerced index containers.
@pytest.mark.parametrize(
    "indices",
    [
        [10],
        [-1],
        [16],
        [11.0],
        [True],
        [11, True],
        ["11"],
        11,
        [[11]],
        np.array([], dtype=bool),
    ],
)
def test_invalid_prediction_indices_are_rejected(indices):
    inputs = _inputs()
    fitted = fit(inputs, 11, 1.0, min_train_rows=10)
    with pytest.raises(ValueError, match="indices"):
        fitted.predict(inputs, indices)


# Ordered requests may repeat positions and may intentionally contain no rows.
def test_prediction_preserves_requested_order_and_supports_empty_input():
    inputs = _inputs()
    fitted = fit(inputs, 11, 1.0, min_train_rows=10)
    expected = fitted.predict(inputs, [11, 12])
    np.testing.assert_array_equal(
        fitted.predict(inputs, [12, 11, 12]), expected[[1, 0, 1]]
    )
    assert fitted.predict(inputs, []).shape == (0, 3)


# Calendar or named-column changes cannot silently reinterpret trained coefficients.
def test_prediction_rejects_other_source_calendars_or_feature_order():
    inputs = _inputs()
    fitted = fit(inputs, 11, 1.0, min_train_rows=10)
    with pytest.raises(ValueError, match="calendar|names"):
        fitted.predict(replace(inputs, feature_names=inputs.feature_names[::-1]), [11])
    with pytest.raises(ValueError, match="calendar|names"):
        fitted.predict(replace(inputs, dates=inputs.dates - DAY), [11])
    with pytest.raises(ValueError, match="calendar|names"):
        fitted.predict(_inputs(columns=1), [11])


# Feature names are literal, unique identities in an explicit column order.
@pytest.mark.parametrize(
    "names",
    [
        ("same", "same"),
        ("only",),
        ("", "valid"),
        (" bad", "valid"),
        (1, "valid"),
        {"a", "b"},
        "ab",
    ],
)
def test_invalid_feature_names_are_rejected(names):
    with pytest.raises(ValueError, match="feature_names"):
        replace(_inputs(), feature_names=names)


# Finite source numbers whose arithmetic overflows are refused rather than serialized.
def test_numerical_overflow_fails_closed():
    inputs = _inputs()
    features = inputs.features.copy()
    features[:10, 0] = np.where(np.arange(10) % 2, 1e308, -1e308)
    with pytest.raises(ValueError, match="arithmetic"):
        fit(replace(inputs, features=features), 11, 1.0, min_train_rows=10)


# Unavailable outcomes can change audit classification without changing model identity.
def test_immature_label_missingness_only_changes_the_audit_receipt():
    inputs = _inputs()
    ends, available = inputs.label_end_on.copy(), inputs.label_available_on.copy()
    ends[0, 0] = available[0, 0] = inputs.dates[12]
    immature = replace(inputs, label_end_on=ends, label_available_on=available)
    original = fit(immature, 11, 1.0, min_train_rows=9)
    labels = immature.labels.copy()
    labels[0, 0] = np.nan
    missing = replace(immature, labels=labels)
    changed = fit(missing, 11, 1.0, min_train_rows=9)
    assert original.sha256 != changed.sha256
    assert original.model_state_sha256 == changed.model_state_sha256
    assert (
        original.receipt["fitted_input_sha256"]
        == changed.receipt["fitted_input_sha256"]
    )
    np.testing.assert_array_equal(
        original.predict(immature, [11, 12]), changed.predict(missing, [11, 12])
    )


# Constant observed columns have unit scale without being labelled all-missing.
def test_constant_known_features_have_zero_coefficients_and_unit_scale():
    inputs = _inputs()
    inputs = replace(inputs, features=np.full_like(inputs.features, 6.0))
    fitted = fit(inputs, 11, 2.0, min_train_rows=10)
    target = fitted.receipt["targets"]["stock"]
    assert target["transform"] == {
        "median": [6.0, 6.0],
        "mean": [6.0, 6.0],
        "scale": [1.0, 1.0],
        "all_missing": [False, False],
    }
    np.testing.assert_array_equal(target["coefficients"], np.zeros(4))
    np.testing.assert_allclose(
        fitted.predict(inputs, [11])[0], inputs.labels[:10].mean(axis=0)
    )
