"""Causal affine bridge from supplied OOS log forecasts to daily arithmetic returns.

This module trusts no model artifact or price loader. The caller authenticates
original forecast/source bytes; this bridge records their supplied identities.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import numpy as np

from backend.market import calendar as exchange

POLICY = "daily-arithmetic-bridge/1-research"
MIN_DAYS = 504
MAX_DAYS = 756
FREEZE = np.datetime64("2026-08-17", "D")
PROTOCOL = "docs/research/daily-arithmetic-bridge-plan-2026-10-03.md"


# Return aligned forecasts and labels while retaining missing opportunities.
@dataclass(frozen=True)
class BridgeForecasts:
    calibrated: np.ndarray
    past_mean: np.ndarray
    labels: np.ndarray
    label_end_dates: np.ndarray
    score_mask: np.ndarray
    manifest: dict


# Preserve typed array bytes, dimensions and representation in artifact identities.
def _hash(array):
    value = np.ascontiguousarray(array)
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode())
    digest.update(json.dumps(value.shape).encode())
    digest.update(value.tobytes())
    return digest.hexdigest()


# Refuse ambiguous publication clocks rather than assigning a timezone by assumption.
def _as_of(value):
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    if (
        not isinstance(instant, datetime)
        or instant.tzinfo is None
        or instant.utcoffset() is None
    ):
        raise ValueError("Timezone-aware data_as_of required")
    return instant.astimezone(exchange.NEW_YORK)


# Validate original supplied daily grids without filling or compacting missing rows.
def _validate(dates, symbols, adjusted_opens, grades, eligible, forecasts, calendar):
    dates, calendar = np.asarray(dates), np.asarray(calendar)
    names = tuple(symbols)
    if (
        dates.ndim != 1
        or dates.dtype != np.dtype("datetime64[D]")
        or not len(dates)
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
        or calendar.dtype != dates.dtype
        or not np.array_equal(dates, calendar)
    ):
        raise ValueError("Complete aligned chronological daily calendar required")
    if (
        not names
        or any(not isinstance(name, str) or not name for name in names)
        or len(set(names)) != len(names)
        or "SPY" not in names
        or "QQQ" not in names
    ):
        raise ValueError("Unique symbols including SPY and QQQ required")
    shape = (len(dates), len(names))
    arrays = []
    for value, name in (
        (adjusted_opens, "adjusted_opens"),
        (grades, "grades"),
        (forecasts, "absolute_forecasts"),
    ):
        array = np.asarray(value)
        if (
            array.shape != shape
            or array.dtype.kind not in "iuf"
            or np.isinf(array).any()
        ):
            raise ValueError(f"Aligned numeric finite-or-missing {name} required")
        arrays.append(array.astype(np.float64, copy=True))
    opens, grades, forecasts = arrays
    if np.any(np.isfinite(opens) & (opens <= 0)):
        raise ValueError("Adjusted opens must be positive or missing")
    if np.any(~np.isin(grades, (-1, 0, 1, 2, 3))):
        raise ValueError("Ordinal grades -1 through 3 required")
    eligible = np.asarray(eligible)
    if eligible.shape != shape or eligible.dtype.kind != "b":
        raise ValueError("Explicit aligned boolean eligibility required")
    return dates.copy(), names, opens, grades, eligible.copy(), forecasts


# Construct exact open-to-next-open outcomes separately from causal score eligibility.
def _targets(dates, opens, as_of):
    labels = np.full(opens.shape, np.nan, dtype=np.float64)
    endpoints = np.full(len(dates), np.datetime64("NaT", "D"))
    if len(dates) > 2:
        endpoints[:-2] = dates[2:]
        known_end = np.array(
            [
                datetime.combine(day.astype(object), time(9, 30), exchange.NEW_YORK)
                <= as_of
                for day in dates[2:]
            ]
        )
        start, end = opens[1:-1], opens[2:]
        valid = np.isfinite(start) & np.isfinite(end) & known_end[:, None]
        with np.errstate(over="ignore", invalid="ignore"):
            returns = end / start - 1
        valid &= np.isfinite(returns)
        labels[:-2] = np.where(valid, returns, np.nan)
    return labels, endpoints


# Fit a single bounded affine map with total training weight one per whole date.
def fit_affine(x, y, weights):
    x, y, weights = [np.asarray(value, dtype=np.float64) for value in (x, y, weights)]
    if (
        x.ndim != 1
        or not len(x)
        or y.shape != x.shape
        or weights.shape != x.shape
        or not all(np.isfinite(value).all() for value in (x, y, weights))
        or np.any(weights <= 0)
    ):
        raise ValueError(
            "Finite aligned affine training rows and positive weights required"
        )
    total = float(weights.sum())
    mean_x, mean_y = float(weights @ x / total), float(weights @ y / total)
    centered_x, centered_y = x - mean_x, y - mean_y
    variance = (
        0.0 if np.all(x == x[0]) else float(weights @ (centered_x * centered_x) / total)
    )
    covariance = float(weights @ (centered_x * centered_y) / total)
    beta = 0.0 if variance == 0 else float(np.clip(covariance / variance, 0, 1))
    alpha = mean_y - beta * mean_x
    if not np.isfinite(
        [total, mean_x, mean_y, variance, covariance, beta, alpha]
    ).all():
        raise ValueError("Affine training arithmetic exceeds finite numerical range")
    return {
        "alpha": alpha,
        "beta": beta,
        "past_mean": mean_y,
        "mean_x": mean_x,
        "predictor_variance": variance,
        "predictor_target_covariance": covariance,
        "total_weight": total,
    }


# Record exact training selection and numeric bytes before reporting any coefficient.
def _rows(dates, names, days, mask, forecasts, labels, endpoints):
    local, stock = np.nonzero(mask[days])
    selected_days = days[local]
    counts = np.bincount(local, minlength=len(days))
    weights = 1.0 / counts[local]
    used_days = days[counts > 0]
    x, y = forecasts[selected_days, stock], labels[selected_days, stock]
    hashes = {
        "decision_indices": _hash(selected_days.astype(np.int64)),
        "symbol_indices": _hash(stock.astype(np.int64)),
        "names": _hash(np.asarray(names)[stock]),
        "forecasts": _hash(x),
        "labels": _hash(y),
        "weights": _hash(weights),
        "endpoints": _hash(endpoints[selected_days]),
    }
    receipt = {
        "training_days": len(used_days),
        "training_rows": len(x),
        "training_dates": dates[used_days].astype(str).tolist(),
        "rows_per_date": counts[counts > 0].tolist(),
        "row_hashes": hashes,
        "maximum_label_end": str(endpoints[used_days[-1]]) if len(used_days) else None,
    }
    return x, y, weights, receipt


# Apply monthly past-only affine fits to every known causal opportunity.
def walk_forward(
    dates,
    symbols,
    adjusted_opens,
    grades,
    eligible,
    absolute_forecasts,
    calendar,
    *,
    data_as_of,
):
    original_hashes = {
        "dates": _hash(np.asarray(dates)),
        "symbols": _hash(np.asarray(symbols)),
        "adjusted_opens": _hash(np.asarray(adjusted_opens)),
        "grades": _hash(np.asarray(grades)),
        "eligible": _hash(np.asarray(eligible)),
        "absolute_forecasts": _hash(np.asarray(absolute_forecasts)),
        "calendar": _hash(np.asarray(calendar)),
    }
    dates, names, opens, grades, eligible, forecasts = _validate(
        dates,
        symbols,
        adjusted_opens,
        grades,
        eligible,
        absolute_forecasts,
        calendar,
    )
    as_of = _as_of(data_as_of)
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
    stock = np.array([name not in ("SPY", "QQQ") for name in names])
    score_mask = (
        eligible
        & (grades >= 2)
        & stock[None, :]
        & np.isfinite(forecasts)
        & completed[:, None]
    )
    labels, endpoints = _targets(dates, opens, as_of)
    train_mask = score_mask & np.isfinite(labels)
    calibrated = np.full(opens.shape, np.nan, dtype=np.float64)
    past_mean = calibrated.copy()
    root = Path(__file__).resolve().parents[2]
    source = {
        "backend/market/daily_arithmetic_bridge.py": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        PROTOCOL: hashlib.sha256((root / PROTOCOL).read_bytes()).hexdigest(),
    }
    manifest = {
        "policy": POLICY,
        "minimum_days": MIN_DAYS,
        "maximum_days": MAX_DAYS,
        "freeze": str(FREEZE),
        "target": "adjusted_open[t+2]/adjusted_open[t+1]-1",
        "units": "one_session_arithmetic_return",
        "symbols": list(names),
        "data_as_of": as_of.isoformat(),
        "runtime": {"numpy": np.__version__},
        "source_sha256": source,
        "calculation_precision": "float64",
        "input_sha256": original_hashes,
        "label_sha256": _hash(labels),
        "label_end_dates_sha256": _hash(endpoints),
        "score_mask_sha256": _hash(score_mask),
        "months": [],
    }
    months = dates.astype("datetime64[M]")
    for month in np.unique(months):
        scored = np.flatnonzero(months == month)
        first = int(scored[0])
        cutoff = min(dates[first], FREEZE)
        days = np.arange(max(0, first - MAX_DAYS), first, dtype=np.int64)
        days = days[~np.isnat(endpoints[days]) & (endpoints[days] < cutoff)]
        x, y, weights, receipt = _rows(
            dates, names, days, train_mask, forecasts, labels, endpoints
        )
        receipt.update(
            month=str(month),
            fit_date=str(dates[first]),
            fit_index=first,
            label_end_before=str(cutoff),
            status="insufficient_training_days",
        )
        if receipt["training_days"] >= MIN_DAYS and completed[first]:
            receipt.update(fit_affine(x, y, weights))
            receipt["status"] = "fitted"
            allowed = score_mask[scored]
            values = receipt["alpha"] + receipt["beta"] * forecasts[scored]
            calibrated[scored] = np.where(allowed, values, np.nan)
            past_mean[scored] = np.where(allowed, receipt["past_mean"], np.nan)
        elif not completed[first]:
            receipt["status"] = "fit_clock_unavailable"
        manifest["months"].append(receipt)
    finite = np.flatnonzero(np.any(np.isfinite(calibrated), axis=1))
    manifest["first_score_date"] = str(dates[finite[0]]) if len(finite) else None
    manifest["pre_start_sessions"] = int(finite[0]) if len(finite) else len(dates)
    manifest["calibrated_sha256"] = _hash(calibrated)
    manifest["past_mean_sha256"] = _hash(past_mean)
    return BridgeForecasts(
        calibrated, past_mean, labels, endpoints, score_mask, manifest
    )
