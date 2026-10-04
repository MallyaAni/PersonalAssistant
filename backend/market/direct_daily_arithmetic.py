"""One fixed direct arithmetic head on the authenticated bridge's exact support.

Original model/input authentication belongs to the caller. This module refuses
any mismatch in supplied grids or bridge training receipts before fitting.
"""

from __future__ import annotations

import hashlib
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import learned_entry_data
from backend.market import learned_entry_models as base

POLICY = "direct-daily-arithmetic/1-research"
PROTOCOL = "docs/research/direct-daily-arithmetic-plan-2026-10-03.md"
FEATURE_NAMES = learned_entry_data.FEATURE_NAMES[:13]


# Keep trusted in-memory estimators separate from non-executable forecast evidence.
@dataclass(frozen=True)
class DirectForecasts:
    forecasts: np.ndarray
    manifest: dict
    models: dict


# Apply only feature columns selected from the actual mature training rows.
@dataclass(frozen=True)
class ObservedHead:
    estimator: object
    columns: np.ndarray

    # Score raw original features without any scoring-time column selection.
    def predict(self, values):
        return self.estimator.predict(np.asarray(values)[:, self.columns])


# Hash the numeric fitted baseline and trees without serializing executable objects.
def model_identity(head):
    estimator = head.estimator
    identity = {
        "config": dict(base.MODEL_CONFIG["boosting"]),
        "columns": reference._hash(head.columns),
        "baseline": reference._hash(estimator._baseline_prediction),
        "feature_count": int(estimator.n_features_in_),
        "iterations": int(estimator.n_iter_),
        "trees": [
            {
                "nodes": reference._hash(tree.nodes),
                "raw_left_cat_bitsets": reference._hash(tree.raw_left_cat_bitsets),
                "binned_left_cat_bitsets": reference._hash(
                    tree.binned_left_cat_bitsets
                ),
            }
            for stage in estimator._predictors
            for tree in stage
        ],
    }
    identity["sha256"] = base._json_hash(identity)
    return identity


# Validate exact original feature and parent forecast representations before reuse.
def _inputs(prepared, bridge):
    if not isinstance(bridge, reference.BridgeForecasts):
        raise ValueError("Validated BridgeForecasts required")
    dates = np.asarray(prepared["dates"])
    names = tuple(prepared["symbols"])
    x, valid = np.asarray(prepared["X"]), np.asarray(prepared["valid"])
    absolute = np.asarray(prepared["absolute_forecasts"])
    if (
        dates.ndim != 1
        or not len(dates)
        or dates.dtype != np.dtype("datetime64[D]")
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError("Exact chronological datetime64[D] feature dates required")
    shape = (len(dates), len(names))
    if (
        x.shape != (*shape, 13)
        or x.dtype.kind not in "fiu"
        or np.isinf(x).any()
        or tuple(prepared["feature_names"]) != FEATURE_NAMES
    ):
        raise ValueError("Original finite-or-missing thirteen causal features required")
    if valid.shape != shape or valid.dtype.kind != "b":
        raise ValueError("Original aligned boolean prepared.valid required")
    if (
        absolute.shape != shape
        or absolute.dtype.kind not in "fiu"
        or np.isinf(absolute).any()
    ):
        raise ValueError("Original numeric absolute forecasts required")
    manifest = bridge.manifest
    if (
        manifest.get("policy") != reference.POLICY
        or manifest.get("symbols") != list(names)
        or manifest.get("minimum_days") != reference.MIN_DAYS
        or manifest.get("maximum_days") != reference.MAX_DAYS
        or manifest.get("freeze") != str(reference.FREEZE)
        or manifest.get("target") != "adjusted_open[t+2]/adjusted_open[t+1]-1"
        or manifest.get("units") != "one_session_arithmetic_return"
    ):
        raise ValueError("Exact parent bridge schema and symbol identity required")
    for name, value in (
        ("dates", dates),
        ("symbols", np.asarray(names)),
        ("absolute_forecasts", absolute),
    ):
        if manifest["input_sha256"].get(name) != reference._hash(value):
            raise ValueError(f"Parent bridge original {name} bytes mismatch")
    return x, dates, names, absolute, valid


# Check parent output grids and causal support independently of feature validation.
def _validate(prepared, bridge):
    x, dates, names, absolute, valid = _inputs(prepared, bridge)
    shape = (len(dates), len(names))
    manifest = bridge.manifest
    for field, digest in (
        ("calibrated", "calibrated_sha256"),
        ("past_mean", "past_mean_sha256"),
        ("labels", "label_sha256"),
        ("score_mask", "score_mask_sha256"),
        ("label_end_dates", "label_end_dates_sha256"),
    ):
        array = np.asarray(getattr(bridge, field))
        expected = (len(dates),) if field == "label_end_dates" else shape
        if (
            not isinstance(getattr(bridge, field), np.ndarray)
            or array.shape != expected
            or reference._hash(array) != manifest.get(digest)
        ):
            raise ValueError(f"Parent bridge {field} bytes mismatch")
    if (
        bridge.score_mask.dtype.kind != "b"
        or np.any(bridge.score_mask & ~valid)
        or np.any(bridge.score_mask & ~np.isfinite(absolute))
    ):
        raise ValueError(
            "Bridge causal scoring support disagrees with original features"
        )
    benchmark = np.array([name in ("SPY", "QQQ") for name in names])
    if not benchmark.any() or np.any(bridge.score_mask[:, benchmark]):
        raise ValueError("Benchmarks must remain excluded from bridge support")
    endpoints = np.full(len(dates), np.datetime64("NaT", "D"))
    endpoints[:-2] = dates[2:]
    if (
        bridge.label_end_dates.dtype != endpoints.dtype
        or not np.array_equal(bridge.label_end_dates.view("i8"), endpoints.view("i8"))
        or bridge.labels.dtype.kind != "f"
        or np.isinf(bridge.labels).any()
        or np.any(np.isfinite(bridge.labels) & (bridge.labels <= -1))
    ):
        raise ValueError("Exact one-session arithmetic endpoints and labels required")
    months = dates.astype("datetime64[M]")
    if [item.get("month") for item in manifest["months"]] != [
        str(month) for month in np.unique(months)
    ]:
        raise ValueError("Exact original monthly receipt schedule required")
    return x, dates, names, absolute


# Recompute every typed bridge training row identity and refuse unequal support.
def _training(dates, names, absolute, bridge, scored, parent):
    first = int(scored[0])
    cutoff = min(dates[first], reference.FREEZE)
    days = np.arange(max(0, first - reference.MAX_DAYS), first, dtype=np.int64)
    endpoints = bridge.label_end_dates
    days = days[~np.isnat(endpoints[days]) & (endpoints[days] < cutoff)]
    mask = bridge.score_mask & np.isfinite(bridge.labels)
    _, _, _, receipt = reference._rows(
        dates, names, days, mask, absolute, bridge.labels, endpoints
    )
    receipt.update(
        month=str(dates[first].astype("datetime64[M]")),
        fit_date=str(dates[first]),
        fit_index=first,
        label_end_before=str(cutoff),
    )
    for key, value in receipt.items():
        if parent.get(key) != value:
            raise ValueError(f"Direct/bridge training support mismatch: {key}")
    completed = datetime.combine(
        dates[first].astype(object),
        exchange.session_close(dates[first].astype(object)),
        exchange.NEW_YORK,
    )
    expected_status = (
        "fitted"
        if receipt["training_days"] >= reference.MIN_DAYS
        else "insufficient_training_days"
    )
    if completed > reference._as_of(bridge.manifest["data_as_of"]):
        expected_status = "fit_clock_unavailable"
    if parent.get("status") != expected_status:
        raise ValueError(
            "Direct/bridge monthly fit status disagrees with support clock"
        )
    local, stock = np.nonzero(mask[days])
    counts = np.bincount(local, minlength=len(days))
    weights = 1.0 / counts[local]
    return days[local], stock, weights, receipt


# Fit only the declared mature observed columns with equal total weight per date.
def _fit(features, labels, weights):
    columns = np.flatnonzero(np.isfinite(features).any(axis=0)).astype(np.int64)
    if not len(columns):
        return None
    estimator = base._estimator("boosting")
    estimator.fit(features[:, columns], labels, sample_weight=weights)
    return ObservedHead(estimator, columns)


# Preserve invalid predicted returns as unavailable instead of clipping a model.
def predict(head, features, valid):
    features, valid = np.asarray(features), np.asarray(valid)
    if (
        features.ndim != 3
        or features.shape[-1] != 13
        or valid.shape != features.shape[:2]
        or valid.dtype.kind != "b"
        or features.dtype.kind not in "fiu"
        or np.isinf(features).any()
    ):
        raise ValueError(
            "Aligned finite-or-missing direct features and boolean score mask required"
        )
    values = np.full(valid.shape, np.nan, dtype=np.float64)
    receipt = {
        "opportunities": int(valid.sum()),
        "nonfinite": 0,
        "at_or_below_minus_one": 0,
    }
    if head is not None and valid.any():
        raw = np.asarray(head.predict(features[valid]), dtype=np.float64)
        if raw.shape != (int(valid.sum()),):
            raise ValueError("Direct model prediction shape mismatch")
        nonfinite, impossible = ~np.isfinite(raw), np.isfinite(raw) & (raw <= -1)
        receipt["nonfinite"] = int(nonfinite.sum())
        receipt["at_or_below_minus_one"] = int(impossible.sum())
        values[valid] = np.where(nonfinite | impossible, np.nan, raw)
    return values, receipt


# Train the single fixed arithmetic head on exactly the bridge's monthly rows.
def walk_forward(prepared, bridge):
    import scipy
    import sklearn

    x, dates, names, absolute = _validate(prepared, bridge)
    root = Path(__file__).resolve().parents[2]
    identity = {
        "policy": POLICY,
        "config": dict(base.MODEL_CONFIG["boosting"]),
        "target": "adjusted_open[t+2]/adjusted_open[t+1]-1",
        "minimum_days": reference.MIN_DAYS,
        "maximum_days": reference.MAX_DAYS,
        "label_end": 2,
        "holdout_end_before": str(reference.FREEZE),
        "symbols": list(names),
        "dates_sha256": reference._hash(dates),
        "labels_sha256": reference._hash(bridge.labels),
        "label_end_dates_sha256": reference._hash(bridge.label_end_dates),
        "score_mask_sha256": reference._hash(bridge.score_mask),
        "feature_names": list(FEATURE_NAMES),
        "features_sha256": reference._hash(x),
        "valid_sha256": reference._hash(np.asarray(prepared["valid"])),
        "bridge_manifest_sha256": base._json_hash(bridge.manifest),
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "sklearn": sklearn.__version__,
        },
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__).resolve(),
                Path(base.__file__).resolve(),
                Path(reference.__file__).resolve(),
                root / PROTOCOL,
            )
        },
    }
    manifest = {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "months": [],
    }
    forecasts = np.full(bridge.calibrated.shape, np.nan, dtype=np.float64)
    models = {}
    months = dates.astype("datetime64[M]")
    with threadpool_limits(limits=2):
        for parent, month in zip(
            bridge.manifest["months"], np.unique(months), strict=True
        ):
            scored = np.flatnonzero(months == month)
            actual, stocks, weights, receipt = _training(
                dates, names, absolute, bridge, scored, parent
            )
            receipt["status"] = parent["status"]
            head = None
            if parent["status"] == "fitted":
                if receipt["training_days"] < reference.MIN_DAYS:
                    raise ValueError("Fitted bridge lacks mature direct support")
                labels = bridge.labels[actual, stocks]
                past_mean = float(weights @ labels / weights.sum())
                if not np.isclose(
                    past_mean, parent["past_mean"], rtol=1e-12, atol=1e-15
                ):
                    raise ValueError("Direct/bridge past-mean comparator disagrees")
                features = x[actual, stocks]
                receipt["typed_training_features_sha256"] = reference._hash(features)
                head = _fit(features, labels, weights)
                receipt["past_mean"] = past_mean
                if head is None:
                    receipt["status"] = "no_observed_training_features"
                else:
                    receipt["observed_feature_indices"] = head.columns.tolist()
                    receipt["model"] = model_identity(head)
            elif parent["status"] not in (
                "insufficient_training_days",
                "fit_clock_unavailable",
            ):
                raise ValueError("Unknown parent bridge fit status")
            values, diagnostics = predict(head, x[scored], bridge.score_mask[scored])
            forecasts[scored] = values
            receipt["prediction_sha256"] = reference._hash(values)
            receipt["prediction_counts"] = diagnostics
            models[str(month)] = head
            manifest["months"].append(receipt)
    manifest["forecasts_sha256"] = reference._hash(forecasts)
    manifest["score_mask_sha256"] = reference._hash(bridge.score_mask)
    available = np.flatnonzero(np.isfinite(forecasts).any(axis=1))
    manifest["first_score_date"] = str(dates[available[0]]) if len(available) else None
    return DirectForecasts(forecasts, manifest, models)
