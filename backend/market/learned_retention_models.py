"""Causal daily held-B forecasts; no account replay, orders or live adoption.

Monthly heads predict conditional log returns. Their exponentiated means are
plug-in retention inputs, not expected arithmetic wealth. The caller supplies
the audited complete exchange calendar and original input provenance.
"""

from __future__ import annotations

import hashlib
import platform
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import allocation_controls, learned_entry_data
from backend.market import learned_entry_models as base

POLICY = "learned-held-b-forecast/1"
FEATURE_NAMES = learned_entry_data.FEATURE_NAMES[:13]
LABEL_END = 11


# Keep predictions, unavailable evidence and actual fitted monthly heads together.
@dataclass(frozen=True)
class DailyForecasts:
    relative: np.ndarray
    spy: np.ndarray
    manifest: dict
    models: dict


# Preserve original indices when a training-only column has no observations.
@dataclass(frozen=True)
class _ObservedHead:
    estimator: object
    columns: np.ndarray

    # Apply the fitted observation mask without scoring-time feature selection.
    def predict(self, features):
        return self.estimator.predict(np.asarray(features)[:, self.columns])


# Build the original completed-close features without requiring future return labels.
def completed_features(panel, grades, eligible, calendar, provenance):
    dates, prices, names, grades, eligible = learned_entry_data._validate_panel(
        panel, grades, eligible
    )
    calendar = np.asarray(calendar, dtype="datetime64[D]")
    if calendar.ndim != 1 or not np.array_equal(calendar, dates):
        raise ValueError("Complete audited exchange calendar must match daily rows")
    if not isinstance(provenance, dict) or not provenance:
        raise ValueError("Original daily input provenance required")
    for field in ("open", "close", "adj_close"):
        values = np.asarray(getattr(panel, field))
        if (
            values.shape != prices.shape
            or values.dtype.kind not in "fiu"
            or np.isinf(values).any()
            or np.any(np.isfinite(values) & (values <= 0))
        ):
            raise ValueError(
                "Aligned positive-or-missing numeric daily prices required"
            )
    if np.asarray(grades).dtype.kind not in "fiu":
        raise ValueError("Numeric ordinal grades required")
    stock = np.array([name not in ("SPY", "QQQ") for name in names])
    if not stock.any():
        raise ValueError("A declared stock book is required")
    spy = names.index("SPY")
    members = eligible & stock[None, :]
    # One unavailable sentinel lets the shared context include the last close.
    context, available = learned_entry_data._daily_context(
        np.vstack((prices, np.full(len(names), np.nan))),
        np.vstack((grades, np.full(len(names), -1))),
        np.vstack((members, np.zeros(len(names), dtype=bool))),
        spy,
    )
    context, available = context[1:], available[1:]
    return {
        "X": context,
        "valid": available & members & (grades >= 0),
        "available": available,
        "risk_valid": available & stock[None, :],
        "dates": dates,
        "prices": prices,
        "feature_names": list(FEATURE_NAMES),
        "symbols": names,
        "training_symbols": stock,
        "spy_index": spy,
        "provenance": provenance,
    }


# Build completed-close features and separately available next-open return labels.
def prepare(panel, grades, eligible, calendar, provenance):
    completed = completed_features(panel, grades, eligible, calendar, provenance)
    dates, prices, names = completed["dates"], completed["prices"], completed["symbols"]
    spy, stock = completed["spy_index"], completed["training_symbols"]
    opens = allocation_controls.adjusted_open(panel.open, panel.close, prices)
    if opens.shape != prices.shape or np.any(np.isinf(opens)):
        raise ValueError("Finite-or-missing aligned adjusted daily opens required")
    relative = np.full(prices.shape, np.nan)
    market = np.full(len(dates), np.nan)
    endpoints = np.full(len(dates), np.datetime64("NaT", "D"))
    for day in range(max(0, len(dates) - LABEL_END)):
        start, end = opens[day + 1], opens[day + LABEL_END]
        known = np.isfinite(start) & np.isfinite(end) & (start > 0) & (end > 0)
        if known[spy]:
            market[day] = np.log(end[spy] / start[spy])
            relative[day, known] = np.log(end[known] / start[known]) - market[day]
        endpoints[day] = dates[day + LABEL_END]
    return {
        "X": completed["X"],
        "relative_labels": relative,
        "spy_labels": market,
        "valid": completed["valid"],
        "spy_valid": completed["available"][:, spy],
        "dates": dates,
        "label_end_dates": endpoints,
        "feature_names": list(FEATURE_NAMES),
        "symbols": names,
        "training_symbols": stock,
        "spy_index": spy,
        "provenance": provenance,
    }


# Validate dimensions, clock endpoints and membership before fitting any estimator.
def _validate(data):
    x = np.asarray(data["X"])
    dates = np.asarray(data["dates"], dtype="datetime64[D]")
    if (
        x.ndim != 3
        or not len(x)
        or x.shape[-1] != len(FEATURE_NAMES)
        or list(data["feature_names"]) != list(FEATURE_NAMES)
        or len(dates) != len(x)
        or np.any(np.isnat(dates))
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError("Chronological daily13-feature grid required")
    if x.dtype.kind not in "fiu" or np.any(np.isinf(x)):
        raise ValueError("Finite-or-missing numeric causal features required")
    shape = x.shape[:2]
    for name, expected in (("valid", shape), ("spy_valid", (len(x),))):
        if np.shape(data[name]) != expected or np.asarray(data[name]).dtype.kind != "b":
            raise ValueError("Boolean aligned prediction eligibility required")
    for name, expected in (("relative_labels", shape), ("spy_labels", (len(x),))):
        values = np.asarray(data[name])
        if (
            values.shape != expected
            or values.dtype.kind not in "fiu"
            or np.isinf(values).any()
        ):
            raise ValueError("Finite-or-missing aligned numeric labels required")
    names = tuple(data["symbols"])
    stock = np.asarray(data["training_symbols"])
    expected_stock = np.array([name not in ("SPY", "QQQ") for name in names])
    if (
        len(names) != shape[1]
        or len(set(names)) != len(names)
        or "SPY" not in names
        or data["spy_index"] != names.index("SPY")
        or stock.dtype.kind != "b"
        or stock.shape != (shape[1],)
        or not stock.any()
        or not np.array_equal(stock, expected_stock)
        or np.any(np.asarray(data["valid"])[:, ~stock])
    ):
        raise ValueError("Exact stock-only membership and SPY index required")
    endpoints = np.full(len(dates), np.datetime64("NaT", "D"))
    if len(dates) > LABEL_END:
        endpoints[:-LABEL_END] = dates[LABEL_END:]
    supplied = np.asarray(data["label_end_dates"], dtype="datetime64[D]")
    if supplied.shape != endpoints.shape or not np.array_equal(
        supplied.view("i8"), endpoints.view("i8")
    ):
        raise ValueError("Labels must end at the supplied opening t+11")
    return x, dates


# Purge entire decision dates whose label endpoints are not known before the fit.
def training_days(data, fit_index):
    _, dates = _validate(data)
    if isinstance(fit_index, bool) or not isinstance(fit_index, (int, np.integer)):
        raise ValueError("Integer fit index required")
    if not 0 <= fit_index < len(dates):
        raise ValueError("Fit index outside daily calendar")
    cutoff = min(dates[fit_index], base.HOLDOUT_START)
    days = np.arange(max(0, fit_index - base.MAX_TRAIN_DAYS), fit_index)
    endpoints = np.asarray(data["label_end_dates"], dtype="datetime64[D]")[days]
    return days[~np.isnat(endpoints) & (endpoints < cutoff)], cutoff


# Fit one head only after its own distinct mature feature-valid dates reach warmup.
def _fit_head(x, labels, valid, days):
    local, stock = np.nonzero(valid[days] & np.isfinite(labels[days]))
    actual = days[local]
    distinct = np.unique(actual)
    receipt = {
        "training_days": len(distinct),
        "rows": len(actual),
        "row_days_sha256": base._array_hash(actual),
        "row_stocks_sha256": base._array_hash(stock),
        "labels_sha256": base._array_hash(labels[actual, stock]),
        "status": "insufficient_mature_history",
    }
    if len(distinct) < base.MIN_TRAIN_DAYS:
        return None, receipt
    features = x[actual, stock]
    columns = np.flatnonzero(np.isfinite(features).any(axis=0))
    receipt["observed_feature_indices"] = columns.tolist()
    if not len(columns):
        receipt["status"] = "no_observed_training_features"
        return None, receipt
    model = base._estimator("boosting")
    # The pinned sklearn binning fails on an empty all-NaN training column.
    model.fit(features[:, columns], labels[actual, stock])
    receipt["status"] = "fitted"
    return _ObservedHead(model, columns), receipt


# Score causal rows even when their future holding-return labels are unavailable.
def predict(model, features, valid):
    features, valid = np.asarray(features), np.asarray(valid)
    if (
        features.ndim != 3
        or features.shape[-1] != len(FEATURE_NAMES)
        or valid.shape != features.shape[:2]
        or valid.dtype.kind != "b"
        or features.dtype.kind not in "fiu"
        or np.isinf(features).any()
    ):
        raise ValueError("Causal daily features and boolean score eligibility required")
    values = np.full(valid.shape, np.nan)
    if model is not None and valid.any():
        values[valid] = model.predict(features[valid])
        values[~np.isfinite(values)] = np.nan
    return values


# Fit fixed monthly heads and retain hashes and unavailability without economic scoring.
def walk_forward(data):
    import scipy
    import sklearn

    x, dates = _validate(data)
    relative = np.full(x.shape[:2], np.nan)
    spy_values = np.full(len(dates), np.nan)
    identity = {
        "policy": POLICY,
        "config": base.MODEL_CONFIG["boosting"],
        "minimum_days": base.MIN_TRAIN_DAYS,
        "maximum_days": base.MAX_TRAIN_DAYS,
        "label_end": LABEL_END,
        "holdout_end_before": str(base.HOLDOUT_START),
        "features": list(FEATURE_NAMES),
        "symbols": list(data["symbols"]),
        "provenance": data["provenance"],
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "sklearn": sklearn.__version__,
        },
        "source_sha256": {
            str(path.relative_to(Path(__file__).resolve().parents[2])): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in (
                Path(__file__).resolve(),
                Path(base.__file__).resolve(),
                Path(learned_entry_data.__file__).resolve(),
                Path(allocation_controls.__file__).resolve(),
                Path(__file__).resolve().parents[2]
                / "docs/research/learned-retention-plan-2026-10-03.md",
            )
        },
        "arrays": {
            key: base._array_hash(data[key])
            for key in (
                "X",
                "relative_labels",
                "spy_labels",
                "valid",
                "spy_valid",
                "dates",
                "label_end_dates",
                "training_symbols",
            )
        },
    }
    manifest = {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "months": [],
    }
    models = {}
    months = dates.astype("datetime64[M]")
    spy = data["spy_index"]
    with threadpool_limits(limits=2):
        for month in np.unique(months):
            scored = np.flatnonzero(months == month)
            first = int(scored[0])
            days, cutoff = training_days(data, first)
            own, own_receipt = _fit_head(
                x, data["relative_labels"], data["valid"], days
            )
            market, market_receipt = _fit_head(
                x[:, spy : spy + 1],
                np.asarray(data["spy_labels"])[:, None],
                np.asarray(data["spy_valid"])[:, None],
                days,
            )
            relative[scored] = predict(own, x[scored], data["valid"][scored])
            spy_values[scored] = predict(
                market,
                x[scored, spy : spy + 1],
                np.asarray(data["spy_valid"])[scored, None],
            )[:, 0]
            models[str(month)] = (own, market)
            manifest["months"].append(
                {
                    "month": str(month),
                    "fit_date": str(dates[first]),
                    "label_end_before": str(cutoff),
                    "mature_day_indices_sha256": base._array_hash(days),
                    "maximum_label_end": str(data["label_end_dates"][days[-1]])
                    if len(days)
                    else None,
                    "stock": own_receipt,
                    "spy": market_receipt,
                }
            )
    manifest["relative_forecast_sha256"] = base._array_hash(relative)
    manifest["spy_forecast_sha256"] = base._array_hash(spy_values)
    return DailyForecasts(relative, spy_values, manifest, models)
