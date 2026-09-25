"""Saved-fit diagnostic acceptance using small real NumPy ridge fixtures only."""

import copy
import hashlib
import json
import math
from dataclasses import replace

import numpy as np
import pytest

from backend.market.forecast_diagnostics import _correlation, _metrics, diagnose
from backend.market.nested_ridge import RegressionInputs, fit


# Create dated synthetic features and outcomes with a genuine two-session label delay.
def _inputs(*, labels=None):
    days = np.arange("2024-01-01", "2024-01-23", dtype="datetime64[D]")
    t = np.arange(20, dtype=float)
    features = np.column_stack((t / 20, np.sin(t)))
    outcomes = np.column_stack(
        (
            0.02 * features[:, 0] + 0.01 * features[:, 1],
            0.01 * np.cos(t),
            0.015 * np.sin(t * 0.4),
        )
    )
    features[1, 0] = np.nan
    return RegressionInputs(
        dates=days[:20],
        features=features,
        feature_available_on=np.broadcast_to(days[:20, None], features.shape),
        labels=outcomes if labels is None else labels,
        label_end_on=np.broadcast_to(days[2:22, None], outcomes.shape),
        label_available_on=np.broadcast_to(days[2:22, None], outcomes.shape),
        feature_names=("linear", "oscillating"),
    )


# Independently preserve each existing receipt and prediction JSON hash convention.
def _hash(value, *, newline=False):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256((body + ("\n" if newline else "")).encode()).hexdigest()


# Bind a deliberately edited saved prediction record without generating its values.
def _prediction_hash(fold):
    fold["predictions_sha256"] = _hash(
        {"start": fold["start"], "stop": fold["stop"], "values": fold["predictions"]},
        newline=True,
    )


# Freeze actual chronological fits and their actual saved predictions for the tests.
def _folds(inputs, spans=((8, 11), (11, 14))):
    folds = []
    for start, stop in spans:
        model = fit(inputs, start, 1.0, min_train_rows=3)
        fold = {
            "start": start,
            "stop": stop,
            "fit": model.receipt,
            "fit_receipt_sha256": model.sha256,
            "model_hash": model.model_state_sha256,
            "predictions": model.predict(inputs, np.arange(start, stop)).tolist(),
        }
        _prediction_hash(fold)
        folds.append(fold)
    return folds


# Run the public observer on exactly six saved decisions without creating more fits.
def _diagnose(inputs, folds, *, evaluated_on="2024-01-20"):
    return diagnose(
        inputs, folds, first_decision=8, stop_decision=14, evaluated_on=evaluated_on
    )


# Rebind a changed receipt's outer hash so semantic checks, not only byte checks, run.
def _receipt_hash(fold):
    receipt = fold["fit"]
    receipt["sha256"] = _hash(
        {key: value for key, value in receipt.items() if key != "sha256"}
    )
    fold["fit_receipt_sha256"] = receipt["sha256"]


# Rehash altered evidence and state while leaving target-level digests bound.
def _rebind_receipt(fold):
    receipt = fold["fit"]
    receipt["fitted_input_sha256"] = _hash(
        {
            "fit_on": receipt["fit_on"],
            "feature_names": receipt["feature_names"],
            "targets": {
                name: target["training_inputs"]
                for name, target in receipt["targets"].items()
            },
        }
    )
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
    receipt["model_state_sha256"] = fold["model_hash"] = _hash(state)
    _receipt_hash(fold)


# Metrics use exact saved predictions and each fit's own target-label mean.
def test_complete_chronological_metrics_match_independent_scalar_calculation():
    inputs = _inputs()
    folds = _folds(inputs)
    result = _diagnose(inputs, folds)
    assert result["coverage"] == {
        "expected_decisions": 6,
        "recorded_decisions": 6,
        "all_decisions_accounted_for": True,
    }
    for column, name in enumerate(("stock", "SPY", "QQQ")):
        predictions, labels, baselines = [], [], []
        for saved, observed in zip(folds, result["actual_folds"], strict=True):
            training = saved["fit"]["targets"][name]["training_inputs"]["labels"]
            baseline = math.fsum(training) / len(training)
            assert observed["training_baseline"][name]["mean"] == pytest.approx(
                baseline
            )
            for index, prediction in zip(
                range(saved["start"], saved["stop"]), saved["predictions"], strict=True
            ):
                predictions.append(prediction[column])
                labels.append(inputs.labels[index, column])
                baselines.append(baseline)
        errors = [p - y for p, y in zip(predictions, labels, strict=True)]
        sse = math.fsum(error * error for error in errors)
        base_sse = math.fsum(
            (p - y) ** 2 for p, y in zip(baselines, labels, strict=True)
        )
        metrics = result["full_sample"]["targets"][name]
        assert metrics["observations"] == metrics["scored"] == 6
        assert metrics["excluded"] == 0
        assert metrics["sse"] == pytest.approx(sse, abs=1e-15)
        assert metrics["rmse"] == pytest.approx(math.sqrt(sse / 6))
        assert metrics["bias"] == pytest.approx(math.fsum(errors) / 6)
        assert metrics["baseline_sse"] == pytest.approx(base_sse)
        assert metrics["sse_skill_vs_training_mean"] == pytest.approx(
            1 - sse / base_sse
        )
        assert metrics["correlation"] == pytest.approx(
            np.corrcoef(predictions, labels)[0, 1]
        )
    assert not result["refit_performed"]
    assert not result["independent_validation"]
    assert not result["adoption_eligible"]


# The unpenalized intercept is not mistaken for the target's training-label mean.
def test_baseline_comes_from_actual_labels_not_intercept_or_feature_mean():
    inputs = _inputs()
    folds = _folds(inputs)
    result = _diagnose(inputs, folds)
    target = folds[0]["fit"]["targets"]["stock"]
    baseline = result["actual_folds"][0]["training_baseline"]["stock"]["mean"]
    assert baseline != pytest.approx(target["intercept"], abs=1e-8)
    assert baseline != pytest.approx(target["transform"]["mean"][0], abs=1e-8)
    assert baseline == pytest.approx(np.mean(target["training_inputs"]["labels"]))


# Exclude fit-cutoff label equality but score equality at evaluation.
def test_strict_training_maturity_and_inclusive_evaluation_boundary():
    inputs = _inputs()
    publications = inputs.label_available_on.copy()
    publications[0, 0] = inputs.dates[8]
    inputs = replace(inputs, label_available_on=publications)
    folds = _folds(inputs)
    result = _diagnose(inputs, folds, evaluated_on=str(inputs.dates[13]))
    used = folds[0]["fit"]["targets"]["stock"]["eligible_rows"]
    assert 0 not in used
    assert 6 not in used  # Endpoint is exactly the fit date.
    equal = next(row for row in result["rows"] if row["decision_index"] == 11)
    assert equal["targets"]["stock"]["label_end_on"] == str(inputs.dates[13])
    assert equal["targets"]["stock"]["exclusions"] == []
    assert result["rows"][-1]["targets"]["stock"]["realized"] is None


# Unseen future outcome values and missingness cannot change an earlier as-of report.
@pytest.mark.parametrize("replacement", [99.0, np.nan])
def test_future_outcome_perturbation_preserves_rows_metrics_and_baselines(replacement):
    inputs = _inputs()
    folds = _folds(inputs)
    before = _diagnose(inputs, folds, evaluated_on=str(inputs.dates[13]))
    labels = inputs.labels.copy()
    labels[12:] = replacement
    after = _diagnose(
        replace(inputs, labels=labels), folds, evaluated_on=str(inputs.dates[13])
    )
    assert after == before
    assert all(
        row["targets"]["stock"]["realized"] is None for row in after["rows"][-2:]
    )


# A delayed publication remains hidden even when its economic endpoint has passed.
def test_unpublished_label_is_masked_and_later_becomes_scoreable():
    inputs = _inputs()
    publication = inputs.label_available_on.copy()
    publication[8, 1] = inputs.dates[18]
    inputs = replace(inputs, label_available_on=publication)
    folds = _folds(inputs)
    early = _diagnose(inputs, folds, evaluated_on=str(inputs.dates[13]))
    item = early["rows"][0]["targets"]["SPY"]
    assert item["realized"] is None
    assert item["exclusions"] == ["label_unpublished_at_evaluation"]
    later = _diagnose(inputs, folds)
    assert later["rows"][0]["targets"]["SPY"]["exclusions"] == []
    assert later["rows"][0]["targets"]["SPY"]["realized"] == inputs.labels[8, 1]


# Missing forecasts stay missing while valid targets retain their own denominators.
def test_explicit_null_forecast_is_counted_and_never_imputed():
    inputs = _inputs()
    folds = _folds(inputs)
    folds[0]["predictions"][0][0] = None
    _prediction_hash(folds[0])
    result = _diagnose(inputs, folds)
    assert result["rows"][0]["targets"]["stock"]["prediction"] is None
    assert result["full_sample"]["targets"]["stock"]["scored"] == 5
    assert result["full_sample"]["targets"]["SPY"]["scored"] == 6
    assert result["full_sample"]["relative_spreads"]["stock_minus_SPY"]["scored"] == 5
    assert result["full_sample"]["relative_spreads"]["SPY_minus_QQQ"]["scored"] == 6


# Keep missing observed labels and timestamps without a complete-case join.
def test_missing_labels_and_endpoint_evidence_keep_all_decisions():
    inputs = _inputs()
    labels, endings, publication = (
        inputs.labels.copy(),
        inputs.label_end_on.copy(),
        inputs.label_available_on.copy(),
    )
    labels[9, 0] = labels[10, 2] = np.nan
    endings[10, 2] = publication[10, 2] = np.datetime64("NaT", "D")
    inputs = replace(
        inputs, labels=labels, label_end_on=endings, label_available_on=publication
    )
    result = _diagnose(inputs, _folds(inputs))
    assert len(result["rows"]) == 6
    assert (
        result["full_sample"]["targets"]["stock"]["exclusion_counts"]["label_missing"]
        == 1
    )
    assert (
        result["full_sample"]["targets"]["QQQ"]["exclusion_counts"][
            "label_endpoint_missing"
        ]
        == 1
    )
    for group in result["full_sample"].values():
        assert all(
            item["scored"] + item["excluded"] == item["observations"] == 6
            for item in group.values()
        )


# Use both targets' past means and reject different outcome horizons.
def test_relative_spread_baseline_and_endpoint_comparability():
    inputs = _inputs()
    endings, available = inputs.label_end_on.copy(), inputs.label_available_on.copy()
    endings[9, 2] = available[9, 2] = inputs.dates[12]
    labels = inputs.labels.copy()
    labels[0, 0] = np.nan
    inputs = replace(
        inputs, labels=labels, label_end_on=endings, label_available_on=available
    )
    result = _diagnose(inputs, _folds(inputs))
    row = result["rows"][0]
    spread = row["relative_spreads"]["stock_minus_SPY"]
    assert (
        spread["baseline"]
        == row["targets"]["stock"]["baseline"] - row["targets"]["SPY"]["baseline"]
    )
    assert spread["realized"] == inputs.labels[8, 0] - inputs.labels[8, 1]
    assert result["full_sample"]["targets"]["QQQ"]["scored"] == 6
    assert result["full_sample"]["relative_spreads"]["stock_minus_QQQ"]["scored"] == 5
    assert (
        "label_endpoints_not_comparable"
        in result["rows"][1]["relative_spreads"]["stock_minus_QQQ"]["exclusions"]
    )


# Perfect constant baselines yield undefined skill and correlation, not invented ones.
def test_zero_baseline_sse_and_variance_have_explicit_null_reasons():
    inputs = _inputs(labels=np.zeros((20, 3)))
    result = _diagnose(inputs, _folds(inputs))
    for group in result["full_sample"].values():
        for metrics in group.values():
            assert metrics["sse"] == metrics["baseline_sse"] == metrics["rmse"] == 0
            assert metrics["sse_skill_vs_training_mean"] is None
            assert metrics["skill_unavailable_reason"] == "baseline_sse_zero"
            assert metrics["correlation"] is None
            assert metrics["correlation_unavailable_reason"] == "both_zero_variance"


# An exact constant cohort cannot acquire apparent model skill from mean rounding.
def test_nonbinary_constant_training_mean_is_exact_on_public_path():
    inputs = _inputs(labels=np.full((20, 3), 0.03))
    endpoints = np.broadcast_to(
        inputs.dates[:, None] + np.timedelta64(1, "D"), inputs.labels.shape
    )
    inputs = replace(
        inputs,
        features=np.zeros_like(inputs.features),
        label_end_on=endpoints,
        label_available_on=endpoints,
    )
    folds = _folds(inputs, ((8, 15),))
    result = diagnose(
        inputs,
        folds,
        first_decision=8,
        stop_decision=15,
        evaluated_on=str(inputs.dates[-1]),
    )
    for name in ("stock", "SPY", "QQQ"):
        assert result["actual_folds"][0]["training_baseline"][name] == {
            "mean": 0.03,
            "rows": 7,
        }
        metrics = result["full_sample"]["targets"][name]
        assert metrics["sse"] == metrics["baseline_sse"] == 0.0
        assert metrics["sse_skill_vs_training_mean"] is None
        assert metrics["skill_unavailable_reason"] == "baseline_sse_zero"
        assert metrics["correlation"] is None
        assert metrics["correlation_unavailable_reason"] == "both_zero_variance"


# A positive representable SSE keeps a positive root-mean-square value after averaging.
def test_rmse_does_not_underflow_when_dividing_a_positive_sse():
    error = math.sqrt(math.ulp(0.0))
    metrics = _metrics(
        [
            {"prediction": value, "realized": 0.0, "baseline": value, "exclusions": []}
            for value in (error, 0.0)
        ]
    )
    assert metrics["sse"] == metrics["baseline_sse"] == math.ulp(0.0)
    expected = error / math.sqrt(2)
    assert metrics["rmse"] == expected
    assert metrics["baseline_rmse"] == expected


# Non-binary constant values remain degenerate even when their rounded mean drifts.
@pytest.mark.parametrize(
    ("predictions", "actual", "reason"),
    [
        ([0.03] * 7, [0.03] * 7, "both_zero_variance"),
        ([0.01] * 73, list(range(73)), "prediction_zero_variance"),
        (list(range(7)), [0.03] * 7, "realized_zero_variance"),
    ],
)
def test_constant_correlation_does_not_become_rounding_noise(
    predictions, actual, reason
):
    assert _correlation(predictions, actual) == (None, reason)


# Correlation preserves tiny genuine variation under translation of near-constant data.
def test_nearly_constant_correlation_is_translation_invariant():
    predictions = [0.03] * 6 + [math.nextafter(0.03, math.inf)]
    actual = list(range(7))
    translated = [value - predictions[0] for value in predictions]
    expected, reason = _correlation(translated, actual)
    value, shifted_reason = _correlation(predictions, actual)
    assert reason is shifted_reason is None
    assert expected == pytest.approx(math.sqrt(3 / 8), rel=1e-14)
    assert value == pytest.approx(expected, rel=1e-14)


# Finite extreme inputs can be normalized before an origin subtraction overflows.
def test_correlation_handles_unrepresentable_unscaled_offsets():
    value, reason = _correlation([-1e308, 0.0, 1e308], [2.0, -4.0, 0.0])
    expected, _ = _correlation([-1.0, 0.0, 1.0], [2.0, -4.0, 0.0])
    assert reason is None
    assert value == pytest.approx(expected, rel=1e-14)


# An entirely missing forecast target produces no score and still reconciles its rows.
def test_empty_scoring_denominator_is_not_zero_error():
    inputs = _inputs()
    folds = _folds(inputs)
    for fold in folds:
        for prediction in fold["predictions"]:
            prediction[0] = None
        _prediction_hash(fold)
    metrics = _diagnose(inputs, folds)["full_sample"]["targets"]["stock"]
    assert metrics["scored"] == 0
    assert metrics["excluded"] == 6
    assert metrics["sse"] is None
    assert metrics["correlation_unavailable_reason"] == "no_scored_observations"


# Every saved fold must cover exactly the caller's declared decision interval.
@pytest.mark.parametrize(
    "mutation",
    [
        "gap",
        "overlap",
        "reverse",
        "tail",
        "fit_date",
        "receipt_hash",
        "prediction_hash",
    ],
)
def test_malformed_or_unbound_fold_evidence_is_rejected(mutation):
    inputs = _inputs()
    folds = _folds(inputs)
    if mutation == "gap":
        folds[1]["start"] += 1
    elif mutation == "overlap":
        folds[1]["start"] -= 1
    elif mutation == "reverse":
        folds.reverse()
    elif mutation == "tail":
        folds.pop()
    elif mutation == "fit_date":
        folds[0]["fit"]["fit_on"] = "2024-01-10"
        _receipt_hash(folds[0])
    elif mutation == "receipt_hash":
        folds[0]["fit_receipt_sha256"] = "0" * 64
    else:
        folds[0]["predictions_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="coverage|fit date|hash differs"):
        _diagnose(inputs, folds)


# A self-rehashed prediction must still agree with saved state applied to dated inputs.
def test_rehashed_wrong_prediction_is_rejected_by_state_application():
    inputs = _inputs()
    folds = _folds(inputs)
    folds[0]["predictions"][0][0] += 0.01
    _prediction_hash(folds[0])
    with pytest.raises(ValueError, match="model-state application"):
        _diagnose(inputs, folds)


# Reject altered training outcomes under old receipts instead of changing baselines.
def test_changed_used_training_source_is_rejected():
    inputs = _inputs()
    folds = _folds(inputs)
    labels = inputs.labels.copy()
    labels[0, 0] += 1
    with pytest.raises(ValueError, match="training evidence differs"):
        _diagnose(replace(inputs, labels=labels), folds)


# JSON numbers and Booleans cannot pass source validation merely by comparing equal.
@pytest.mark.parametrize(
    "field",
    ["labels", "known_features", "rows", "feature_known_mask", "feature_missing_mask"],
)
def test_type_changed_training_evidence_is_rejected_after_outer_rehash(field):
    inputs = _inputs(labels=np.ones((20, 3)))
    folds = _folds(inputs)
    target = folds[0]["fit"]["targets"]["stock"]
    if field == "labels":
        target["training_inputs"][field][0] = True
    elif field == "known_features":
        target["training_inputs"][field][0][0] = False
    elif field == "rows":
        target["training_inputs"][field][0] = False
    else:
        target[field][0][0] = int(target[field][0][0])
    _rebind_receipt(folds[0])
    with pytest.raises(
        ValueError, match="training evidence|target input hash|mask differs"
    ):
        _diagnose(inputs, folds)


# Keep future feature values masked in training evidence and prediction checks.
def test_unavailable_features_cannot_change_saved_state_application():
    inputs = _inputs()
    publication = inputs.feature_available_on.copy()
    publication[[2, 9], 1] = inputs.dates[19]
    inputs = replace(inputs, feature_available_on=publication)
    folds = _folds(inputs)
    before = _diagnose(inputs, folds)
    features = inputs.features.copy()
    features[[2, 9], 1] = 1e9
    assert _diagnose(replace(inputs, features=features), folds) == before


# Replay accepts harmless transform underflow accepted by the original predictor.
def test_saved_state_application_matches_original_numeric_error_policy():
    inputs = _inputs(labels=np.zeros((20, 3)))
    features = np.zeros_like(inputs.features)
    features[:6, 0] = np.array([-1, 1, -1, 1, -1, 1]) * 1e100
    features[8:, 0] = 1e-250
    inputs = replace(inputs, features=features)
    folds = _folds(inputs)
    assert folds[0]["predictions"] == [[0.0, 0.0, 0.0]] * 3
    result = _diagnose(inputs, folds)
    assert result["full_sample"]["targets"]["stock"]["sse"] == 0.0
    assert result["actual_folds"][0]["max_prediction_application_residual"] == 0.0


# Backdated reports cannot expose later decisions or their later training baselines.
def test_evaluation_before_last_declared_decision_is_rejected():
    inputs = _inputs()
    with pytest.raises(ValueError, match="precedes declared decisions"):
        _diagnose(inputs, _folds(inputs), evaluated_on=str(inputs.dates[12]))


# The observer never calls fitting, changes receipts, or aliases its returned evidence.
def test_diagnostics_do_not_refit_or_mutate_inputs(monkeypatch):
    inputs = _inputs()
    folds = _folds(inputs)
    before = copy.deepcopy(folds)

    # Fail if the read-only diagnostic reaches the model fitting entry point.
    def forbidden_fit(*args, **kwargs):
        raise AssertionError("diagnostics cannot fit")

    monkeypatch.setattr("backend.market.nested_ridge.fit", forbidden_fit)
    result = _diagnose(inputs, folds)
    assert folds == before
    result["rows"][0]["targets"]["stock"]["prediction"] = 9
    result["actual_folds"][0]["training_baseline"]["stock"]["mean"] = 9
    assert folds == before
