"""Causal, separately fitted ridge targets for examined-data research only.

This kernel neither selects a policy nor authenticates historical availability.
Caller-supplied daily evidence gates every feature at its original decision and
every outcome at the fit boundary. No network, market store, or account is used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from numbers import Real

import numpy as np

TARGET_ORDER = ("stock", "SPY", "QQQ")
SCHEMA = "nested-ridge-fit/1"


# Copy validated numeric arrays onto immutable bytes, not caller-owned buffers.
def _owned(array: np.ndarray) -> np.ndarray:
    return np.frombuffer(array.tobytes(order="C"), dtype=array.dtype).reshape(
        array.shape
    )


# Accept real numeric arrays without converting strings, booleans or complex data.
def _real_array(value: np.ndarray, name: str) -> np.ndarray:
    if isinstance(value, (list, tuple)):
        original = np.asarray(value, dtype=object)
        if any(
            isinstance(item, (bool, np.bool_)) or not isinstance(item, Real)
            for item in original.flat
        ):
            raise ValueError(
                f"{name} must contain real numeric values, not coerced data"
            )
    array = np.asarray(value)
    if array.dtype.kind not in "iuf":
        raise ValueError(f"{name} must contain real numeric values, not coerced data")
    with np.errstate(over="ignore", invalid="ignore"):
        result = array.astype(np.float64)
    if np.isinf(result).any():
        raise ValueError(f"{name} must not contain infinity or overflow")
    return result


# Require actual daily datetime arrays so subday information cannot be truncated.
def _daily_array(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype != np.dtype("datetime64[D]"):
        raise ValueError(f"{name} must use datetime64[D] without date coercion")
    return array


# Bind feature columns to a stable explicit order or documented positional names.
def _names(value: tuple[str, ...] | None, count: int) -> tuple[str, ...]:
    if value is None:
        return tuple(f"feature_{column}" for column in range(count))
    if not isinstance(value, (tuple, list)) or len(value) != count:
        raise ValueError("feature_names must be an ordered name for each feature")
    if any(
        not isinstance(name, str) or not name or name.strip() != name for name in value
    ):
        raise ValueError("feature_names must contain nonempty plain strings")
    if len(set(value)) != count:
        raise ValueError("feature_names must be unique")
    return tuple(value)


# Validate outcome timing without imposing any fixed forecast horizon.
def _validate_labels(labels, ends, available, dates) -> None:
    shape = (len(dates), len(TARGET_ORDER))
    if labels.shape != shape or ends.shape != shape or available.shape != shape:
        raise ValueError("labels and their dates must have shape (sessions, 3)")
    finite = np.isfinite(labels)
    if np.any(finite & (np.isnat(ends) | np.isnat(available))):
        raise ValueError("finite labels require endpoint and availability dates")
    if np.any(finite & (ends <= dates[:, None])):
        raise ValueError("finite label endpoints must be after their decision dates")
    if np.any(finite & (available < ends)):
        raise ValueError("finite label availability must not precede its endpoint")


@dataclass(frozen=True, slots=True)
class RegressionInputs:
    """Owned daily feature evidence and ordered stock/SPY/QQQ outcome evidence."""

    dates: np.ndarray
    features: np.ndarray
    feature_available_on: np.ndarray
    labels: np.ndarray
    label_end_on: np.ndarray
    label_available_on: np.ndarray
    feature_names: tuple[str, ...] | None = None

    # Validate the complete evidence shape and freeze independent input buffers.
    def __post_init__(self) -> None:
        dates = _daily_array(self.dates, "dates")
        if dates.ndim != 1 or not len(dates) or np.isnat(dates).any():
            raise ValueError("dates must be a nonempty daily calendar without NaT")
        if np.any(dates[1:] <= dates[:-1]):
            raise ValueError("dates must be strictly increasing and unique")
        features = _real_array(self.features, "features")
        if (
            features.ndim != 2
            or features.shape[0] != len(dates)
            or not features.shape[1]
        ):
            raise ValueError("features must have shape (sessions, nonempty features)")
        feature_dates = _daily_array(self.feature_available_on, "feature_available_on")
        if feature_dates.shape != features.shape:
            raise ValueError("feature_available_on must align with features")
        if np.any(np.isfinite(features) & np.isnat(feature_dates)):
            raise ValueError("finite features require publication dates")
        labels = _real_array(self.labels, "labels")
        ends = _daily_array(self.label_end_on, "label_end_on")
        available = _daily_array(self.label_available_on, "label_available_on")
        _validate_labels(labels, ends, available, dates)
        for name, array in (
            ("dates", dates),
            ("features", features),
            ("feature_available_on", feature_dates),
            ("labels", labels),
            ("label_end_on", ends),
            ("label_available_on", available),
        ):
            object.__setattr__(self, name, _owned(array))
        object.__setattr__(
            self, "feature_names", _names(self.feature_names, features.shape[1])
        )


# Serialize only finite JSON-safe evidence in a deterministic field order.
def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


# Fingerprint canonical evidence without depending on Python object serialization.
def _digest(value: dict) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


# Keep integer controls explicit instead of treating booleans or floats as indices.
def _integer(value: int, name: str, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return int(value)


# Mark a feature known only when it was published by its own decision session.
def _known(inputs: RegressionInputs, rows: np.ndarray) -> np.ndarray:
    return np.isfinite(inputs.features[rows]) & (
        inputs.feature_available_on[rows] <= inputs.dates[rows, None]
    )


# Validate explicit row indices without silently treating booleans as positions.
def _prediction_rows(indices, fit_index: int, count: int) -> np.ndarray:
    if isinstance(indices, (tuple, list)) and any(
        isinstance(item, (bool, np.bool_)) or not isinstance(item, (int, np.integer))
        for item in indices
    ):
        raise ValueError("prediction indices must contain integers, not coerced data")
    rows = np.asarray(indices)
    empty_sequence = isinstance(indices, (tuple, list)) and not indices
    if rows.ndim != 1 or (not empty_sequence and rows.dtype.kind not in "iu"):
        raise ValueError(
            "prediction indices must be a one-dimensional integer sequence"
        )
    if np.any(rows < fit_index) or np.any(rows >= count):
        raise ValueError(
            "prediction indices must be at or after fit_index and within the calendar"
        )
    return rows.astype(np.int64)


@dataclass(frozen=True, slots=True)
class _TargetFit:
    """Frozen preprocessing and coefficients for one independently trained target."""

    median: np.ndarray
    mean: np.ndarray
    scale: np.ndarray
    coefficients: np.ndarray
    intercept: float

    # Impute and standardize with training parameters, retaining missing indicators.
    def design(self, features: np.ndarray, known: np.ndarray) -> np.ndarray:
        imputed = np.where(known, features, self.median)
        return np.concatenate(
            ((imputed - self.mean) / self.scale, (~known).astype(float)), axis=1
        )


@dataclass(frozen=True, slots=True)
class RidgeFit:
    """A frozen fit and replayable receipt, not a historical-quality certificate."""

    fit_index: int
    alpha: float
    feature_names: tuple[str, ...]
    sha256: str
    model_state_sha256: str
    _dates: np.ndarray = field(repr=False)
    _models: tuple[_TargetFit, ...] = field(repr=False)
    _receipt_json: str = field(repr=False)

    # Return a fresh receipt so caller edits cannot change the retained proof.
    @property
    def receipt(self) -> dict:
        return json.loads(self._receipt_json)

    # Predict only at or after fitting, using feature evidence and never labels.
    def predict(self, inputs: RegressionInputs, indices) -> np.ndarray:
        if not isinstance(inputs, RegressionInputs):
            raise ValueError("prediction inputs must be RegressionInputs")
        if inputs.feature_names != self.feature_names or not np.array_equal(
            inputs.dates, self._dates
        ):
            raise ValueError(
                "prediction calendar and ordered feature names must match the fit"
            )
        rows = _prediction_rows(indices, self.fit_index, len(self._dates))
        known = _known(inputs, rows)
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                predictions = np.column_stack(
                    [
                        model.design(inputs.features[rows], known) @ model.coefficients
                        + model.intercept
                        for model in self._models
                    ]
                )
        except FloatingPointError as error:
            raise ValueError("prediction arithmetic is not finite") from error
        if not np.isfinite(predictions).all():
            raise ValueError("prediction arithmetic is not finite")
        return predictions


# Fit imputation, scaling and an unpenalized intercept on one target's used rows.
def _fit_target(
    features: np.ndarray, known: np.ndarray, labels: np.ndarray, alpha: float
):
    count = features.shape[1]
    median = np.zeros(count)
    all_missing = ~known.any(axis=0)
    for column in range(count):
        values = features[known[:, column], column]
        if len(values):
            median[column] = np.median(values)
    imputed = np.where(known, features, median)
    mean = imputed.mean(axis=0)
    scale = imputed.std(axis=0)
    scale[scale == 0] = 1.0
    design = np.concatenate(((imputed - mean) / scale, (~known).astype(float)), axis=1)
    design_mean = design.mean(axis=0)
    label_mean = float(labels.mean())
    centered = design - design_mean
    gram = centered.T @ centered + alpha * np.eye(2 * count)
    coefficients = np.linalg.solve(gram, centered.T @ (labels - label_mean))
    intercept = float(label_mean - design_mean @ coefficients)
    model = _TargetFit(
        *(_owned(value) for value in (median, mean, scale, coefficients)), intercept
    )
    if not all(
        np.isfinite(value).all() for value in (median, mean, scale, coefficients)
    ) or not np.isfinite(intercept):
        raise ValueError("fit arithmetic is not finite")
    return model, all_missing


# Retain only values that actually entered a target's fit, masking unknown cells.
def _training_evidence(
    inputs: RegressionInputs, rows: np.ndarray, known: np.ndarray, target: int
) -> dict:
    values = inputs.features[rows]
    available = inputs.feature_available_on[rows]
    return {
        "rows": rows.tolist(),
        "decision_on": inputs.dates[rows].astype(str).tolist(),
        "known_features": [
            [
                float(value) if valid else None
                for value, valid in zip(row, mask, strict=True)
            ]
            for row, mask in zip(values, known, strict=True)
        ],
        "feature_available_on": [
            [
                str(value) if valid else None
                for value, valid in zip(row, mask, strict=True)
            ]
            for row, mask in zip(available, known, strict=True)
        ],
        "labels": inputs.labels[rows, target].tolist(),
        "label_end_on": inputs.label_end_on[rows, target].astype(str).tolist(),
        "label_available_on": inputs.label_available_on[rows, target]
        .astype(str)
        .tolist(),
    }


# Select one target's strictly matured rows and record every excluded prefix row.
def _target_receipt(
    inputs: RegressionInputs,
    fit_index: int,
    target: int,
    alpha: float,
    min_train_rows: int,
):
    candidates = np.arange(fit_index)
    fit_date = inputs.dates[fit_index]
    finite = np.isfinite(inputs.labels[candidates, target])
    ended = inputs.label_end_on[candidates, target] < fit_date
    available = inputs.label_available_on[candidates, target] < fit_date
    eligible = finite & ended & available
    rows = candidates[eligible]
    if len(rows) < min_train_rows:
        raise ValueError(
            f"{TARGET_ORDER[target]} has {len(rows)} eligible training rows; "
            f"requires {min_train_rows}"
        )
    known = _known(inputs, rows)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            model, all_missing = _fit_target(
                inputs.features[rows], known, inputs.labels[rows, target], alpha
            )
    except (FloatingPointError, np.linalg.LinAlgError) as error:
        raise ValueError(f"{TARGET_ORDER[target]} fit arithmetic failed") from error
    evidence = _training_evidence(inputs, rows, known, target)
    return model, {
        "eligible_rows": rows.tolist(),
        "dropped_rows": candidates[~eligible].tolist(),
        "dropped_by_reason": {
            "label_missing": candidates[~finite].tolist(),
            "endpoint_not_before_fit": candidates[finite & ~ended].tolist(),
            "label_not_available_before_fit": candidates[finite & ~available].tolist(),
        },
        "feature_known_mask": known.tolist(),
        "feature_missing_mask": (~known).tolist(),
        "transform": {
            "median": model.median.tolist(),
            "mean": model.mean.tolist(),
            "scale": model.scale.tolist(),
            "all_missing": all_missing.tolist(),
        },
        "coefficients": model.coefficients.tolist(),
        "intercept": model.intercept,
        "training_inputs": evidence,
        "fitted_input_sha256": _digest(evidence),
    }


# Fit three separate causal ridge regressions and freeze their complete evidence.
def fit(
    inputs: RegressionInputs, fit_index: int, alpha: float, *, min_train_rows: int = 504
) -> RidgeFit:
    if not isinstance(inputs, RegressionInputs):
        raise ValueError("inputs must be RegressionInputs")
    fit_index = _integer(fit_index, "fit_index", 0)
    min_train_rows = _integer(min_train_rows, "min_train_rows", 1)
    if fit_index >= len(inputs.dates):
        raise ValueError("fit_index must identify a source session")
    if (
        isinstance(alpha, (bool, np.bool_))
        or not isinstance(alpha, Real)
        or not np.isfinite(alpha)
        or alpha <= 0
    ):
        raise ValueError("alpha must be a finite positive real number")
    alpha = float(alpha)
    if not np.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha must remain finite and positive in float64")
    models, targets = [], {}
    for target, name in enumerate(TARGET_ORDER):
        model, receipt = _target_receipt(
            inputs, fit_index, target, alpha, min_train_rows
        )
        models.append(model)
        targets[name] = receipt
    input_evidence = {
        "fit_on": str(inputs.dates[fit_index]),
        "feature_names": list(inputs.feature_names),
        "targets": {
            name: target["training_inputs"] for name, target in targets.items()
        },
    }
    receipt = {
        "schema": SCHEMA,
        "fit_index": fit_index,
        "fit_on": str(inputs.dates[fit_index]),
        "alpha": alpha,
        "min_train_rows": min_train_rows,
        "target_order": list(TARGET_ORDER),
        "feature_names": list(inputs.feature_names),
        "candidate_rows": list(range(fit_index)),
        "feature_timing": "available_on <= original decision date",
        "label_timing": "decision < fit, endpoint < fit, availability < fit",
        "objective": (
            "sum squared error + alpha * squared coefficient norm; "
            "unpenalized intercept"
        ),
        "missingness_indicators": "appended after standardized features; unscaled",
        "fitted_input_sha256": _digest(input_evidence),
        "targets": targets,
        "historical_availability_verified": False,
        "adoption_eligible": False,
    }
    model_state = {
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
    model_state["targets"] = {
        name: {key: target[key] for key in ("transform", "coefficients", "intercept")}
        for name, target in targets.items()
    }
    state_fingerprint = _digest(model_state)
    receipt["model_state_sha256"] = state_fingerprint
    receipt["model_state_sha256_scope"] = (
        "used input evidence, ordered features and targets, fit boundary, alpha, "
        "transforms and coefficients; excludes dropped-row classifications"
    )
    receipt["sha256_scope"] = "complete canonical receipt except its sha256 field"
    fingerprint = _digest(receipt)
    receipt["sha256"] = fingerprint
    return RidgeFit(
        fit_index,
        alpha,
        inputs.feature_names,
        fingerprint,
        state_fingerprint,
        _owned(inputs.dates),
        tuple(models),
        _canonical(receipt),
    )
