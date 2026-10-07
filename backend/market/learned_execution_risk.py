"""One preregistered short-horizon second moment for learned execution timing.

The target is squared one-decision waiting advantage. Ten-session return risk
is neither the target nor a substitute. This is not epistemic uncertainty.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import learned_entry_models as original

SCHEMA = "learned-execution-risk/1"
TARGET_SCHEMA = {
    "label": "squared_log_immediate_open_over_one_decision_later_open",
    "original_label_column": 2,
    "units": "squared_log_price_ratio",
    "execution_horizon": "one_decision_log_price_advantage",
    "terminal_wait": "next_session_first_completed_bar",
    "maturity_sessions": 10,
    "not_epistemic_uncertainty": True,
}


# Derive waiting risk without borrowing the unrelated ten-session return labels.
def waiting_second_moment(dataset):
    waiting = np.asarray(dataset["y"])[..., 2].astype(np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        squared = waiting * waiting
    squared[~np.isfinite(squared)] = np.nan
    return squared


# Pin original inputs and architecture together with the new target and protocol.
def identity(dataset, x, y, valid, dates, features, target):
    receipt = original._identity(dataset, x, y, valid, dates, features, "boosting")
    receipt["method"] = "waiting_second_moment_boosting"
    receipt["schema"] = SCHEMA
    receipt["target_schema"] = TARGET_SCHEMA
    receipt["target_sha256"] = original._array_hash(target)
    receipt["original_model_source_sha256"] = receipt.pop("model_source_sha256")
    receipt["model_source_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    protocol = (
        Path(__file__).resolve().parents[2]
        / "docs/research/learned-execution-risk-plan-2026-10-02.md"
    )
    receipt["execution_risk_protocol_sha256"] = hashlib.sha256(
        protocol.read_bytes()
    ).hexdigest()
    return receipt


# Select known waiting outcomes with the original clock, maturity and holdout rules.
def training_rows(dates, valid, target, fit_index, training_symbols):
    # A broadcast view preserves the original row selector without three label copies.
    labels = np.broadcast_to(target[..., None], target.shape + (3,))
    return original.training_rows(dates, valid, labels, fit_index, training_symbols)


# Fit exactly one fixed HGB head and predict valid inputs with no future-label filter.
def _fit_month(x, target, valid, indices, month_days, month, output, predictions):
    day, clock, stock = indices
    local_day, score_clock, score_stock = np.nonzero(valid[month_days])
    score_day = month_days[local_day]
    model = original._estimator("boosting")
    negative, unavailable = 0, 0
    with threadpool_limits(limits=2):
        model.fit(x[day, clock, stock], target[day, clock, stock])
        if len(score_day):
            values = model.predict(x[score_day, score_clock, score_stock])
            with np.errstate(over="ignore", invalid="ignore"):
                values = values.astype(np.float32)
            unavailable = int((~np.isfinite(values)).sum())
            negative = int((np.isfinite(values) & (values < 0)).sum())
            # Preserve negative finite model outputs; the controller rejects them.
            values[~np.isfinite(values)] = np.nan
            predictions[score_day, score_clock, score_stock] = values
    models = [] if output is None else [original._save_model(output, month, 0, model)]
    return {
        "status": "fitted",
        "prediction_rows": len(score_day),
        "models": models,
        "negative_second_moment_predictions": negative,
        "unavailable_nonfinite_predictions": unavailable,
    }


# Reject incompatible risk semantics before verifying and restoring monthly bytes.
def _resume_month(output, path, month_days, predictions, digest):
    receipt = json.loads(path.read_text())
    if receipt.get("target_schema") != TARGET_SCHEMA:
        raise ValueError("Saved risk target schema or horizon changed")
    if receipt["status"] == "fitted" and (
        len(receipt["models"]) != 1 or receipt["models"][0]["head"] != 0
    ):
        raise ValueError("Saved risk estimator must contain exactly one head")
    return original._resume_month(output, path, month_days, predictions, digest)


# Refit one waiting-risk head monthly and retain authenticated resumable artifacts.
def walk_forward(dataset, output_dir=None):
    x, y, valid, dates, features = original._validate(dataset)
    target = waiting_second_moment(dataset)
    fingerprint = identity(dataset, x, y, valid, dates, features, target)
    digest = original._json_hash(fingerprint)
    output = original._output_directory(output_dir, fingerprint)
    predictions = np.full(valid.shape, np.nan, dtype=np.float32)
    manifest = {"identity": fingerprint, "identity_sha256": digest, "months": []}
    months = dates.astype("datetime64[M]")
    symbols = original._training_symbols(dataset, x.shape[2])
    for month in np.unique(months):
        month_days = np.flatnonzero(months == month)
        receipt_path = output / f"{month}.json" if output is not None else None
        if receipt_path is not None and receipt_path.exists():
            receipt = _resume_month(
                output, receipt_path, month_days, predictions, digest
            )
            manifest["months"].append(receipt)
            continue
        day, clock, stock, cutoff = training_rows(
            dates, valid, target, int(month_days[0]), symbols
        )
        distinct = np.unique(day)
        receipt = {
            "month": str(month),
            "fit_date": str(dates[month_days[0]]),
            "label_end_before": str(cutoff),
            "training_days": len(distinct),
            "training_rows": len(day),
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
                    target,
                    valid,
                    (day, clock, stock),
                    month_days,
                    month,
                    output,
                    predictions,
                )
            )
            if output is not None:
                receipt.update(
                    original._save_predictions(output, month, month_days, predictions)
                )
        manifest["months"].append(receipt)
        if output is not None:
            original._write_json(receipt_path, receipt)
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
    manifest["prediction_sha256"] = original._array_hash(predictions)
    if output is not None:
        original._write_json(output / "manifest.json", manifest)
    return predictions, manifest
