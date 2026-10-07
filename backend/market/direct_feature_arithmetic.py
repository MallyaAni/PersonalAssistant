"""A fixed daily arithmetic head whose support depends on features, not old models."""

from __future__ import annotations

import hashlib
from copy import deepcopy
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
RISK_POLICY = "holding-price-inference/1-research"
JOINT_PROTOCOL = "docs/research/joint-distribution-allocation-plan-2026-10-04.md"
SAVED_RISK_SOURCE = {
    "backend/market/direct_daily_arithmetic.py": (
        "8c51bd0cf858e0df22f0ff56e4fe0f6f33a93542d94831e8b39fa2984169b690"
    ),
    "backend/market/direct_feature_arithmetic.py": (
        "93b10dd7d9d367361351d8cf59ca2b530bc880f33af718e0300df9eac7edb203"
    ),
    JOINT_PROTOCOL: "db48217d2e44e312cca774b6e7c1fa5c378b48f4e2124c3b15c54aeba5980cc1",
}


# Keep explicit causal opportunity support beside forecasts and numeric model evidence.
@dataclass(frozen=True)
class FeatureForecasts:
    forecasts: np.ndarray
    score_mask: np.ndarray
    manifest: dict
    models: dict
    dates: np.ndarray
    symbols: tuple


# Keep expanded inference distinct from the unchanged parent training artifacts.
@dataclass(frozen=True)
class HoldingRiskForecasts:
    forecasts: np.ndarray
    score_mask: np.ndarray
    manifest: dict
    dates: np.ndarray
    symbols: tuple
    parent: FeatureForecasts
    features: np.ndarray
    valid: np.ndarray
    prices: np.ndarray


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


# Copy original numeric forecasts and lineage without retaining executable heads.
def _copy_feature(result):
    if not isinstance(result, FeatureForecasts):
        raise ValueError("Explicit original FeatureForecasts required")
    return FeatureForecasts(
        result.forecasts.copy(),
        result.score_mask.copy(),
        deepcopy(result.manifest),
        {},
        result.dates.copy(),
        tuple(result.symbols),
    )


# Bind original price features and validity before expanding any inference support.
def _risk_features(parent, bridge, features, valid, prices):
    dates, names, identity = _calibration_inputs(parent, bridge)
    if not _holding_mode(identity):
        raise ValueError("Original held-model training lineage required")
    features, valid, prices = (
        np.asarray(features),
        np.asarray(valid),
        np.asarray(prices),
    )
    if (
        features.shape != (*parent.forecasts.shape, 13)
        or features.dtype.kind not in "fiu"
        or np.isinf(features).any()
        or valid.shape != parent.forecasts.shape
        or valid.dtype != np.dtype("bool")
        or identity["input_sha256"]["features"] != reference._hash(features)
        or identity["input_sha256"]["valid"] != reference._hash(valid)
        or prices.shape != valid.shape
        or prices.dtype != np.dtype("float64")
        or np.isinf(prices).any()
        or np.any(np.isfinite(prices) & (prices <= 0))
    ):
        raise ValueError("Exact original holding feature and valid bytes required")
    as_of = errors._publication(dates, bridge)
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
    benchmark = np.array([name in ("SPY", "QQQ") for name in names])
    mask = (
        _price_risk_support(prices, features, names) & completed[:, None] & ~benchmark
    )
    if np.any(parent.score_mask & ~mask):
        raise ValueError("Original trading support exceeds causal price support")
    return dates, names, mask


# Recover completed-close price availability without a grade or membership mask.
def _price_risk_support(prices, features, names):
    if "SPY" not in names:
        raise ValueError("Original SPY price history required")
    spy = names.index("SPY")
    consecutive = np.zeros(len(names), dtype=np.int64)
    support = np.zeros(prices.shape, dtype=bool)
    observed = np.isfinite(features[:, :, [*range(8), *range(9, 13)]]).any(axis=2)
    observed &= np.isfinite(features[:, :, 12])
    for day in range(len(prices)):
        good = np.isfinite(prices[day]) & (prices[day] > 0)
        consecutive = np.where(good, consecutive + 1, 0)
        support[day] = (consecutive >= 253) & (consecutive[spy] >= 253) & observed[day]
    return support


# Name expanded inference with exact original inputs and new source semantics.
def _risk_identity(parent, prices):
    root = Path(__file__).resolve().parents[2]
    return {
        "policy": RISK_POLICY,
        "parent_manifest_sha256": base._json_hash(parent.manifest),
        "training_policy": HELD_POLICY,
        "target": parent.manifest["identity"]["target"],
        "features_sha256": parent.manifest["identity"]["input_sha256"]["features"],
        "valid_sha256": parent.manifest["identity"]["input_sha256"]["valid"],
        "support": (
            "253_complete_close_and_spy_prefixes_observed_completed_nonbenchmark"
        ),
        "prices_sha256": reference._hash(prices),
        "price_basis": "caller_authenticated_original_adjusted_close",
        "original_prediction_tolerance": {"rtol": 1e-12, "atol": 1e-14},
        "new_fits": 0,
        "grade_or_membership_permission": False,
        "adoption_eligible": False,
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__).resolve(),
                Path(direct.__file__).resolve(),
                root / JOINT_PROTOCOL,
            )
        },
    }


# Reuse only the original month's authenticated numeric head on causal price support.
def holding_risk_forecasts(parent, bridge, features, valid, heads, *, prices):
    dates, names, mask = _risk_features(parent, bridge, features, valid, prices)
    receipts = parent.manifest["months"]
    if not isinstance(heads, dict) or list(heads) != [row["month"] for row in receipts]:
        raise ValueError("Complete original monthly numeric-head schedule required")
    forecasts = np.full(parent.forecasts.shape, np.nan, dtype=np.float64)
    months = dates.astype("datetime64[M]")
    identity = _risk_identity(parent, prices)
    manifest = {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "months": [],
    }
    for row in receipts:
        head = heads[row["month"]]
        if row["status"] == "fitted":
            if (
                not isinstance(head, direct.NumericHead)
                or direct.numeric_identity(head) != row["model"]
            ):
                raise ValueError("Exact original month's numeric head required")
        elif head is not None:
            raise ValueError("Unavailable original month must have no numeric head")
        scored = np.flatnonzero(months == np.datetime64(row["month"], "M"))
        values, counts = direct.predict(
            head, np.asarray(features)[scored], mask[scored]
        )
        original = parent.score_mask[scored]
        if not np.allclose(
            values[original],
            parent.forecasts[scored][original],
            rtol=1e-12,
            atol=1e-14,
            equal_nan=True,
        ):
            raise ValueError("Original supported prediction parity failed")
        values[original] = parent.forecasts[scored][original]
        forecasts[scored] = values
        manifest["months"].append(
            {
                "month": row["month"],
                "parent_receipt_sha256": base._json_hash(row),
                "model_sha256": row.get("model", {}).get("sha256"),
                "status": row["status"],
                "prediction_sha256": reference._hash(values),
                "inference_mask_sha256": reference._hash(mask[scored]),
                "inference_features_sha256": reference._hash(
                    np.asarray(features)[scored]
                ),
                "prediction_counts": counts,
            }
        )
    manifest.update(
        forecasts_sha256=reference._hash(forecasts),
        score_mask_sha256=reference._hash(mask),
    )
    result = HoldingRiskForecasts(
        forecasts,
        mask,
        manifest,
        dates.copy(),
        names,
        _copy_feature(parent),
        np.asarray(features).copy(),
        np.asarray(valid).copy(),
        np.asarray(prices).copy(),
    )
    _risk_lineage(result, bridge)
    return result


# Refuse expanded artifacts that obscure training, input support or monthly scoring.
def _risk_lineage(result, bridge, *, allow_saved_origin=False):
    dates, names, expected_mask = _risk_features(
        result.parent, bridge, result.features, result.valid, result.prices
    )
    expected_identity = _risk_identity(result.parent, result.prices)
    if not isinstance(allow_saved_origin, (bool, np.bool_)):
        raise ValueError("Explicit boolean saved-origin admission required")
    if (
        allow_saved_origin
        and result.manifest["identity"]["source_sha256"] == SAVED_RISK_SOURCE
    ):
        expected_identity["source_sha256"] = dict(SAVED_RISK_SOURCE)
    if (
        result.symbols != names
        or result.dates.dtype != dates.dtype
        or not np.array_equal(result.dates, dates)
        or result.manifest["identity"] != expected_identity
        or result.manifest["identity_sha256"] != base._json_hash(expected_identity)
        or result.score_mask.dtype != np.dtype("bool")
        or not np.array_equal(result.score_mask, expected_mask)
        or result.forecasts.shape != expected_mask.shape
        or result.forecasts.dtype != np.dtype("float64")
        or np.isinf(result.forecasts).any()
        or np.any(
            np.isfinite(result.forecasts) & ((result.forecasts <= -1) | ~expected_mask)
        )
        or result.manifest["forecasts_sha256"] != reference._hash(result.forecasts)
        or result.manifest["score_mask_sha256"] != reference._hash(expected_mask)
        or not np.array_equal(
            result.forecasts[result.parent.score_mask],
            result.parent.forecasts[result.parent.score_mask],
            equal_nan=True,
        )
    ):
        raise ValueError(
            "Expanded holding-risk lineage or original predictions mismatch"
        )
    original = result.parent.manifest["months"]
    receipts = result.manifest["months"]
    if [row["month"] for row in receipts] != [row["month"] for row in original]:
        raise ValueError("Complete original risk-inference monthly schedule required")
    months = dates.astype("datetime64[M]")
    for row, parent in zip(receipts, original, strict=True):
        scored = np.flatnonzero(months == np.datetime64(row["month"], "M"))
        expected = {
            "parent_receipt_sha256": base._json_hash(parent),
            "model_sha256": parent.get("model", {}).get("sha256"),
            "status": parent["status"],
            "prediction_sha256": reference._hash(result.forecasts[scored]),
            "inference_mask_sha256": reference._hash(expected_mask[scored]),
            "inference_features_sha256": reference._hash(result.features[scored]),
        }
        if any(row.get(key) != value for key, value in expected.items()) or (
            parent["status"] != "fitted" and np.isfinite(result.forecasts[scored]).any()
        ):
            raise ValueError("Expanded holding-risk monthly receipt mismatch")
    return dates, names, result.parent.manifest["identity"]


# Return an explicit joint forecast or unavailable evidence for the required book.
@dataclass(frozen=True)
class HoldingScenarios:
    scenarios: np.ndarray | None
    probabilities: np.ndarray | None
    symbols: tuple[str, ...]
    receipt: dict


# Admit frozen OOS holding forecasts once and retain same-date joint error history.
class HoldingScenarioReader:
    # Validate immutable copies without retaining any executable model or caller buffer.
    def __init__(self, result, bridge, *, allow_saved_origin=False):
        if not isinstance(
            result, (FeatureForecasts, HoldingRiskForecasts)
        ) or not isinstance(bridge, reference.BridgeForecasts):
            raise ValueError("Explicit holding forecast and bridge artifacts required")
        bridge = reference.BridgeForecasts(
            bridge.calibrated.copy(),
            bridge.past_mean.copy(),
            bridge.labels.copy(),
            bridge.label_end_dates.copy(),
            bridge.score_mask.copy(),
            deepcopy(bridge.manifest),
        )
        if isinstance(result, HoldingRiskForecasts):
            result = HoldingRiskForecasts(
                result.forecasts.copy(),
                result.score_mask.copy(),
                deepcopy(result.manifest),
                result.dates.copy(),
                tuple(result.symbols),
                _copy_feature(result.parent),
                result.features.copy(),
                result.valid.copy(),
                result.prices.copy(),
            )
            dates, names, identity = _risk_lineage(
                result, bridge, allow_saved_origin=allow_saved_origin
            )
        else:
            result = _copy_feature(result)
            dates, names, identity = _calibration_inputs(result, bridge)
        if not _holding_mode(identity):
            raise ValueError("Holding-capable B/A/A+ forecast lineage required")
        if (
            dates.ndim != 1
            or dates.dtype != np.dtype("datetime64[D]")
            or not len(dates)
            or np.isnat(dates).any()
            or np.any(dates[1:] <= dates[:-1])
            or not names
            or len(names) != len(set(names))
        ):
            raise ValueError("Unique complete chronological holding grid required")
        years, calendar = exchange.reviewed_sessions()
        whole = np.arange(dates[0], dates[-1] + np.timedelta64(1, "D"))
        if any(
            day.astype(object).year not in years for day in whole
        ) or not np.array_equal(dates, whole[np.is_busday(whole, busdaycal=calendar)]):
            raise ValueError("Actual complete exchange holding sessions required")
        endpoints = np.full(len(dates), np.datetime64("NaT", "D"))
        endpoints[:-2] = dates[2:]
        if (
            bridge.labels.shape != result.forecasts.shape
            or bridge.labels.dtype != np.dtype("float64")
            or np.isinf(bridge.labels).any()
            or np.any(bridge.labels[np.isfinite(bridge.labels)] < -1)
            or bridge.label_end_dates.dtype != endpoints.dtype
            or not np.array_equal(
                bridge.label_end_dates.view("i8"), endpoints.view("i8")
            )
        ):
            raise ValueError(
                "Aligned possible holding outcomes and exact D+2 endpoints required"
            )
        self.as_of = errors._publication(dates, bridge)
        self.dates, self.symbols = dates, names
        self.forecasts, self.labels = result.forecasts, bridge.labels
        self.endpoints, self.support = bridge.label_end_dates, result.score_mask
        for array in (
            self.dates,
            self.forecasts,
            self.labels,
            self.endpoints,
            self.support,
        ):
            array.setflags(write=False)
        self.months = dates.astype("datetime64[M]")
        self.months.setflags(write=False)
        self._cache = {}
        root = Path(__file__).resolve().parents[2]
        protocol = (
            root / "docs/research/joint-distribution-allocation-plan-2026-10-04.md"
        )
        self.identity = {
            "policy": "joint-holding-scenarios/1-research",
            "horizon": "next_open_to_following_open_arithmetic_return",
            "return_basis": "saved_adjusted_open_ratio_not_exact_broker_wealth",
            "feature_manifest_sha256": base._json_hash(result.manifest),
            "bridge_manifest_sha256": base._json_hash(bridge.manifest),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
            "minimum_joint_days": 252,
            "maximum_days": reference.MAX_DAYS,
            "freeze": str(reference.FREEZE),
            "confidence_guarantee": False,
            "adoption_eligible": False,
        }
        if isinstance(result, HoldingRiskForecasts):
            self.identity["risk_inference_policy"] = RISK_POLICY
            self.identity["original_feature_manifest_sha256"] = base._json_hash(
                result.parent.manifest
            )
            self.identity["original_risk_source_sha256"] = deepcopy(
                result.manifest["identity"]["source_sha256"]
            )
            self.identity["consumer_risk_source_sha256"] = _risk_identity(
                result.parent, result.prices
            )["source_sha256"]

    # Cache strictly mature common OOS dates for the month and required stock order.
    def _bank(self, day, indices):
        first = int(np.flatnonzero(self.months == self.months[day])[0])
        key = (first, *indices)
        if key in self._cache:
            return self._cache[key]
        cutoff = min(self.dates[first], reference.FREEZE)
        candidates = np.arange(
            max(0, first - reference.MAX_DAYS), first, dtype=np.int64
        )
        matured = candidates[
            ~np.isnat(self.endpoints[candidates])
            & (self.endpoints[candidates] < cutoff)
        ]
        mask = (
            self.support[np.ix_(matured, indices)]
            & np.isfinite(self.forecasts[np.ix_(matured, indices)])
            & np.isfinite(self.labels[np.ix_(matured, indices)])
        )
        chosen = matured[mask.all(axis=1)]
        past, outcomes = (
            self.forecasts[np.ix_(chosen, indices)],
            self.labels[np.ix_(chosen, indices)],
        )
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            gross = (1 + outcomes) / (1 + past)
        receipt = {
            "fit_date": str(self.dates[first]),
            "label_end_before": str(cutoff),
            "candidate_dates": len(candidates),
            "mature_dates": len(matured),
            "joint_dates": len(chosen),
            "unavailable_joint_dates": len(matured) - len(chosen),
            "per_stock_available_dates": mask.sum(axis=0).tolist(),
            "decision_indices": chosen.tolist(),
            "maximum_endpoint": str(self.endpoints[chosen].max())
            if len(chosen)
            else None,
            "row_sha256": {
                "decision_indices": reference._hash(chosen),
                "forecasts": reference._hash(past),
                "labels": reference._hash(outcomes),
                "gross_errors": reference._hash(gross),
                "endpoints": reference._hash(self.endpoints[chosen]),
            },
        }
        gross.setflags(write=False)
        self._cache[key] = gross, receipt
        return gross, receipt

    # Form current simultaneous scenarios without consulting current or future outcomes.
    def distribution(self, day, symbols):
        if (
            isinstance(day, (bool, np.bool_))
            or not isinstance(day, (int, np.integer))
            or not 0 <= day < len(self.dates)
            or not isinstance(symbols, (list, tuple))
            or not symbols
            or any(not isinstance(s, str) or not s for s in symbols)
            or len(symbols) != len(set(symbols))
        ):
            raise ValueError(
                "Explicit current index and unique required stock identities required"
            )
        close = datetime.combine(
            self.dates[day].astype(object),
            exchange.session_close(self.dates[day].astype(object)),
            exchange.NEW_YORK,
        )
        if close > self.as_of:
            raise ValueError("Current completed holding forecast is not yet published")
        names = tuple(symbols)
        receipt = {
            **deepcopy(self.identity),
            "decision_date": str(self.dates[day]),
            "symbols": list(names),
            "status": "unavailable",
        }
        if any(name not in self.symbols for name in names):
            receipt["reason"] = "uncovered_required_stock"
            return HoldingScenarios(None, None, names, receipt)
        indices = tuple(self.symbols.index(name) for name in names)
        gross, bank = self._bank(int(day), indices)
        receipt.update(deepcopy(bank))
        current = self.forecasts[day, list(indices)]
        if not np.isfinite(current).all() or not self.support[day, list(indices)].all():
            receipt["reason"] = "missing_current_forecast"
        elif len(gross) < 252:
            receipt["reason"] = "insufficient_joint_history"
        else:
            with np.errstate(over="ignore", invalid="ignore"):
                scenarios = (1 + current) * gross - 1
            if not np.isfinite(scenarios).all() or np.any(scenarios < -1):
                receipt["reason"] = "unsupported_scenario_arithmetic"
            else:
                probabilities = np.full(len(scenarios), 1 / len(scenarios))
                scenarios.setflags(write=False)
                probabilities.setflags(write=False)
                receipt.update(
                    status="available",
                    scenarios_sha256=reference._hash(scenarios),
                    probabilities_sha256=reference._hash(probabilities),
                )
                return HoldingScenarios(scenarios, probabilities, names, receipt)
        return HoldingScenarios(None, None, names, receipt)
