"""Whole-session crossfitted nonlinear policy iteration, still research-only.

Outer monthly maturity is enforced here rather than delegated to a caller.
Training suffixes follow prediction-selected actions, never hindsight extrema.
No production path imports this policy and no account is simulated here.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import learned_entry_models as base
from backend.market import normalized_continuation as normalized
from backend.market import sequential_execution_models as suffix

POLICY = "nonlinear-self-continuation/1-research"
ITERATIONS = 3
MIN_MATURE_SESSIONS = 504
PROTOCOL = "docs/research/nonlinear-self-continuation-plan-2026-10-07.md"


# Require explicit named stock membership so benchmarks cannot silently train heads.
def _contract(dataset):
    x, _, _, _, _ = base._validate(dataset)
    names = tuple(dataset.get("tickers", ()))
    if len(names) != x.shape[2] or len(set(names)) != len(names) or any(
        not isinstance(name, str) or not name for name in names
    ):
        raise ValueError("Unique original ticker names required")
    if "training_symbols" not in dataset:
        raise ValueError("Explicit stock-only training membership required")
    mask = base._training_symbols(dataset, len(names))
    if any(mask[index] for index, name in enumerate(names) if name in ("SPY", "QQQ")):
        raise ValueError("Benchmark names cannot train continuation models")
    return names


# Bind fitted trees and all prediction parameters without serializing model pickles.
def _model_hash(model):
    digest = hashlib.sha256()
    digest.update(base._json_hash(model.get_params()).encode())
    digest.update(base._array_hash(np.asarray(model._baseline_prediction)).encode())
    for trees in model._predictors:
        for tree in trees:
            for name in ("nodes", "binned_left_cat_bitsets", "raw_left_cat_bitsets"):
                values = np.asarray(getattr(tree, name))
                digest.update(base._array_hash(values).encode())
    mapper = model._bin_mapper
    for thresholds in mapper.bin_thresholds_:
        digest.update(base._array_hash(np.asarray(thresholds)).encode())
    digest.update(base._array_hash(mapper.is_categorical_).encode())
    digest.update(base._array_hash(mapper.n_bins_non_missing_).encode())
    return digest.hexdigest()


# Fit both side heads at every ordinary clock using only the supplied training days.
def _fit_heads(dataset, days, targets):
    x, _, valid, _, _ = base._validate(dataset)
    scale = normalized.scales(dataset)[days, :24]
    if np.shape(targets) != (len(days), 24, x.shape[2], 2):
        raise ValueError("Aligned whole-session side targets required")
    permitted = valid[days, :24] & np.isfinite(scale)
    permitted &= base._training_symbols(dataset, x.shape[2])[None, None, :]
    models, records = [], []
    for side in range(2):
        local, clock, stock = np.nonzero(permitted & np.isfinite(targets[..., side]))
        if not len(local):
            models.append(None)
            records.append({"status": "no_finite_targets", "rows": 0})
            continue
        labels = targets[local, clock, stock, side] / scale[local, clock, stock]
        finite = np.isfinite(labels)
        local, clock, stock, labels = (
            value[finite] for value in (local, clock, stock, labels)
        )
        if not len(local):
            models.append(None)
            records.append({"status": "no_finite_targets", "rows": 0})
            continue
        model = base._estimator("boosting")
        model.fit(x[days[local], clock, stock].astype(np.float64), labels)
        models.append(model)
        records.append({
            "status": "fitted", "rows": len(local),
            "distinct_dates": len(np.unique(days[local])),
            "clocks": np.unique(clock).tolist(),
            "row_days_sha256": base._array_hash(days[local]),
            "row_clocks_sha256": base._array_hash(clock),
            "row_stocks_sha256": base._array_hash(stock),
            "features_sha256": base._array_hash(x[days[local], clock, stock]),
            "targets_sha256": base._array_hash(labels),
            "model_sha256": _model_hash(model),
        })
    return models, records


# Score observed feature rows without consulting execution outcomes or later labels.
def _predict(heads, dataset, days):
    if len(heads) != 2:
        raise ValueError("Exactly two side heads required")
    x, _, valid, _, _ = base._validate(dataset)
    scale = normalized.scales(dataset)[days]
    local, clock, stock = np.nonzero(valid[days] & np.isfinite(scale))
    result = np.full((len(days), 25, x.shape[2], 2), np.nan, dtype=np.float64)
    for side, model in enumerate(heads):
        if model is not None and len(local):
            values = model.predict(x[days[local], clock, stock].astype(np.float64))
            with np.errstate(over="ignore", invalid="ignore"):
                values *= scale[local, clock, stock]
            values[~np.isfinite(values)] = np.nan
            result[local, clock, stock, side] = values
    return result


# Choose separate future suffixes before reading their realized training prices.
def _targets(dataset, days, forecasts):
    _, _, valid, _, _, close, execution, observed = suffix._inputs(dataset)
    supported = observed & valid
    supported[:, 24] = observed[:, 24]
    selected = np.stack([
        suffix.suffix_selection(forecasts[index], supported[day])
        for index, day in enumerate(days)
    ])
    targets = np.full((len(days), 24, execution.shape[2], 2), np.nan)
    for clock in range(24):
        future = suffix._selected_prices(execution, days, selected[:, clock + 1])
        for side in range(2):
            targets[:, clock, :, side] = suffix._target(
                execution, close, days, clock, future[..., side]
            )
    return targets, selected


# Improve each complement's own policy a fixed number of times from terminal execution.
def _chain(dataset, days):
    shape = np.shape(dataset["valid"])
    forecasts = np.full((len(days), 25, shape[2], 2), np.nan)
    previous = None
    records = []
    heads = [None, None]
    for iteration in range(ITERATIONS):
        targets, selected = _targets(dataset, days, forecasts)
        heads, fitted = _fit_heads(dataset, days, targets)
        records.append({
            "iteration": iteration,
            "targets_sha256": base._array_hash(targets),
            "selected_clocks_sha256": base._array_hash(selected),
            "changed_suffixes": (
                None if previous is None
                else int(np.count_nonzero(selected != previous))
            ),
            "heads": fitted,
        })
        previous = selected
        forecasts = _predict(heads, dataset, days)
    return heads, records


# Enforce monthly chronology and fit excluded-date chains before the final side heads.
def fit_month(dataset, fit_index):
    names = _contract(dataset)
    x, _, _, dates, features, _, _, _ = suffix._inputs(dataset)
    if isinstance(fit_index, (bool, np.bool_)) or not isinstance(
        fit_index, (int, np.integer)
    ):
        raise ValueError("An explicit monthly fit index required")
    if not 0 <= fit_index < len(dates):
        raise ValueError("Monthly fit index outside source calendar")
    month = dates[fit_index].astype("datetime64[M]")
    if fit_index and dates[fit_index - 1].astype("datetime64[M]") == month:
        raise ValueError("Fit must use the first supplied session of the month")
    days, cutoff = suffix.training_days(dates, int(fit_index))
    receipt = {
        "policy": POLICY, "fit_date": str(dates[fit_index]), "month": str(month),
        "label_end_before": str(cutoff), "training_days": len(days),
        "maximum_label_end": (
            str(dates[days[-1] + base.LABEL_SESSIONS]) if len(days) else None
        ),
        "days_sha256": base._array_hash(days),
        "training_dates_sha256": base._array_hash(dates[days]),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256(
            (Path(__file__).resolve().parents[2] / PROTOCOL).read_bytes()
        ).hexdigest(),
        "dependencies": {
            Path(module.__file__).name: hashlib.sha256(
                Path(module.__file__).read_bytes()
            ).hexdigest() for module in (base, normalized, suffix)
        },
        "numpy_version": np.__version__,
        "sklearn_version": importlib.metadata.version("scikit-learn"),
        "minimum_mature_sessions": MIN_MATURE_SESSIONS,
        "features": features, "tickers": names,
        "training_symbols_sha256": base._array_hash(
            base._training_symbols(dataset, x.shape[2])
        ),
        "iterations": ITERATIONS, "adoption_eligible": False,
        "status": "insufficient_mature_history", "folds": [],
    }
    bundle = {"heads": [None, None], "receipt": receipt, "fit_index": int(fit_index)}
    if len(days) < MIN_MATURE_SESSIONS:
        return bundle
    if not np.all(dates[days + base.LABEL_SESSIONS] < cutoff):
        raise ValueError("Training labels overlap the outer monthly cutoff")
    held_targets = np.full((len(days), 24, x.shape[2], 2), np.nan)
    with threadpool_limits(limits=2):
        for fold in range(3):
            train, held = days[days % 3 != fold], days[days % 3 == fold]
            if not len(train) or not len(held):
                raise ValueError("Each whole-date fold needs train and held sessions")
            heads, chain = _chain(dataset, train)
            held_forecasts = _predict(heads, dataset, held)
            labels, selected = _targets(dataset, held, held_forecasts)
            held_targets[np.flatnonzero(days % 3 == fold)] = labels
            receipt["folds"].append({
                "fold": fold, "train_days": train.tolist(), "held_days": held.tolist(),
                "chain": chain, "held_targets_sha256": base._array_hash(labels),
                "held_selected_clocks_sha256": base._array_hash(selected),
            })
        bundle["heads"], receipt["heads"] = _fit_heads(dataset, days, held_targets)
    available = [head is not None for head in bundle["heads"]]
    status = (
        "fitted" if all(available) else
        "partially_fitted" if any(available) else "no_finite_training_targets"
    )
    receipt.update(status=status, held_targets_sha256=base._array_hash(held_targets))
    bundle["held_targets"] = held_targets
    return bundle


# Admit only the fitted month and unchanged feature contract for out-of-sample scoring.
def predict_month(bundle, dataset, days):
    names = _contract(dataset)
    _, _, _, dates, features = base._validate(dataset)
    days = np.asarray(days)
    if days.ndim != 1 or days.dtype.kind not in "iu" or not len(days):
        raise ValueError("Nonempty integer scoring days required")
    if np.any(days < bundle["fit_index"]) or np.any(days >= len(dates)):
        raise ValueError("Scoring must follow the outer fit within the source calendar")
    receipt = bundle["receipt"]
    if (features != receipt["features"] or names != receipt["tickers"]
        or str(dates[bundle["fit_index"]]) != receipt["fit_date"]
        or np.any(
            dates[days].astype("datetime64[M]") != np.datetime64(receipt["month"])
        )):
        raise ValueError("Scoring month or feature identity differs")
    with threadpool_limits(limits=2):
        return _predict(bundle["heads"], dataset, days.astype(np.int64))
