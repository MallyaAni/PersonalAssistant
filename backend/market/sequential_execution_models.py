"""Crossfitted continuation-price heads with causal monthly execution forecasts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import learned_entry_models as original
from backend.market.learned_intraday_moments import certify_ridge

SCHEMA = "sequential-execution/1"
TARGET_SCHEMA = {
    "target": "stop_minus_prediction_selected_future_price_over_observed_close",
    "clocks": list(range(24)),
    "terminal": 24,
    "sides": ["buy", "sell"],
    "folds": "global_source_calendar_day_index_modulo_3",
    "unavailable_selected_price": "locked_missing_no_fallback",
    "ridge_precision": "float64",
    "ridge_certificate_tolerance": 1e-8,
}


# Convert a conditional price difference into an action without realized future prices.
def decision(predicted_difference, side):
    if side not in ("buy", "sell", 0, 1):
        raise ValueError("Side must be buy or sell")
    if not np.isfinite(predicted_difference):
        return "unavailable"
    wait = predicted_difference > 0 if side in ("buy", 0) else predicted_difference < 0
    return "wait" if wait else "execute"


# Select a separate stopping suffix for every start without reading outcome prices.
def suffix_selection(predictions, observed_valid, terminal=24):
    values, observed = np.asarray(predictions), np.asarray(observed_valid)
    if terminal != 24 or values.ndim != 3 or values.shape[0] != 25:
        raise ValueError("Expected predictions(25,S,2), terminal24")
    if (
        values.shape[-1] != 2
        or observed.dtype != bool
        or observed.shape != values.shape[:2]
    ):
        raise ValueError("Expected boolean observed validity(25,S)")
    chosen = np.full(values.shape, -1, dtype=np.int16)
    chosen[24] = np.where(observed[24, :, None], 24, -1)
    for clock in range(23, -1, -1):
        for side in range(2):
            known = observed[clock] & np.isfinite(values[clock, :, side])
            wait = (
                values[clock, :, side] > 0 if side == 0 else values[clock, :, side] < 0
            )
            chosen[clock, :, side] = np.where(
                known,
                np.where(wait, chosen[clock + 1, :, side], clock),
                chosen[clock + 1, :, side],
            )
    return chosen


# Validate execution arrays while leaving unavailable future outcomes eligible to score.
def _inputs(dataset):
    x, y, valid, dates, features = original._validate(dataset)
    close = np.asarray(dataset["current_close"])
    execution = np.asarray(dataset["next_open"])
    if close.shape != valid.shape or execution.shape != valid.shape:
        raise ValueError("Execution and observed close must have shape(D,25,S)")
    observed = np.isfinite(close) & (close > 0)
    return x, y, valid, dates, features, close, execution, observed


# Pin model, protocol, causal features, outcomes and the crossfitting contract exactly.
def identity(dataset):
    x, y, valid, dates, features, close, execution, _ = _inputs(dataset)
    value = original._identity(dataset, x, y, valid, dates, features, "ridge")
    value["original_model_source_sha256"] = value.pop("model_source_sha256")
    value.update(
        schema=SCHEMA,
        target_schema=TARGET_SCHEMA,
        train_clocks=list(range(24)),
        model_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        certificate_source_sha256=hashlib.sha256(
            Path(certify_ridge.__code__.co_filename).read_bytes()
        ).hexdigest(),
        sequential_protocol_sha256=hashlib.sha256(
            (
                Path(__file__).resolve().parents[2]
                / "docs/research/sequential-execution-plan-2026-10-02.md"
            ).read_bytes()
        ).hexdigest(),
    )
    value["arrays"].update(
        current_close=original._array_hash(close),
        next_open=original._array_hash(execution),
    )
    return json.loads(json.dumps(value))


# Keep only the fixed calendar window whose conservative label endpoints are known.
def training_days(dates, fit_index):
    cutoff = min(dates[fit_index], original.HOLDOUT_START)
    days = np.arange(max(0, fit_index - original.MAX_TRAIN_DAYS), fit_index)
    days = days[days + original.LABEL_SESSIONS < len(dates)]
    return days[dates[days + original.LABEL_SESSIONS] < cutoff], cutoff


# Reproduce a fitted Ridge pipeline using numeric parameters instead of model pickles.
def _predict(parameters, x):
    x = np.asarray(x, dtype=np.float64)
    missing = np.isnan(x)
    filled = np.where(missing, parameters["imputer"], x)
    z = np.column_stack((filled, missing[:, parameters["indicators"]]))
    z = (z - parameters["center"]) / parameters["scale"]
    return z @ parameters["coef"] + parameters["intercept"]


# Fit and certify one fixed Ridge head on observed rows with finite selected labels.
def _fit_head(x, target, days, clock, stock_mask, observed):
    mask = observed[days, clock] & stock_mask & np.isfinite(target)
    local, stock = np.nonzero(mask)
    row_days = days[local]
    receipt = {
        "rows": len(local),
        "days": len(np.unique(row_days)),
        "row_days_sha256": original._array_hash(row_days),
        "row_stocks_sha256": original._array_hash(stock),
        "target_sha256": original._array_hash(target[local, stock]),
    }
    if not len(local):
        receipt["status"] = "no_finite_targets"
        return None, receipt
    train_x = x[row_days, clock, stock].astype(np.float64)
    train_y = target[local, stock].astype(np.float64)
    model = original._estimator("ridge").fit(train_x, train_y)
    receipt.update(status="fitted", certificate=certify_ridge(model, train_x, train_y))
    imputer, scaler, ridge = model
    parameters = {
        "imputer": imputer.statistics_.copy(),
        "indicators": imputer.indicator_.features_.copy(),
        "center": scaler.mean_.copy(),
        "scale": scaler.scale_.copy(),
        "coef": ridge.coef_.copy(),
        "intercept": np.asarray(ridge.intercept_),
    }
    if not np.allclose(
        _predict(parameters, train_x), model.predict(train_x), rtol=1e-12, atol=1e-12
    ):
        raise RuntimeError("Numeric Ridge archive differs from fitted pipeline")
    receipt["parameters_sha256"] = {
        key: original._array_hash(np.atleast_1d(value))
        for key, value in parameters.items()
    }
    return parameters, receipt


# Evaluate a numeric head only on the causal observed feature rows supplied to it.
def _score_head(parameters, x, observed, days, clock):
    values = np.full((len(days), x.shape[2]), np.nan)
    if parameters is not None:
        local, stock = np.nonzero(observed[days, clock])
        values[local, stock] = _predict(parameters, x[days[local], clock, stock])
        values[~np.isfinite(values)] = np.nan
    return values


# Read the selected execution outcome once, preserving missing or invalid prices.
def _selected_prices(execution, days, chosen):
    selected = np.full(chosen.shape, np.nan, dtype=np.float64)
    for side in range(2):
        local, stock = np.nonzero(chosen[..., side] >= 0)
        selected[local, stock, side] = execution[
            days[local], chosen[local, stock, side], stock
        ]
    selected[~np.isfinite(selected) | (selected <= 0)] = np.nan
    return selected


# Form the fixed stop-minus-selected-wait target without hindsight price selection.
def _target(execution, close, days, clock, future):
    current = execution[days, clock].astype(np.float64)
    denominator = close[days, clock].astype(np.float64)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        target = (current - future) / denominator
    available = (
        np.isfinite(current)
        & (current > 0)
        & np.isfinite(denominator)
        & (denominator > 0)
    )
    return np.where(available & np.isfinite(target), target, np.nan)


# Fit one independent backward chain without observing any held-fold session labels.
def _nuisance_chain(x, close, execution, observed, days, stock_mask):
    future = np.repeat(execution[days, 24, :, None], 2, axis=-1).astype(np.float64)
    future[~observed[days, 24]] = np.nan
    future[~np.isfinite(future) | (future <= 0)] = np.nan
    heads, receipts = {}, {}
    for clock in range(23, -1, -1):
        predictions = np.full(future.shape, np.nan)
        for side in range(2):
            key = f"{clock}_{side}"
            target = _target(execution, close, days, clock, future[..., side])
            heads[key], receipts[key] = _fit_head(
                x, target, days, clock, stock_mask, observed
            )
            predictions[..., side] = _score_head(heads[key], x, observed, days, clock)
        for side in range(2):
            known = observed[days, clock] & np.isfinite(predictions[..., side])
            wait = (
                predictions[..., side] > 0 if side == 0 else predictions[..., side] < 0
            )
            stop_price = execution[days, clock].astype(np.float64)
            stop_price[~np.isfinite(stop_price) | (stop_price <= 0)] = np.nan
            future[..., side] = np.where(
                known, np.where(wait, future[..., side], stop_price), future[..., side]
            )
    return heads, receipts


# Score all ordinary clocks from causal inputs while keeping terminal forecasts empty.
def predict_window(bundle, dataset, days):
    x, _, valid, _, _, _, _, observed = _inputs(dataset)
    days = np.asarray(days, dtype=np.int64)
    predictions = np.full((len(days), 25, x.shape[2], 2), np.nan)
    for clock in range(24):
        for side in range(2):
            predictions[:, clock, :, side] = _score_head(
                bundle["heads"].get(f"{clock}_{side}"), x, observed & valid, days, clock
            )
    return predictions


# Fit excluded-date chains and final heads from their held-session suffix labels.
def fit_window(dataset, days, artifact_dir=None):
    x, _, valid, dates, _, close, execution, observed = _inputs(dataset)
    days = np.asarray(days, dtype=np.int64)
    if (
        days.ndim != 1
        or not len(days)
        or np.any(days[1:] <= days[:-1])
        or np.any(days < 0)
        or np.any(days >= len(dates))
    ):
        raise ValueError("Fit days must be nonempty unique ordered calendar indices")
    stock_mask = original._training_symbols(dataset, x.shape[2])
    oof_chosen = np.full((len(days), 25, x.shape[2], 2), -1, dtype=np.int16)
    labels = np.full((len(days), 24, x.shape[2], 2), np.nan)
    bundle = {"heads": {}, "nuisance": {}, "oof_selected_clocks": oof_chosen}
    receipt = {
        "folds": [],
        "heads": {},
        "training_days": len(days),
        "days_sha256": original._array_hash(days),
    }
    with threadpool_limits(limits=2):
        for fold in range(3):
            train, held = days[days % 3 != fold], days[days % 3 == fold]
            chain_observed = observed & valid
            chain_observed[:, 24] = observed[:, 24]
            heads, head_receipts = _nuisance_chain(
                x, close, execution, chain_observed, train, stock_mask
            )
            bundle["nuisance"][str(fold)] = heads
            forecasts = predict_window({"heads": heads}, dataset, held)
            held_chosen = (
                np.stack(
                    [
                        suffix_selection(forecasts[i], observed[day])
                        for i, day in enumerate(held)
                    ]
                )
                if len(held)
                else np.empty((0, 25, x.shape[2], 2), dtype=np.int16)
            )
            local = np.flatnonzero(days % 3 == fold)
            oof_chosen[local] = held_chosen
            for clock in range(24):
                selected = _selected_prices(execution, held, held_chosen[:, clock + 1])
                for side in range(2):
                    labels[local, clock, :, side] = _target(
                        execution, close, held, clock, selected[..., side]
                    )
            receipt["folds"].append(
                {
                    "fold": fold,
                    "train_days": train.tolist(),
                    "held_days": held.tolist(),
                    "train_dates_sha256": original._array_hash(dates[train]),
                    "held_dates_sha256": original._array_hash(dates[held]),
                    "heads": head_receipts,
                    "selected_clocks_sha256": original._array_hash(held_chosen),
                }
            )
        for clock in range(24):
            for side in range(2):
                key = f"{clock}_{side}"
                bundle["heads"][key], receipt["heads"][key] = _fit_head(
                    x,
                    labels[:, clock, :, side],
                    days,
                    clock,
                    stock_mask,
                    observed & valid,
                )
    bundle["oof_targets"] = labels
    receipt.update(
        oof_targets_sha256=original._array_hash(labels),
        oof_selected_clocks_sha256=original._array_hash(oof_chosen),
    )
    if artifact_dir is not None:
        output = Path(artifact_dir)
        output.mkdir(parents=True, exist_ok=True)
        receipt["bundle"] = _save_bundle(output / "models.npz", bundle)
        original._write_json(output / "fit.json", receipt)
    return bundle, receipt


# Store fitted numeric coefficients and the crossfitted labels in one atomic archive.
def _save_bundle(path, bundle):
    arrays = {
        "oof_targets": bundle["oof_targets"],
        "oof_selected_clocks": bundle["oof_selected_clocks"],
    }
    for group, heads in [("final", bundle["heads"])] + [
        (f"fold{fold}", heads) for fold, heads in bundle["nuisance"].items()
    ]:
        for head, parameters in heads.items():
            if parameters is not None:
                arrays.update(
                    {
                        f"{group}_{head}_{name}": value
                        for name, value in parameters.items()
                    }
                )
    _save_npz(path, arrays)
    return {
        "file": path.name,
        "sha256": _file_hash(path),
        "arrays": {
            key: original._array_hash(np.atleast_1d(value))
            for key, value in arrays.items()
        },
    }


# Hash persisted bytes rather than trusting an archive's filename or existence.
def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Publish numeric archives atomically so interruption cannot masquerade as completion.
def _save_npz(path, arrays):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez(handle, **arrays)
    os.replace(temporary, path)


# Authenticate each numeric archive against both its file and per-array receipts.
def _read_npz(path, receipt):
    if _file_hash(path) != receipt["sha256"]:
        raise ValueError("Saved numeric artifact byte mismatch")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    hashes = {
        key: original._array_hash(np.atleast_1d(value)) for key, value in arrays.items()
    }
    if hashes != receipt["arrays"]:
        raise ValueError("Saved numeric artifact array mismatch")
    return arrays


# Verify source identity, exact monthly schedule, mature folds and saved forecast bytes.
def validate_saved(directory, dataset):
    output = Path(directory)
    manifest = json.loads((output / "manifest.json").read_text())
    expected = identity(dataset)
    if manifest["identity"] != expected or manifest[
        "identity_sha256"
    ] != original._json_hash(expected):
        raise ValueError("Saved run differs from exact identity")
    arrays = _read_npz(output / "predictions.npz", manifest["forecast"])
    dates = np.asarray(dataset["dates"], dtype="datetime64[D]")
    close = np.asarray(dataset["current_close"])
    score_valid = np.asarray(dataset["valid"]) & np.isfinite(close) & (close > 0)
    if not np.array_equal(arrays["dates"], dates):
        raise ValueError("Saved forecast calendar mismatch")
    if (
        arrays["dates"].dtype != np.dtype("datetime64[D]")
        or arrays["dates"].shape != dates.shape
        or arrays["predictions"].dtype != np.dtype("float32")
        or arrays["predictions"].shape != np.asarray(dataset["valid"]).shape + (2,)
    ):
        raise ValueError("Saved forecast dtype or shape mismatch")
    result = np.full(
        np.asarray(dataset["valid"]).shape + (2,), np.nan, dtype=np.float32
    )
    months = dates.astype("datetime64[M]")
    if [m["month"] for m in manifest["months"]] != [str(m) for m in np.unique(months)]:
        raise ValueError("Saved monthly schedule mismatch")
    for month in manifest["months"]:
        days = np.flatnonzero(months == np.datetime64(month["month"]))
        train, cutoff = training_days(dates, days[0])
        _verify_month(
            output, month, days, train, cutoff, expected, result, dates, score_valid
        )
    if not np.array_equal(result, arrays["predictions"], equal_nan=True):
        raise ValueError("Global predictions differ from monthly artifacts")
    return result, manifest


# Authenticate each numeric head's fitted certificate and parameter bytes.
def _verify_heads(parameters, group, heads):
    if set(heads) != {f"{k}_{s}" for k in range(24) for s in range(2)}:
        raise ValueError("Expected every clock and side head")
    for key, record in heads.items():
        if record["status"] == "no_finite_targets":
            if record["rows"] != 0:
                raise ValueError("Unavailable head has training rows")
            continue
        cert = record["certificate"]
        if (
            record["status"] != "fitted"
            or not cert["certified"]
            or cert["tolerance"] != 1e-8
            or not np.isfinite(cert["normalized_gradient"])
            or cert["normalized_gradient"] > 1e-8
        ):
            raise ValueError("Uncertified Ridge artifact")
        for name, digest in record["parameters_sha256"].items():
            if (
                original._array_hash(np.atleast_1d(parameters[f"{group}_{key}_{name}"]))
                != digest
            ):
                raise ValueError("Head parameter mismatch")


# Authenticate whole-session fold memberships and every fitted numeric head.
def _verify_fit(folder, fit, train):
    if fit["days_sha256"] != original._array_hash(train) or len(fit["folds"]) != 3:
        raise ValueError("Saved training window mismatch")
    parameters = _read_npz(folder / "models.npz", fit["bundle"])
    for fold, record in enumerate(fit["folds"]):
        if (
            record["fold"] != fold
            or record["train_days"] != train[train % 3 != fold].tolist()
            or record["held_days"] != train[train % 3 == fold].tolist()
        ):
            raise ValueError("Whole-session exclusion mismatch")
        _verify_heads(parameters, f"fold{fold}", record["heads"])
    _verify_heads(parameters, "final", fit["heads"])
    if (
        original._array_hash(parameters["oof_targets"]) != fit["oof_targets_sha256"]
        or original._array_hash(parameters["oof_selected_clocks"])
        != fit["oof_selected_clocks_sha256"]
    ):
        raise ValueError("Held-fold target artifact mismatch")


# Check monthly maturity, fold exclusion, coefficients and causal forecast clocks.
def _verify_month(
    output, month, days, train, cutoff, expected, result, dates, score_valid
):
    folder = output / month["month"]
    if json.loads((folder / "receipt.json").read_text()) != month:
        raise ValueError("Saved monthly receipt mismatch")
    if (
        month["identity_sha256"] != original._json_hash(expected)
        or month["training_days"] != len(train)
        or month["label_end_before"] != str(cutoff)
        or month["fit_date"] != str(dates[days[0]])
        or month["train_first"] != (str(dates[train[0]]) if len(train) else None)
        or month["train_last"] != (str(dates[train[-1]]) if len(train) else None)
        or month["max_label_end"]
        != (str(dates[train[-1] + 10]) if len(train) else None)
    ):
        raise ValueError("Saved monthly maturity mismatch")
    if month["status"] == "insufficient_mature_history":
        if len(train) >= original.MIN_TRAIN_DAYS:
            raise ValueError("Incorrect warmup status")
        return
    if month["status"] != "fitted" or len(train) < original.MIN_TRAIN_DAYS:
        raise ValueError("Incorrect fitted status")
    _verify_fit(folder, month["fit"], train)
    forecasts = _read_npz(folder / "predictions.npz", month["forecast"])
    if (
        not np.array_equal(forecasts["days"], days)
        or forecasts["days"].dtype != np.dtype("int64")
        or forecasts["days"].shape != days.shape
        or forecasts["predictions"].dtype != np.dtype("float32")
        or forecasts["predictions"].shape != result[days].shape
        or np.isfinite(forecasts["predictions"][:, 24]).any()
        or np.isfinite(forecasts["predictions"][~score_valid[days]]).any()
    ):
        raise ValueError("Saved forecast clock or calendar mismatch")
    result[days] = forecasts["predictions"]


# Fit each fixed monthly cutoff once and resume only exact authenticated artifacts.
def walk_forward(dataset, output_dir=None):
    _, _, valid, dates, _, _, _, observed = _inputs(dataset)
    pinned = identity(dataset)
    digest = original._json_hash(pinned)
    output = original._output_directory(output_dir, pinned)
    if output is not None and (output / "manifest.json").exists():
        return validate_saved(output, dataset)
    predictions = np.full(valid.shape + (2,), np.nan, dtype=np.float32)
    manifest = {"identity": pinned, "identity_sha256": digest, "months": []}
    months = dates.astype("datetime64[M]")
    for month in np.unique(months):
        score_days = np.flatnonzero(months == month)
        train, cutoff = training_days(dates, score_days[0])
        receipt = {
            "month": str(month),
            "identity_sha256": digest,
            "training_days": len(train),
            "label_end_before": str(cutoff),
            "fit_date": str(dates[score_days[0]]),
            "train_first": str(dates[train[0]]) if len(train) else None,
            "train_last": str(dates[train[-1]]) if len(train) else None,
            "max_label_end": str(dates[train[-1] + 10]) if len(train) else None,
        }
        folder = output / str(month) if output is not None else None
        if folder is not None:
            folder.mkdir(exist_ok=True)
        if folder is not None and (folder / "receipt.json").exists():
            receipt = json.loads((folder / "receipt.json").read_text())
            _verify_month(
                output,
                receipt,
                score_days,
                train,
                cutoff,
                pinned,
                predictions,
                dates,
                valid & observed,
            )
        elif len(train) < original.MIN_TRAIN_DAYS:
            receipt["status"] = "insufficient_mature_history"
        else:
            bundle, fit = fit_window(dataset, train, folder)
            predictions[score_days] = predict_window(
                bundle, dataset, score_days
            ).astype(np.float32)
            receipt.update(status="fitted", fit=fit)
            if folder is not None:
                path = folder / "predictions.npz"
                arrays = {"days": score_days, "predictions": predictions[score_days]}
                _save_npz(path, arrays)
                receipt["forecast"] = {
                    "sha256": _file_hash(path),
                    "arrays": {k: original._array_hash(v) for k, v in arrays.items()},
                }
        manifest["months"].append(receipt)
        if folder is not None:
            original._write_json(folder / "receipt.json", receipt)
            original._write_json(output / "progress.json", manifest)
    if output is not None:
        path = output / "predictions.npz"
        arrays = {"predictions": predictions, "dates": dates}
        _save_npz(path, arrays)
        manifest["forecast"] = {
            "sha256": _file_hash(path),
            "arrays": {k: original._array_hash(v) for k, v in arrays.items()},
        }
        original._write_json(output / "manifest.json", manifest)
    return predictions, manifest
