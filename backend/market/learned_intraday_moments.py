"""Duration-matched monthly waiting means and risk, isolated from earlier fits."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import learned_entry_models as original

SCHEMA = "learned-intraday-moments/1"
RIDGE_CERTIFICATE_TOLERANCE = 1e-8
TARGET_SCHEMA = {
    "mean": "log_immediate_open_over_fifteen_minute_later_open",
    "second_moment": "square_of_same_fifteen_minute_log_price_advantage",
    "original_label_column": 2,
    "elapsed_minutes": 15,
    "prediction_clocks": list(range(23)),
    "maturity_sessions": 10,
    "not_epistemic_uncertainty": True,
}


# Describe regular-session label duration from calendar clocks without future prices.
def waiting_elapsed_minutes(dates):
    dates = np.asarray(dates, dtype="datetime64[D]")
    if np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
        raise ValueError("Unique ordered session dates required for elapsed duration")
    elapsed = np.full((len(dates), 25), 15.0)
    elapsed[:, 24] = np.nan
    zone = ZoneInfo("America/New_York")
    for day in range(len(dates) - 1):
        current = dt.datetime.combine(
            dt.date.fromisoformat(str(dates[day])), dt.time(15, 45), zone
        )
        later = dt.datetime.combine(
            dt.date.fromisoformat(str(dates[day + 1])), dt.time(9, 45), zone
        )
        elapsed[day, 24] = (
            later.astimezone(dt.UTC) - current.astimezone(dt.UTC)
        ).total_seconds() / 60
    return elapsed


# Mask targets solely by declared duration and preserve unavailable waiting outcomes.
def targets(dataset, elapsed):
    waiting = np.asarray(dataset["y"])[..., 2].astype(np.float64)
    waiting = np.where(elapsed[..., None] == 15, waiting, np.nan)
    with np.errstate(over="ignore", invalid="ignore"):
        second = waiting * waiting
    known = np.isfinite(waiting) & np.isfinite(second)
    return np.where(known, waiting, np.nan), np.where(known, second, np.nan)


# Check the fitted Ridge normal equations and intercept in transformed feature units.
def certify_ridge(model, x, y):
    z = model[:-1].transform(np.asarray(x, dtype=np.float64))
    y = np.asarray(y, dtype=np.float64)
    ridge = model[-1]
    residual = ridge.predict(z) - y
    alpha_coef = float(ridge.alpha) * ridge.coef_
    coefficient_gradient = z.T @ residual + alpha_coef
    intercept_gradient = float(residual.sum())
    scale = max(
        1.0,
        float(np.linalg.norm(z.T @ y)),
        float(np.linalg.norm(alpha_coef)),
        abs(float(len(y) * y.mean())),
    )
    normalized = (
        max(float(np.linalg.norm(coefficient_gradient)), abs(intercept_gradient))
        / scale
    )
    if not np.isfinite(normalized) or normalized > RIDGE_CERTIFICATE_TOLERANCE:
        raise RuntimeError("Ridge fit failed its normal-equation certificate")
    return {
        "normalized_gradient": normalized,
        "tolerance": RIDGE_CERTIFICATE_TOLERANCE,
        "coefficient_gradient_norm": float(np.linalg.norm(coefficient_gradient)),
        "intercept_gradient": intercept_gradient,
        "normalization": scale,
        "input_target_precision": "float64",
        "certified": True,
    }


# Pin original inputs, both estimators and the new duration-matched targets and code.
def _identity(dataset, x, y, valid, dates, features, elapsed, mean, second):
    receipt = original._identity(dataset, x, y, valid, dates, features, "boosting")
    receipt.update(
        schema=SCHEMA,
        method="fifteen_minute_joint_moments",
        target_schema=TARGET_SCHEMA,
        mean_target_sha256=original._array_hash(mean),
        second_target_sha256=original._array_hash(second),
        elapsed_minutes_sha256=original._array_hash(elapsed),
        ridge_config=original.MODEL_CONFIG["ridge"],
        ridge_precision="float64",
        ridge_certificate_tolerance=RIDGE_CERTIFICATE_TOLERANCE,
    )
    receipt["original_model_source_sha256"] = receipt.pop("model_source_sha256")
    receipt["model_source_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    protocol = (
        Path(__file__).resolve().parents[2]
        / "docs/research/fifteen-minute-execution-plan-2026-10-02.md"
    )
    receipt["duration_protocol_sha256"] = hashlib.sha256(
        protocol.read_bytes()
    ).hexdigest()
    return receipt


# Build the complete canonical identity for authentication without fitting anything.
def identity(dataset):
    x, y, valid, dates, features = original._validate(dataset)
    elapsed = waiting_elapsed_minutes(dates)
    mean, second = targets(dataset, elapsed)
    return _identity(dataset, x, y, valid, dates, features, elapsed, mean, second)


# Use the original clocks and maturity rules, excluding duration-mismatched rows.
def training_rows(dates, valid, waiting, elapsed, fit_index, symbols):
    duration_valid = valid & (elapsed[..., None] == 15)
    labels = np.broadcast_to(waiting[..., None], waiting.shape + (3,))
    return original.training_rows(dates, duration_valid, labels, fit_index, symbols)


# Save a trusted locally fitted estimator without ever deserializing model pickles.
def _save_model(output, month, name, model):
    import joblib

    filename = f"{month}-{name}.joblib"
    temporary = output / (filename + ".tmp")
    joblib.dump(model, temporary, compress=0)
    os.replace(temporary, output / filename)
    return {
        "name": name,
        "file": filename,
        "sha256": hashlib.sha256((output / filename).read_bytes()).hexdigest(),
    }


# Fit the declared two waiting means and common risk on exactly the same rows.
def _fit_month(
    x, mean, second, score_valid, indices, month_days, month, output, means, risk
):
    day, clock, stock = indices
    train_x = x[day, clock, stock].astype(np.float64)
    train_mean, train_second = mean[day, clock, stock], second[day, clock, stock]
    local_day, score_clock, score_stock = np.nonzero(score_valid[month_days])
    score_day = month_days[local_day]
    score_x = x[score_day, score_clock, score_stock].astype(np.float64)
    models, unavailable, negative = [], {}, 0
    receipt = {"status": "fitted", "prediction_rows": len(score_day)}
    with threadpool_limits(limits=2):
        for name, method, target in (
            ("boosting_mean", "boosting", train_mean),
            ("ridge_mean", "ridge", train_mean),
            ("risk", "boosting", train_second),
        ):
            model = original._estimator(method)
            model.fit(train_x, target)
            if method == "ridge":
                receipt["ridge_certificate"] = certify_ridge(model, train_x, target)
            values = model.predict(score_x) if len(score_x) else np.empty(0)
            with np.errstate(over="ignore", invalid="ignore"):
                values = values.astype(np.float32)
            unavailable[name] = int((~np.isfinite(values)).sum())
            values[~np.isfinite(values)] = np.nan
            if name == "risk":
                negative = int((np.isfinite(values) & (values < 0)).sum())
                risk[score_day, score_clock, score_stock] = values
            else:
                means[method][score_day, score_clock, score_stock, 2] = values
            if output is not None:
                models.append(_save_model(output, month, name, model))
    receipt.update(
        models=models,
        nonfinite_predictions=unavailable,
        negative_second_moment_predictions=negative,
    )
    return receipt


# Publish monthly or complete forecast arrays atomically before their receipt.
def _save_arrays(output, filename, days, dates, elapsed, means, risk):
    temporary = output / (filename + ".tmp")
    with temporary.open("wb") as handle:
        np.savez(
            handle,
            days=days,
            dates=dates[days],
            waiting_elapsed_minutes=elapsed[days],
            means_boosting=means["boosting"][days],
            means_ridge=means["ridge"][days],
            risk=risk[days],
        )
    os.replace(temporary, output / filename)
    return {
        "prediction_file": filename,
        "prediction_file_sha256": hashlib.sha256(
            (output / filename).read_bytes()
        ).hexdigest(),
    }


# Check monthly target and estimator semantics before trusting saved forecast bytes.
def _validate_receipt(receipt, digest):
    if (
        receipt.get("target_schema") != TARGET_SCHEMA
        or receipt["identity_sha256"] != digest
    ):
        raise ValueError("Saved intraday schema or identity changed")
    if receipt["status"] == "insufficient_mature_history":
        return
    if (
        receipt["status"] != "fitted"
        or {m["name"] for m in receipt["models"]}
        != {"boosting_mean", "ridge_mean", "risk"}
        or len(receipt["models"]) != 3
    ):
        raise ValueError("Expected three duration-matched fitted heads")
    certificate = receipt["ridge_certificate"]
    if (
        not certificate["certified"]
        or not 0 <= certificate["normalized_gradient"] <= RIDGE_CERTIFICATE_TOLERANCE
    ):
        raise ValueError("Saved Ridge certificate is invalid")


# Preserve each declared array shape and dtype before reading its numeric values.
def _same_representation(saved, expected):
    return saved.shape == expected.shape and saved.dtype == expected.dtype


# Validate original model and prediction hashes before restoring a completed month.
def _resume(output, path, days, dates, elapsed, means, risk, digest):
    receipt = json.loads(path.read_text())
    _validate_receipt(receipt, digest)
    if receipt["status"] == "insufficient_mature_history":
        return receipt
    for model in receipt["models"]:
        if (
            hashlib.sha256((output / model["file"]).read_bytes()).hexdigest()
            != model["sha256"]
        ):
            raise ValueError("Saved intraday model hash mismatch")
    archive = output / receipt["prediction_file"]
    if (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        != receipt["prediction_file_sha256"]
    ):
        raise ValueError("Saved intraday forecast hash mismatch")
    with np.load(archive, allow_pickle=False) as saved:
        if not np.array_equal(saved["days"], days) or not np.array_equal(
            saved["dates"], dates[days]
        ):
            raise ValueError("Saved intraday month calendar mismatch")
        np.testing.assert_array_equal(saved["waiting_elapsed_minutes"], elapsed[days])
        if not _same_representation(saved["risk"], risk[days]):
            raise ValueError("Saved intraday risk shape or dtype mismatch")
        risk[days] = saved["risk"]
        for method in means:
            if not _same_representation(saved["means_" + method], means[method][days]):
                raise ValueError("Saved intraday mean shape or dtype mismatch")
            means[method][days] = saved["means_" + method]
    return receipt


# Refit duration-matched moments monthly and score only ordinary causal decisions.
def walk_forward(dataset, output_dir=None):
    x, y, valid, dates, features = original._validate(dataset)
    elapsed = waiting_elapsed_minutes(dates)
    mean, second = targets(dataset, elapsed)
    fingerprint = _identity(
        dataset, x, y, valid, dates, features, elapsed, mean, second
    )
    digest = original._json_hash(fingerprint)
    output = original._output_directory(output_dir, fingerprint)
    means = {
        method: np.full(y.shape, np.nan, dtype=np.float32)
        for method in ("boosting", "ridge")
    }
    risk = np.full(valid.shape, np.nan, dtype=np.float32)
    score_valid = valid.copy()
    score_valid[:, 23:] = False
    manifest = {"identity": fingerprint, "identity_sha256": digest, "months": []}
    months = dates.astype("datetime64[M]")
    symbols = original._training_symbols(dataset, x.shape[2])
    for month in np.unique(months):
        days = np.flatnonzero(months == month)
        path = output / f"{month}.json" if output is not None else None
        if path is not None and path.exists():
            manifest["months"].append(
                _resume(output, path, days, dates, elapsed, means, risk, digest)
            )
            continue
        day, clock, stock, cutoff = training_rows(
            dates, valid, mean, elapsed, int(days[0]), symbols
        )
        distinct = np.unique(day)
        receipt = {
            "month": str(month),
            "fit_date": str(dates[days[0]]),
            "label_end_before": str(cutoff),
            "training_days": len(distinct),
            "training_rows": len(day),
            "training_clocks": sorted(np.unique(clock).tolist()),
            "identity_sha256": digest,
            "target_schema": TARGET_SCHEMA,
            "status": "insufficient_mature_history",
        }
        if len(distinct):
            receipt.update(
                train_first=str(dates[distinct[0]]),
                train_last=str(dates[distinct[-1]]),
                maximum_label_end=str(dates[day.max() + original.LABEL_SESSIONS]),
            )
        if len(distinct) >= original.MIN_TRAIN_DAYS:
            receipt.update(
                _fit_month(
                    x,
                    mean,
                    second,
                    score_valid,
                    (day, clock, stock),
                    days,
                    month,
                    output,
                    means,
                    risk,
                )
            )
            if output is not None:
                receipt.update(
                    _save_arrays(
                        output,
                        f"{month}-predictions.npz",
                        days,
                        dates,
                        elapsed,
                        means,
                        risk,
                    )
                )
        manifest["months"].append(receipt)
        if output is not None:
            original._write_json(path, receipt)
            original._write_json(output / "progress.json", manifest)
        print(
            json.dumps(
                {
                    "month": str(month),
                    "status": receipt["status"],
                    "training_days": receipt["training_days"],
                    "training_rows": receipt["training_rows"],
                }
            ),
            flush=True,
        )
    manifest["prediction_sha256"] = {
        **{method: original._array_hash(value) for method, value in means.items()},
        "risk": original._array_hash(risk),
    }
    if output is not None:
        manifest.update(
            _save_arrays(
                output,
                "predictions.npz",
                np.arange(len(dates)),
                dates,
                elapsed,
                means,
                risk,
            )
        )
        original._write_json(output / "manifest.json", manifest)
    return means, risk, manifest


# Check each monthly receipt against the actual duration-filtered mature training rows.
def _verify_schedule(receipt, dataset, waiting, elapsed, days):
    day, clock, _, cutoff = training_rows(
        dataset["dates"],
        dataset["valid"],
        waiting,
        elapsed,
        int(days[0]),
        original._training_symbols(dataset, dataset["X"].shape[2]),
    )
    dates = dataset["dates"]
    distinct = np.unique(day)
    expected = {
        "fit_date": str(dates[days[0]]),
        "label_end_before": str(cutoff),
        "training_days": len(distinct),
        "training_rows": len(day),
        "training_clocks": sorted(np.unique(clock).tolist()),
    }
    if len(distinct):
        expected.update(
            train_first=str(dates[distinct[0]]),
            train_last=str(dates[distinct[-1]]),
            maximum_label_end=str(dates[day.max() + original.LABEL_SESSIONS]),
        )
    status = (
        "fitted"
        if len(distinct) >= original.MIN_TRAIN_DAYS
        else "insufficient_mature_history"
    )
    if receipt["status"] != status or any(
        receipt.get(k) != v for k, v in expected.items()
    ):
        raise ValueError("Saved intraday training schedule or maturity differs")


# Verify forecast eligibility and reconcile raw unavailable or negative model outputs.
def _verify_predictions(receipt, days, valid, means, risk):
    allowed = valid[days].copy()
    allowed[:, 23:] = False
    outputs = {
        "boosting_mean": means["boosting"][days, ..., 2],
        "ridge_mean": means["ridge"][days, ..., 2],
        "risk": risk[days],
    }
    if receipt["prediction_rows"] != int(allowed.sum()):
        raise ValueError("Saved intraday prediction denominator differs")
    for name, values in outputs.items():
        if np.isfinite(values[~allowed]).any() or np.isinf(values).any():
            raise ValueError(
                "Saved intraday predictions violate causal clock eligibility"
            )
        if (
            int((~np.isfinite(values[allowed])).sum())
            != receipt["nonfinite_predictions"][name]
        ):
            raise ValueError("Saved intraday unavailable prediction count differs")
    negatives = int((np.isfinite(outputs["risk"]) & (outputs["risk"] < 0)).sum())
    if negatives != receipt["negative_second_moment_predictions"]:
        raise ValueError("Saved intraday invalid-risk count differs")
    if any(np.isfinite(value[days, ..., :2]).any() for value in means.values()):
        raise ValueError("Unrelated ten-session mean heads cannot be populated")


# Authenticate saved identities and arrays without refitting or loading models.
def validate_saved(directory, dataset):
    output = Path(directory)
    fingerprint = identity(dataset)
    digest = original._json_hash(fingerprint)
    manifest = json.loads((output / "manifest.json").read_text())
    stored = json.loads((output / "identity.json").read_text())
    canonical = json.loads(json.dumps(fingerprint))
    if (
        stored != canonical
        or manifest["identity"] != canonical
        or manifest["identity_sha256"] != digest
    ):
        raise ValueError("Saved intraday complete identity differs")
    dates, valid = dataset["dates"], dataset["valid"]
    elapsed = waiting_elapsed_minutes(dates)
    mean, _ = targets(dataset, elapsed)
    means = {
        method: np.full(dataset["y"].shape, np.nan, dtype=np.float32)
        for method in ("boosting", "ridge")
    }
    risk = np.full(valid.shape, np.nan, dtype=np.float32)
    months = dates.astype("datetime64[M]")
    if [r["month"] for r in manifest["months"]] != [str(m) for m in np.unique(months)]:
        raise ValueError("Saved intraday monthly sequence differs")
    for receipt in manifest["months"]:
        days = np.flatnonzero(months == np.datetime64(receipt["month"], "M"))
        _verify_schedule(receipt, dataset, mean, elapsed, days)
        original_receipt = _resume(
            output,
            output / (receipt["month"] + ".json"),
            days,
            dates,
            elapsed,
            means,
            risk,
            digest,
        )
        if original_receipt != receipt:
            raise ValueError("Monthly receipt differs from completion manifest")
        if receipt["status"] == "fitted":
            _verify_predictions(receipt, days, valid, means, risk)
    hashes = {
        **{name: original._array_hash(value) for name, value in means.items()},
        "risk": original._array_hash(risk),
    }
    archive = output / manifest["prediction_file"]
    if hashes != manifest["prediction_sha256"] or (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        != manifest["prediction_file_sha256"]
    ):
        raise ValueError("Saved intraday complete prediction bytes differ")
    with np.load(archive, allow_pickle=False) as saved:
        for name, value in {
            "means_boosting": means["boosting"],
            "means_ridge": means["ridge"],
            "risk": risk,
            "dates": dates,
            "days": np.arange(len(dates)),
            "waiting_elapsed_minutes": elapsed,
        }.items():
            if not _same_representation(saved[name], value) or not np.array_equal(
                saved[name], value, equal_nan=True
            ):
                raise ValueError(
                    "Saved intraday complete array dtype, shape or values differ"
                )
    return means, risk, manifest
