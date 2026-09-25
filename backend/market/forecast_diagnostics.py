"""Missingness-aware diagnostics of saved chronological ridge forecasts.

No fitting, selection, simulation or provider access occurs here. Saved-state
application verifies prediction consistency, not that an optimizer was correct
or that supplied historical data was actually available at the declared time.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from datetime import date

import numpy as np

from backend.market.nested_ridge import SCHEMA, TARGET_ORDER, RegressionInputs

TOLERANCE = 1e-12
SPREADS = tuple(
    (a, b) for i, a in enumerate(TARGET_ORDER) for b in TARGET_ORDER[i + 1 :]
)


# Stop at an unsupported evidence boundary instead of emitting a partial score.
def _require(condition, message):
    if not condition:
        raise ValueError(message)


# Preserve the two existing canonical JSON hash conventions without conflating them.
def _hash(value, *, newline=False):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256((encoded + ("\n" if newline else "")).encode()).hexdigest()


# Require a plain daily cutoff without silently truncating a timestamp.
def _day(value):
    text = str(value)
    _require(
        date.fromisoformat(text).isoformat() == text, "evaluated_on needs YYYY-MM-DD"
    )
    return text


# Validate explicit source indices without accepting Booleans or fractional rows.
def _index(value, name):
    _require(type(value) is int and value >= 0, f"{name} needs a nonnegative integer")
    return value


# Keep metric arithmetic finite and reject overflow instead of inventing a score.
def _finite(value):
    _require(math.isfinite(value), "diagnostic arithmetic is not finite")
    return float(value)


# Reconstruct only the past data actually eligible for one saved target's training.
def _training(inputs, start, column):
    cutoff = inputs.dates[start]
    eligible = (
        np.isfinite(inputs.labels[:start, column])
        & (inputs.label_end_on[:start, column] < cutoff)
        & (inputs.label_available_on[:start, column] < cutoff)
    )
    rows = np.flatnonzero(eligible)
    values = inputs.features[rows]
    available = inputs.feature_available_on[rows]
    known = np.isfinite(values) & (available <= inputs.dates[rows, None])
    evidence = {
        "rows": rows.tolist(),
        "decision_on": inputs.dates[rows].astype(str).tolist(),
        "known_features": [
            [float(v) if k else None for v, k in zip(row, mask, strict=True)]
            for row, mask in zip(values, known, strict=True)
        ],
        "feature_available_on": [
            [str(v) if k else None for v, k in zip(row, mask, strict=True)]
            for row, mask in zip(available, known, strict=True)
        ],
        "labels": inputs.labels[rows, column].tolist(),
        "label_end_on": inputs.label_end_on[rows, column].astype(str).tolist(),
        "label_available_on": inputs.label_available_on[rows, column]
        .astype(str)
        .tolist(),
    }
    return rows, known, evidence


# Match target evidence to its source cohort and derive a training-only mean.
def _target(inputs, start, column, target, minimum):
    rows, known, evidence = _training(inputs, start, column)
    _require(
        len(rows) >= minimum, "saved target has insufficient eligible training rows"
    )
    _require(
        _hash(target["eligible_rows"]) == _hash(rows.tolist()), "eligible rows differ"
    )
    submitted_hash = _hash(target["training_inputs"])
    _require(submitted_hash == _hash(evidence), "training evidence differs from source")
    _require(
        target["fitted_input_sha256"] == submitted_hash, "target input hash differs"
    )
    _require(
        _hash(target["feature_known_mask"]) == _hash(known.tolist()),
        "training known mask differs",
    )
    _require(
        _hash(target["feature_missing_mask"]) == _hash((~known).tolist()),
        "training missing mask differs",
    )
    labels = evidence["labels"]
    baseline = _finite(
        labels[0]
        if min(labels) == max(labels)
        else math.fsum(value / len(rows) for value in labels)
    )
    return {"mean": baseline, "rows": len(rows)}


# Bind a saved receipt to its cutoff, source observations and declared model-state hash.
def _receipt(inputs, fold):
    start, receipt = fold["start"], fold["fit"]
    _require(receipt["schema"] == SCHEMA, "unsupported ridge receipt schema")
    _require(
        receipt["fit_index"] == start and type(receipt["fit_index"]) is int,
        "fit index must equal fold start",
    )
    _require(
        receipt["fit_on"] == str(inputs.dates[start]), "fit date differs from source"
    )
    _require(receipt["target_order"] == list(TARGET_ORDER), "target order differs")
    _require(
        receipt["feature_names"] == list(inputs.feature_names), "feature order differs"
    )
    _require(
        _hash(receipt["candidate_rows"]) == _hash(list(range(start))),
        "candidate rows differ",
    )
    minimum = _index(receipt["min_train_rows"], "min_train_rows")
    _require(minimum > 0, "min_train_rows must be positive")
    _require(
        type(receipt["alpha"]) in (int, float) and 0 < receipt["alpha"] < math.inf,
        "invalid saved alpha",
    )
    body = {key: value for key, value in receipt.items() if key != "sha256"}
    _require(
        receipt["sha256"] == fold["fit_receipt_sha256"] == _hash(body),
        "receipt hash differs",
    )
    baselines = {
        name: _target(inputs, start, column, receipt["targets"][name], minimum)
        for column, name in enumerate(TARGET_ORDER)
    }
    evidence = {
        "fit_on": receipt["fit_on"],
        "feature_names": receipt["feature_names"],
        "targets": {
            name: receipt["targets"][name]["training_inputs"] for name in TARGET_ORDER
        },
    }
    _require(
        receipt["fitted_input_sha256"] == _hash(evidence), "combined input hash differs"
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
        name: {
            key: receipt["targets"][name][key]
            for key in ("transform", "coefficients", "intercept")
        }
        for name in TARGET_ORDER
    }
    _require(
        receipt["model_state_sha256"] == fold["model_hash"] == _hash(state),
        "model-state hash differs",
    )
    return baselines


# Validate saved numeric vectors before applying any transform or coefficient.
def _vector(value, count, name):
    _require(isinstance(value, list) and len(value) == count, f"{name}: wrong shape")
    _require(
        all(type(v) in (int, float) and math.isfinite(v) for v in value),
        f"{name}: finite numeric values required",
    )
    return np.asarray(value, dtype=float)


# Apply saved state only to recorded finite forecasts, never replacing explicit nulls.
def _predictions(inputs, fold):
    start, stop, values = fold["start"], fold["stop"], fold["predictions"]
    _require(
        isinstance(values, list) and len(values) == stop - start,
        "prediction row count differs",
    )
    _require(
        fold["predictions_sha256"]
        == _hash({"start": start, "stop": stop, "values": values}, newline=True),
        "prediction hash differs",
    )
    saved = np.full((stop - start, 3), np.nan)
    for i, row in enumerate(values):
        _require(
            isinstance(row, list) and len(row) == 3, "prediction target shape differs"
        )
        for j, value in enumerate(row):
            if value is not None:
                _require(
                    type(value) in (int, float) and math.isfinite(value),
                    "invalid prediction",
                )
                saved[i, j] = value
    features, publications = (
        inputs.features[start:stop],
        inputs.feature_available_on[start:stop],
    )
    known = np.isfinite(features) & (publications <= inputs.dates[start:stop, None])
    count, residual = features.shape[1], 0.0
    for column, name in enumerate(TARGET_ORDER):
        target = fold["fit"]["targets"][name]
        transform = target["transform"]
        median = _vector(transform["median"], count, "median")
        mean = _vector(transform["mean"], count, "mean")
        scale = _vector(transform["scale"], count, "scale")
        coefficients = _vector(target["coefficients"], 2 * count, "coefficients")
        _require(np.all(scale > 0), "saved scales must be positive")
        intercept = target["intercept"]
        _require(
            type(intercept) in (int, float) and math.isfinite(intercept),
            "invalid intercept",
        )
        present = np.isfinite(saved[:, column])
        if not present.any():
            continue
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            imputed = np.where(known[present], features[present], median)
            design = np.concatenate(
                ((imputed - mean) / scale, (~known[present]).astype(float)), axis=1
            )
            computed = design @ coefficients + intercept
        _require(np.isfinite(computed).all(), "saved-state application is not finite")
        _require(
            np.allclose(
                saved[present, column], computed, rtol=TOLERANCE, atol=TOLERANCE
            ),
            "saved predictions differ from model-state application",
        )
        residual = max(
            residual, float(np.max(np.abs(saved[present, column] - computed)))
        )
    return saved, residual


# Keep absent dates explicit rather than turning them into a false maturity date.
def _date_or_none(value):
    return None if np.isnat(value) else str(value)


# Mask unseen outcomes and retain overlapping exclusion reasons for each dated target.
def _observation(inputs, index, column, prediction, baseline, evaluated_on):
    ending = _date_or_none(inputs.label_end_on[index, column])
    available = _date_or_none(inputs.label_available_on[index, column])
    reasons = [] if math.isfinite(prediction) else ["forecast_missing"]
    timing = []
    for value, absent, future in (
        (ending, "label_endpoint_missing", "label_endpoint_after_evaluation"),
        (available, "label_availability_missing", "label_unpublished_at_evaluation"),
    ):
        if value is None:
            timing.append(absent)
        elif value > evaluated_on:
            timing.append(future)
    actual = inputs.labels[index, column]
    unseen = any(
        reason in timing
        for reason in (
            "label_endpoint_after_evaluation",
            "label_unpublished_at_evaluation",
        )
    )
    if not unseen and not np.isfinite(actual):
        timing.append("label_missing")
    return {
        "prediction": float(prediction) if math.isfinite(prediction) else None,
        "realized": float(actual) if not timing else None,
        "label_end_on": ending,
        "label_available_on": available,
        "baseline": baseline,
        "exclusions": reasons + timing,
    }


# Compare target spreads only on jointly observable labels with matching endpoints.
def _spread(targets, left, right):
    a, b = targets[left], targets[right]
    reasons = [
        f"{name}:{reason}"
        for name, item in ((left, a), (right, b))
        for reason in item["exclusions"]
    ]
    matching = a["label_end_on"] is not None and a["label_end_on"] == b["label_end_on"]
    if not matching:
        reasons.append("label_endpoints_not_comparable")
    prediction = (
        None
        if a["prediction"] is None or b["prediction"] is None
        else _finite(a["prediction"] - b["prediction"])
    )
    actual = (
        None
        if not matching or a["realized"] is None or b["realized"] is None
        else _finite(a["realized"] - b["realized"])
    )
    dates = (a["label_available_on"], b["label_available_on"])
    return {
        "prediction": prediction,
        "realized": actual,
        "label_end_on": a["label_end_on"] if matching else None,
        "label_available_on": max(dates) if all(dates) else None,
        "baseline": _finite(a["baseline"] - b["baseline"]),
        "exclusions": reasons,
    }


# Measure Pearson correlation with scaled centered values and explicit degeneracy.
def _correlation(predictions, actual):
    n = len(actual)
    if n < 2:
        return None, "fewer_than_two_scored_observations"
    centered = []
    for values in (predictions, actual):
        if min(values) == max(values):
            centered.append(None)
            continue
        offsets = [value - values[0] for value in values]
        if not all(map(math.isfinite, offsets)):
            magnitude = max(map(abs, values))
            scaled = [value / magnitude for value in values]
            offsets = [value - scaled[0] for value in scaled]
        scale = max(map(abs, offsets))
        normalized = [value / scale for value in offsets]
        mean = math.fsum(normalized) / n
        centered.append([value - mean for value in normalized])
    if centered[0] is None or centered[1] is None:
        reason = (
            "both_zero_variance"
            if centered == [None, None]
            else (
                "prediction_zero_variance"
                if centered[0] is None
                else "realized_zero_variance"
            )
        )
        return None, reason
    x, y = centered
    value = math.fsum(a * b for a, b in zip(x, y, strict=True)) / math.sqrt(
        math.fsum(a * a for a in x) * math.fsum(b * b for b in y)
    )
    return min(1.0, max(-1.0, _finite(value))), None


# Sum finite squared errors without silently converting an underflowed error to zero.
def _sse(errors):
    total = _finite(math.fsum(_finite(value * value) for value in errors))
    _require(total > 0 or not any(errors), "squared-error arithmetic underflowed")
    return total


# Use only complete observable pairs and report the exact denominator and exclusions.
def _metrics(observations):
    usable = [item for item in observations if not item["exclusions"]]
    n = len(usable)
    result = {
        "observations": len(observations),
        "scored": n,
        "excluded": len(observations) - n,
        "exclusion_counts": dict(
            Counter(reason for item in observations for reason in item["exclusions"])
        ),
        **{
            key: None
            for key in (
                "sse",
                "rmse",
                "bias",
                "correlation",
                "baseline_sse",
                "baseline_rmse",
                "sse_skill_vs_training_mean",
            )
        },
        "correlation_unavailable_reason": "no_scored_observations",
        "skill_unavailable_reason": "no_scored_observations",
    }
    if not n:
        return result
    predictions, actual = (
        [item["prediction"] for item in usable],
        [item["realized"] for item in usable],
    )
    errors = [_finite(p - y) for p, y in zip(predictions, actual, strict=True)]
    baseline_errors = [_finite(item["baseline"] - item["realized"]) for item in usable]
    sse, baseline_sse = _sse(errors), _sse(baseline_errors)
    correlation, reason = _correlation(predictions, actual)
    result.update(
        sse=sse,
        rmse=math.sqrt(sse) / math.sqrt(n),
        bias=_finite(math.fsum(value / n for value in errors)),
        correlation=correlation,
        correlation_unavailable_reason=reason,
        baseline_sse=baseline_sse,
        baseline_rmse=math.sqrt(baseline_sse) / math.sqrt(n),
        sse_skill_vs_training_mean=None
        if baseline_sse == 0
        else _finite(1 - sse / baseline_sse),
        skill_unavailable_reason="baseline_sse_zero" if baseline_sse == 0 else None,
    )
    return result


# Pool actual observation errors, never averages of fold RMSE or correlation values.
def _summary(rows):
    return {
        group: {name: _metrics([row[group][name] for row in rows]) for name in names}
        for group, names in (
            ("targets", TARGET_ORDER),
            ("relative_spreads", [f"{a}_minus_{b}" for a, b in SPREADS]),
        )
    }


# Validate and score one saved fold without changing its inputs, fit or predictions.
def _fold(inputs, fold, evaluated_on):
    baselines = _receipt(inputs, fold)
    predictions, residual = _predictions(inputs, fold)
    rows = []
    for offset, index in enumerate(range(fold["start"], fold["stop"])):
        targets = {
            name: _observation(
                inputs,
                index,
                column,
                predictions[offset, column],
                baselines[name]["mean"],
                evaluated_on,
            )
            for column, name in enumerate(TARGET_ORDER)
        }
        rows.append(
            {
                "decision_index": index,
                "decision_on": str(inputs.dates[index]),
                "fold_start": fold["start"],
                "targets": targets,
                "relative_spreads": {
                    f"{a}_minus_{b}": _spread(targets, a, b) for a, b in SPREADS
                },
            }
        )
    summary = {
        key: fold[key]
        for key in (
            "start",
            "stop",
            "fit_receipt_sha256",
            "model_hash",
            "predictions_sha256",
        )
    }
    summary.update(
        fit_on=fold["fit"]["fit_on"],
        training_baseline=baselines,
        max_prediction_application_residual=residual,
        **_summary(rows),
    )
    return rows, summary


# Diagnose exactly the declared chronological coverage using only saved model state.
def diagnose(
    inputs: RegressionInputs,
    outer_folds,
    *,
    first_decision,
    stop_decision,
    evaluated_on,
) -> dict:
    try:
        _require(isinstance(inputs, RegressionInputs), "RegressionInputs are required")
        first = _index(first_decision, "first_decision")
        stop = _index(stop_decision, "stop_decision")
        _require(first < stop <= len(inputs.dates), "invalid declared decision bounds")
        cutoff = _day(evaluated_on)
        _require(
            cutoff >= str(inputs.dates[stop - 1]),
            "evaluation precedes declared decisions",
        )
        _require(
            isinstance(outer_folds, Sequence)
            and not isinstance(outer_folds, (str, bytes))
            and len(outer_folds) > 0,
            "saved outer folds are required",
        )
        rows, summaries, next_start = [], [], first
        for fold in outer_folds:
            start, end = (
                _index(fold["start"], "fold start"),
                _index(fold["stop"], "fold stop"),
            )
            _require(
                start == next_start and start < end <= stop,
                "fold coverage is not exact and contiguous",
            )
            values, summary = _fold(inputs, fold, cutoff)
            rows.extend(values)
            summaries.append(summary)
            next_start = end
        _require(next_start == stop, "fold coverage does not reach declared stop")
        return {
            "schema": "chronological-forecast-diagnostics/1",
            "first_decision": first,
            "stop_decision": stop,
            "evaluated_on": cutoff,
            "full_sample": _summary(rows),
            "actual_folds": summaries,
            "rows": rows,
            "coverage": {
                "expected_decisions": stop - first,
                "recorded_decisions": len(rows),
                "all_decisions_accounted_for": len(rows) == stop - first,
            },
            "verification": {
                "receipt_and_prediction_hashes_checked": True,
                "training_inputs_matched": True,
                "saved_state_application_checked": True,
                "prediction_relative_tolerance": TOLERANCE,
                "prediction_absolute_tolerance": TOLERANCE,
                "fit_optimizer_verified": False,
                "input_source_provenance_verified": False,
            },
            "definitions": {
                "errors": (
                    "Forecast minus realized label; SSE is squared log-return units, "
                    "RMSE and bias are log-return units for the supplied gross "
                    "proxies, not funded P&L."
                ),
                "baseline": (
                    "Each target's own eligible training-label mean at that fold's "
                    "cutoff; spread baseline is the difference of those means, "
                    "not a paired-cohort refit."
                ),
                "availability": (
                    "Training endpoints/publications strictly precede fit. Evaluated "
                    "endpoints/publications may equal evaluated_on. Unseen outcome "
                    "values and missingness are masked."
                ),
                "spreads": (
                    "Endpoints must match and both targets must be scoreable. Common "
                    "label start, units and economic basis remain caller-attested."
                ),
                "exclusions": (
                    "Every declared decision remains. Exclusion reasons may overlap; "
                    "scored plus excluded reconciles observations for each "
                    "target/spread."
                ),
                "dependence": (
                    "Forward labels may overlap across decisions and folds; these "
                    "observations are not independent trials. No probability "
                    "calibration or significance claim."
                ),
                "scope": (
                    "Saved-state application is not proof of correct optimization or "
                    "vendor availability. Self-consistent hashes are not signed "
                    "provenance. This is examined-data diagnostic evidence."
                ),
            },
            "refit_performed": False,
            "independent_validation": False,
            "historical_availability_verified": False,
            "adoption_eligible": False,
        }
    except (KeyError, TypeError, OverflowError, FloatingPointError) as exc:
        raise ValueError(f"Malformed or nonfinite forecast evidence: {exc}") from exc
