"""A fixed daily arithmetic head whose support depends on features, not old models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_daily_arithmetic as direct
from backend.market import direct_error_band as errors
from backend.market import learned_entry_models as base

POLICY = "direct-feature-arithmetic/1-research"
PROTOCOL = "docs/research/direct-feature-support-plan-2026-10-03.md"
HELD_POLICY = "learned-held-exits/1-research"
HELD_BAND_POLICY = "learned-held-exits-band/1-research"
HELD_PROTOCOL = "docs/research/learned-held-exits-plan-2026-10-03.md"


# Keep explicit causal opportunity support beside forecasts and numeric model evidence.
@dataclass(frozen=True)
class FeatureForecasts:
    forecasts: np.ndarray
    score_mask: np.ndarray
    manifest: dict
    models: dict
    dates: np.ndarray
    symbols: tuple


# Derive causal forecasting support, optionally including B holding evidence.
def support(prepared, bridge, grades, eligible, *, hold_b=False):
    if not isinstance(hold_b, (bool, np.bool_)):
        raise ValueError("Explicit boolean held-B support option required")
    x, dates, names, _ = direct._validate(prepared, bridge)
    grades, eligible = np.asarray(grades), np.asarray(eligible)
    shape = (len(dates), len(names))
    if (
        grades.shape != shape
        or grades.dtype.kind not in "iuf"
        or not np.isin(grades, (-1, 0, 1, 2, 3)).all()
        or eligible.shape != shape
        or eligible.dtype.kind != "b"
    ):
        raise ValueError(
            "Aligned ordinal grades and explicit boolean eligibility required"
        )
    as_of = reference._as_of(bridge.manifest["data_as_of"])
    completed = np.array(
        [
            datetime.combine(
                day.astype(object),
                exchange.session_close(day.astype(object)),
                exchange.NEW_YORK,
            )
            <= as_of
            for day in dates
        ]
    )
    # Outcome knowledge is checked independently and never becomes scoring support.
    known = np.isfinite(bridge.labels).any(axis=1)
    for day in np.flatnonzero(known):
        endpoint = bridge.label_end_dates[day]
        if (
            np.isnat(endpoint)
            or datetime.combine(
                endpoint.astype(object),
                exchange.session_close(endpoint.astype(object)),
                exchange.NEW_YORK,
            )
            > as_of
        ):
            raise ValueError("Finite label endpoint is not yet known")
    stock = np.array([name not in ("SPY", "QQQ") for name in names])
    mask = (
        prepared["valid"]
        & eligible
        & (grades >= (1 if hold_b else 2))
        & stock[None, :]
        & completed[:, None]
    )
    return x, dates, names, mask, completed


# Select exactly mature dated feature rows with equal total weight per session.
def training(dates, names, features, labels, endpoints, mask, first):
    cutoff = min(dates[first], reference.FREEZE)
    days = np.arange(max(0, first - reference.MAX_DAYS), first, dtype=np.int64)
    days = days[~np.isnat(endpoints[days]) & (endpoints[days] < cutoff)]
    local, stock = np.nonzero(mask[days] & np.isfinite(labels[days]))
    actual = days[local]
    counts = np.bincount(local, minlength=len(days))
    weights = 1.0 / counts[local]
    used = days[counts > 0]
    receipt = {
        "month": str(dates[first].astype("datetime64[M]")),
        "fit_date": str(dates[first]),
        "fit_index": first,
        "label_end_before": str(cutoff),
        "training_days": len(used),
        "training_rows": len(actual),
        "training_dates": dates[used].astype(str).tolist(),
        "rows_per_date": counts[counts > 0].tolist(),
        "maximum_label_end": str(endpoints[actual].max()) if len(actual) else None,
        "row_hashes": {
            name: reference._hash(value)
            for name, value in (
                ("decision_indices", actual),
                ("symbol_indices", stock.astype(np.int64)),
                ("names", np.asarray(names)[stock]),
                ("labels", labels[actual, stock]),
                ("weights", weights),
                ("endpoints", endpoints[actual]),
            )
        },
    }
    if features is not None:
        receipt["row_hashes"]["features"] = reference._hash(features[actual, stock])
    return actual, stock, weights, receipt


# Fit the registered daily head with explicit default or held-B forecast lineage.
def walk_forward(prepared, bridge, grades, eligible, *, hold_b=False):
    x, dates, names, mask, completed = support(
        prepared, bridge, grades, eligible, hold_b=hold_b
    )
    root = Path(__file__).resolve().parents[2]
    identity = {
        "policy": HELD_POLICY if hold_b else POLICY,
        "target": "adjusted_open[t+2]/adjusted_open[t+1]-1",
        "config": dict(base.MODEL_CONFIG["boosting"]),
        "minimum_days": reference.MIN_DAYS,
        "maximum_days": reference.MAX_DAYS,
        "label_end": 2,
        "holdout_end_before": str(reference.FREEZE),
        "symbols": list(names),
        "feature_names": list(direct.FEATURE_NAMES),
        "data_as_of": bridge.manifest["data_as_of"],
        "bridge_manifest_sha256": base._json_hash(bridge.manifest),
        "input_sha256": {
            name: reference._hash(np.asarray(value))
            for name, value in (
                ("dates", dates),
                ("features", x),
                ("valid", prepared["valid"]),
                ("grades", grades),
                ("eligible", eligible),
                ("score_mask", mask),
                ("labels", bridge.labels),
                ("label_end_dates", bridge.label_end_dates),
            )
        },
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__).resolve(),
                Path(direct.__file__).resolve(),
                Path(base.__file__).resolve(),
                Path(reference.__file__).resolve(),
                Path(exchange.__file__).resolve(),
                root / (HELD_PROTOCOL if hold_b else PROTOCOL),
            )
        },
    }
    if hold_b:
        identity.update(hold_b=True, support_min_grade=1)
    manifest = {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "months": [],
    }
    forecasts, models = np.full(mask.shape, np.nan, dtype=np.float64), {}
    months = dates.astype("datetime64[M]")
    with threadpool_limits(limits=2):
        for month in np.unique(months):
            scored = np.flatnonzero(months == month)
            actual, stocks, weights, receipt = training(
                dates,
                names,
                x,
                bridge.labels,
                bridge.label_end_dates,
                mask,
                int(scored[0]),
            )
            receipt["status"] = "insufficient_training_days"
            head = None
            if not completed[scored[0]]:
                receipt["status"] = "fit_clock_unavailable"
            elif receipt["training_days"] >= reference.MIN_DAYS:
                head = direct._fit(
                    x[actual, stocks], bridge.labels[actual, stocks], weights
                )
                receipt["status"] = (
                    "fitted" if head is not None else "no_observed_training_features"
                )
                if head is not None:
                    receipt["observed_feature_indices"] = head.columns.tolist()
                    receipt["model"] = direct.model_identity(head)
            values, diagnostics = direct.predict(head, x[scored], mask[scored])
            forecasts[scored] = values
            receipt.update(
                prediction_sha256=reference._hash(values), prediction_counts=diagnostics
            )
            models[str(month)] = head
            manifest["months"].append(receipt)
    manifest.update(
        forecasts_sha256=reference._hash(forecasts),
        score_mask_sha256=reference._hash(mask),
    )
    finite = np.flatnonzero(np.isfinite(forecasts).any(axis=1))
    manifest["first_score_date"] = str(dates[finite[0]]) if len(finite) else None
    manifest["support_counts"] = {
        "feature_opportunities": int(mask.sum()),
        "original_bridge_opportunities": int(bridge.score_mask.sum()),
        "added_opportunities": int((mask & ~bridge.score_mask).sum()),
    }
    return FeatureForecasts(forecasts, mask, manifest, models, dates.copy(), names)


# Check the new forecast representation without pretending it is an old policy.
def _calibration_inputs(result, bridge):
    if not isinstance(result, FeatureForecasts):
        raise ValueError("Explicit FeatureForecasts required")
    identity = result.manifest["identity"]
    if result.manifest["identity_sha256"] != base._json_hash(identity):
        raise ValueError("New feature-policy identity required")
    _registered_identity(identity)
    if identity["bridge_manifest_sha256"] != base._json_hash(bridge.manifest):
        raise ValueError("Original label lineage mismatch")
    return _calibration_grids(result, bridge, identity)


# Recover only a registered mode whose explicit option and protocol agree.
def _holding_mode(identity):
    source = identity.get("source_sha256", {})
    if identity.get("policy") == HELD_POLICY:
        protocol_sha = hashlib.sha256(
            (Path(__file__).resolve().parents[2] / HELD_PROTOCOL).read_bytes()
        ).hexdigest()
        if (
            identity.get("hold_b") is not True
            or type(identity.get("support_min_grade")) is not int
            or identity.get("support_min_grade") != 1
            or source.get(HELD_PROTOCOL) != protocol_sha
            or PROTOCOL in source
        ):
            raise ValueError("Held-B forecast mode identity mismatch")
        return True
    if identity.get("policy") != POLICY or (
        "hold_b" in identity
        or "support_min_grade" in identity
        or HELD_PROTOCOL in source
    ):
        raise ValueError("Default feature forecast mode identity mismatch")
    return False


# Refuse changes to the fixed model or its receipt-authenticated support mode.
def _registered_identity(identity):
    _holding_mode(identity)
    expected = {
        "config": dict(base.MODEL_CONFIG["boosting"]),
        "minimum_days": reference.MIN_DAYS,
        "maximum_days": reference.MAX_DAYS,
        "label_end": 2,
        "holdout_end_before": str(reference.FREEZE),
        "target": "adjusted_open[t+2]/adjusted_open[t+1]-1",
        "feature_names": list(direct.FEATURE_NAMES),
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        raise ValueError("Registered feature-policy training identity mismatch")


# Bind exact calendar, symbol, outcome and prediction grids before using errors.
def _calibration_grids(result, bridge, identity):
    dates, names = result.dates, result.symbols
    if (
        identity["symbols"] != list(names)
        or identity["input_sha256"]["dates"] != reference._hash(dates)
        or bridge.manifest["input_sha256"]["dates"] != reference._hash(dates)
        or bridge.manifest["symbols"] != list(names)
    ):
        raise ValueError("Feature calendar/symbol identity mismatch")
    if (
        result.forecasts.shape != (len(dates), len(names))
        or result.forecasts.shape != result.score_mask.shape
        or result.forecasts.dtype != np.dtype("float64")
        or result.score_mask.dtype.kind != "b"
        or np.isinf(result.forecasts).any()
        or np.any(
            np.isfinite(result.forecasts)
            & ((result.forecasts <= -1) | ~result.score_mask)
        )
    ):
        raise ValueError("Feature forecasts disagree with causal support")
    for key, value in (
        ("score_mask", result.score_mask),
        ("labels", bridge.labels),
        ("label_end_dates", bridge.label_end_dates),
    ):
        if identity["input_sha256"].get(key) != reference._hash(value):
            raise ValueError("Feature calibration bytes mismatch: " + key)
    if result.manifest["forecasts_sha256"] != reference._hash(result.forecasts):
        raise ValueError("Feature prediction bytes mismatch")
    if identity["data_as_of"] != bridge.manifest["data_as_of"]:
        raise ValueError("Feature publication clock mismatch")
    _monthly_predictions(result, bridge)
    return dates, names, identity


# Refuse retrospective monthly clocks or finite scores from an unavailable model.
def _monthly_predictions(result, bridge):
    dates = result.dates
    months = dates.astype("datetime64[M]")
    if [row["month"] for row in result.manifest["months"]] != [
        str(month) for month in np.unique(months)
    ]:
        raise ValueError("Complete monthly feature-model schedule required")
    for row, month in zip(result.manifest["months"], np.unique(months), strict=True):
        scored = np.flatnonzero(months == month)
        if (
            row["fit_index"] != int(scored[0])
            or row["fit_date"] != str(dates[scored[0]])
            or row["label_end_before"] != str(min(dates[scored[0]], reference.FREEZE))
            or row["prediction_sha256"] != reference._hash(result.forecasts[scored])
            or (
                row["status"] != "fitted"
                and np.isfinite(result.forecasts[scored]).any()
            )
        ):
            raise ValueError("Feature monthly prediction or fit clock mismatch")
        _mature_receipt(result, bridge, row, int(scored[0]))


# Reconstruct admitted dated rows so fabricated warmup scores cannot become errors.
def _mature_receipt(result, bridge, row, first):
    _, _, _, expected = training(
        result.dates,
        result.symbols,
        None,
        bridge.labels,
        bridge.label_end_dates,
        result.score_mask,
        first,
    )
    for name, value in expected.items():
        actual = row.get(name)
        if name == "row_hashes":
            actual = {key: row.get(name, {}).get(key) for key in value}
        if actual != value:
            raise ValueError("Feature mature training receipt mismatch: " + name)
    as_of = reference._as_of(result.manifest["identity"]["data_as_of"])
    completed = (
        datetime.combine(
            result.dates[first].astype(object),
            exchange.session_close(result.dates[first].astype(object)),
            exchange.NEW_YORK,
        )
        <= as_of
    )
    status = (
        "fit_clock_unavailable"
        if not completed
        else "insufficient_training_days"
        if expected["training_days"] < reference.MIN_DAYS
        else None
    )
    if (status is not None and row["status"] != status) or (
        status is None
        and row["status"] not in ("fitted", "no_observed_training_features")
    ):
        raise ValueError(
            "Feature fitted status disagrees with mature training availability"
        )


# Authenticate new support lineage before reusing the unchanged residual formula.
def calibrate(result, bridge):
    dates, names, identity = _calibration_inputs(result, bridge)
    hold_b = _holding_mode(identity)
    root = Path(__file__).resolve().parents[2]
    band_identity = {
        "policy": HELD_BAND_POLICY
        if hold_b
        else "direct-feature-error-band/1-research",
        "maximum_days": reference.MAX_DAYS,
        "freeze": str(reference.FREEZE),
        "minimum_observations": 2,
        "minimum_clusters": 2,
        "multiplier": 1,
        "units": "one_session_arithmetic_return",
        "clustering": "forecast_calendar_month",
        "feature_manifest_sha256": base._json_hash(result.manifest),
        "bridge_manifest_sha256": base._json_hash(bridge.manifest),
        "input_sha256": {
            name: reference._hash(value)
            for name, value in (
                ("dates", dates),
                ("symbols", np.asarray(names)),
                ("forecasts", result.forecasts),
                ("labels", bridge.labels),
                ("label_end_dates", bridge.label_end_dates),
                ("score_mask", result.score_mask),
            )
        },
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__).resolve(),
                Path(errors.__file__).resolve(),
                Path(reference.__file__).resolve(),
                Path(exchange.__file__).resolve(),
                root / (HELD_PROTOCOL if hold_b else PROTOCOL),
            )
        },
        "calculation_precision": "float64",
        "runtime": {"numpy": np.__version__},
    }
    if hold_b:
        band_identity.update(hold_b=True, support_min_grade=1)
    return errors.freeze_rows(
        dates,
        names,
        result.forecasts,
        bridge.labels,
        bridge.label_end_dates,
        result.score_mask,
        reference._as_of(identity["data_as_of"]),
        band_identity,
    )
