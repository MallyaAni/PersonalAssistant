"""Fixed causal monthly models for the preregistered learned entry study."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

TRAIN_CLOCKS = (0, 3, 9, 19, 24)
MIN_TRAIN_DAYS = 504
MAX_TRAIN_DAYS = 756
LABEL_SESSIONS = 10
HOLDOUT_START = np.datetime64("2026-08-17", "D")
MODEL_CONFIG = {
    "boosting": {
        "max_iter": 64,
        "max_leaf_nodes": 15,
        "learning_rate": 0.05,
        "min_samples_leaf": 200,
        "early_stopping": False,
        "random_state": 0,
    },
    "ridge": {"alpha": 1.0, "solver": "cholesky"},
}


# Hash array bytes and their shape without serializing large matrices as JSON.
def _array_hash(array):
    value = np.asarray(array)
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode())
    digest.update(json.dumps(value.shape).encode())
    for chunk in value:
        digest.update(np.ascontiguousarray(chunk).tobytes())
    return digest.hexdigest()


# Produce stable identifiers for configuration and artifact receipts.
def _json_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


# Publish a complete receipt atomically so interruption never appears complete.
def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    os.replace(temporary, path)


# Validate the common dataset contract before training or loading cached predictions.
def _validate(dataset):
    x = np.asarray(dataset["X"])
    y = np.asarray(dataset["y"])
    valid = np.asarray(dataset["valid"])
    dates = np.asarray(dataset["dates"], dtype="datetime64[D]")
    features = list(dataset["feature_names"])
    if x.ndim != 4 or x.shape[1] != 25 or y.shape != x.shape[:3] + (3,):
        raise ValueError("Expected X(D,25,S,F) and y(D,25,S,3)")
    if valid.dtype != bool or valid.shape != x.shape[:3]:
        raise ValueError("Expected boolean prediction eligibility(D,25,S)")
    _training_symbols(dataset, x.shape[2])
    if (
        len(dates) != len(x)
        or np.any(np.isnat(dates))
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError("Dates must be unique chronological exchange sessions")
    if len(features) != x.shape[-1] or len(set(features)) != len(features):
        raise ValueError("Feature names must uniquely identify every input column")
    if "label_end_dates" in dataset:
        expected = np.full(len(dates), np.datetime64("NaT", "D"))
        expected[:-LABEL_SESSIONS] = dates[LABEL_SESSIONS:]
        supplied = np.asarray(dataset["label_end_dates"], dtype="datetime64[D]")
        if supplied.shape != expected.shape or not np.array_equal(
            supplied.view("i8"), expected.view("i8")
        ):
            raise ValueError(
                "Label endpoints must match the supplied ten-session calendar"
            )
    # Unknown grades remain missing features; infinite values are invalid inputs.
    for day in range(len(x)):
        if np.isinf(x[day][valid[day]]).any():
            raise ValueError(
                "Valid prediction rows cannot have infinite causal features"
            )
    return x, y, valid, dates, features


# Validate the explicitly declared training book independently of scoring eligibility.
def _training_symbols(dataset, stocks):
    mask = np.asarray(dataset.get("training_symbols", np.ones(stocks, dtype=bool)))
    if mask.dtype != bool or mask.shape != (stocks,) or not mask.any():
        raise ValueError("training_symbols must be boolean(S) with a nonempty book")
    return mask


# Select mature training rows identically for all heads and both methods.
def training_rows(dates, valid, y, fit_index, training_symbols=None):
    fit_date = dates[fit_index]
    cutoff = min(fit_date, HOLDOUT_START) if fit_date >= HOLDOUT_START else fit_date
    days = np.arange(max(0, fit_index - MAX_TRAIN_DAYS), fit_index)
    endpoint = days + LABEL_SESSIONS
    mature = endpoint < len(dates)
    days = days[mature]
    endpoint = endpoint[mature]
    days = days[dates[endpoint] < cutoff]
    clocks = np.asarray(TRAIN_CLOCKS)
    mask = valid[days][:, clocks] & np.isfinite(y[days][:, clocks]).all(axis=-1)
    if training_symbols is not None:
        mask &= training_symbols
    local_day, local_clock, stock = np.nonzero(mask)
    row_days = days[local_day]
    return row_days, clocks[local_clock], stock, cutoff


# Build the preregistered estimator without examining labels or tuning parameters.
def _estimator(method):
    if method == "boosting":
        from sklearn.ensemble import HistGradientBoostingRegressor

        return HistGradientBoostingRegressor(**MODEL_CONFIG[method])
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
        StandardScaler(),
        Ridge(**MODEL_CONFIG[method]),
    )


# Identify exact model code, protocols, dependency versions and supplied data.
def _identity(dataset, x, y, valid, dates, features, method):
    import scipy
    import sklearn

    root = Path(__file__).resolve().parents[2]
    protocols = [root / "docs/research/learned-entry-risk-plan-2026-10-02.md"]
    if method == "ridge":
        protocols.append(root / "docs/research/learned-linear-plan-2026-10-02.md")
    return {
        "method": method,
        "config": MODEL_CONFIG[method],
        "train_clocks": TRAIN_CLOCKS,
        "minimum_days": MIN_TRAIN_DAYS,
        "maximum_days": MAX_TRAIN_DAYS,
        "label_sessions": LABEL_SESSIONS,
        "holdout_label_end_before": str(HOLDOUT_START),
        "model_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": [
            hashlib.sha256(p.read_bytes()).hexdigest() for p in protocols
        ],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "sklearn": sklearn.__version__,
        "feature_names": features,
        "feature_hash": _json_hash(features),
        "training_symbols_sha256": _array_hash(_training_symbols(dataset, x.shape[2])),
        "arrays": {
            "X": _array_hash(x),
            "y": _array_hash(y),
            "valid": _array_hash(valid),
            "dates": _array_hash(dates),
        },
        "source_provenance": dataset.get("provenance", {}),
    }


# Establish resumable output with an exact immutable run identity.
def _output_directory(output_dir, identity):
    output = Path(output_dir) if output_dir is not None else None
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        identity_path = output / "identity.json"
        if identity_path.exists():
            if json.loads(identity_path.read_text()) != json.loads(
                json.dumps(identity)
            ):
                raise ValueError(
                    "Saved run differs from exact data, protocol, source or config"
                )
        else:
            _write_json(identity_path, identity)
    return output


# Verify completed artifacts without unpickling estimator objects.
def _resume_month(output, receipt_path, month_days, predictions, identity_hash):
    receipt = json.loads(receipt_path.read_text())
    if receipt["identity_sha256"] != identity_hash:
        raise ValueError("Monthly receipt identity mismatch")
    if receipt["status"] == "insufficient_mature_history":
        return receipt
    if receipt["status"] != "fitted":
        raise ValueError("Unknown monthly receipt status")
    artifact = output / receipt["prediction_file"]
    if (
        hashlib.sha256(artifact.read_bytes()).hexdigest()
        != receipt["prediction_sha256"]
    ):
        raise ValueError("Monthly prediction artifact hash mismatch")
    for model in receipt["models"]:
        path = output / model["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != model["sha256"]:
            raise ValueError("Monthly model artifact hash mismatch")
    with np.load(artifact, allow_pickle=False) as saved:
        if not np.array_equal(saved["days"], month_days):
            raise ValueError("Saved month membership mismatch")
        values = saved["predictions"]
        if values.shape != predictions[month_days].shape:
            raise ValueError("Saved prediction shape mismatch")
        predictions[month_days] = values
    return receipt


# Save a fitted estimator and hash without loading external model pickles.
def _save_model(output, month, head, model):
    import joblib

    filename = f"{month}-head{head}.joblib"
    temporary = output / (filename + ".tmp")
    joblib.dump(model, temporary, compress=0)
    os.replace(temporary, output / filename)
    return {
        "head": head,
        "file": filename,
        "sha256": hashlib.sha256((output / filename).read_bytes()).hexdigest(),
    }


# Fit three real heads and score valid rows independently of unknown future labels.
def _fit_month(
    x, y, valid, row_indices, month_days, month, method, output, predictions
):
    from threadpoolctl import threadpool_limits

    day, clock, stock = row_indices
    train_x = x[day, clock, stock]
    train_y = y[day, clock, stock]
    local_day, score_clock, score_stock = np.nonzero(valid[month_days])
    score_day = month_days[local_day]
    score_x = x[score_day, score_clock, score_stock]
    models = []
    with threadpool_limits(limits=2):
        for head in range(3):
            model = _estimator(method)
            model.fit(train_x, train_y[:, head])
            if len(score_x):
                predictions[score_day, score_clock, score_stock, head] = model.predict(
                    score_x
                )
            if output is not None:
                models.append(_save_model(output, month, head, model))
    return {"status": "fitted", "prediction_rows": len(score_day), "models": models}


# Publish prediction bytes before the corresponding completed receipt.
def _save_predictions(output, month, month_days, predictions):
    filename = f"{month}-predictions.npz"
    temporary = output / (filename + ".tmp")
    with temporary.open("wb") as handle:
        np.savez(handle, days=month_days, predictions=predictions[month_days])
    os.replace(temporary, output / filename)
    return {
        "prediction_file": filename,
        "prediction_sha256": hashlib.sha256(
            (output / filename).read_bytes()
        ).hexdigest(),
    }


# Fit mature history monthly and score eligible rows independently of future labels.
def walk_forward(dataset, output_dir=None, method="boosting"):
    if method not in MODEL_CONFIG:
        raise ValueError("Method must be boosting or ridge")
    x, y, valid, dates, features = _validate(dataset)
    identity = _identity(dataset, x, y, valid, dates, features, method)
    identity_hash = _json_hash(identity)
    output = _output_directory(output_dir, identity)
    predictions = np.full(y.shape, np.nan, dtype=np.float32)
    manifest = {"identity": identity, "identity_sha256": identity_hash, "months": []}
    months = dates.astype("datetime64[M]")
    for month in np.unique(months):
        month_days = np.flatnonzero(months == month)
        fit_index = int(month_days[0])
        receipt_path = output / f"{month}.json" if output else None
        if receipt_path is not None and receipt_path.exists():
            receipt = _resume_month(
                output, receipt_path, month_days, predictions, identity_hash
            )
            manifest["months"].append(receipt)
            continue
        day, clock, stock, cutoff = training_rows(
            dates, valid, y, fit_index, _training_symbols(dataset, x.shape[2])
        )
        distinct = np.unique(day)
        receipt = {
            "month": str(month),
            "fit_date": str(dates[fit_index]),
            "label_end_before": str(cutoff),
            "training_days": len(distinct),
            "training_rows": len(day),
            "identity_sha256": identity_hash,
            "status": "insufficient_mature_history",
        }
        if len(distinct):
            receipt.update(
                train_first=str(dates[distinct[0]]),
                train_last=str(dates[distinct[-1]]),
                maximum_label_end=str(dates[day.max() + LABEL_SESSIONS]),
            )
        if len(distinct) >= MIN_TRAIN_DAYS:
            receipt.update(
                _fit_month(
                    x,
                    y,
                    valid,
                    (day, clock, stock),
                    month_days,
                    month,
                    method,
                    output,
                    predictions,
                )
            )
            if output is not None:
                receipt.update(
                    _save_predictions(output, month, month_days, predictions)
                )
        manifest["months"].append(receipt)
        if output is not None:
            _write_json(receipt_path, receipt)
            _write_json(output / "progress.json", manifest)
        print(
            json.dumps(
                {
                    key: receipt[key]
                    for key in ("month", "status", "training_days", "training_rows")
                }
            ),
            flush=True,
        )
    manifest["prediction_sha256"] = _array_hash(predictions)
    if output is not None:
        _write_json(output / "manifest.json", manifest)
    return predictions, manifest
