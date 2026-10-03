"""One volatility-conditioned nonlinear improvement over frozen suffix labels."""

import json
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import learned_entry_models as base
from backend.market import sequential_execution_models as teacher

POLICY = "normalized-nonlinear-continuation/1"
TEACHER_SHA = "21afa50d2d36c1f03c20fa50dd4c18b05538865559ee80f7bf7ea553373a4c00"
TRAIN_CLOCKS = (0, 3, 9, 19)


# Normalize by observed stock volatility and the remaining regular-session clock.
def scales(dataset):
    names = tuple(dataset["feature_names"])
    if "volatility_20" not in names:
        raise ValueError("Prior-only volatility_20 feature required")
    x, _, valid, _, _ = base._validate(dataset)
    vol = x[..., names.index("volatility_20")].astype(np.float64)
    remaining = np.sqrt(np.maximum(24 - np.arange(25), 0) / 26)
    values = vol * remaining[None, :, None]
    close = np.asarray(dataset["current_close"])
    if close.shape != valid.shape:
        raise ValueError("Aligned observed closes required")
    values[
        ~valid
        | ~np.isfinite(values)
        | (values <= 0)
        | ~np.isfinite(close)
        | (close <= 0)
    ] = np.nan
    return values


# Authenticate the original completed source, mature windows and held-fold labels.
def validate_teacher(directory, dataset):
    directory = Path(directory)
    if teacher._file_hash(directory / "manifest.json") != TEACHER_SHA:
        raise ValueError("Fixed original continuation manifest required")
    _, manifest = teacher.validate_saved(directory, dataset)
    return manifest


# Pin the new architecture, input units, source and immutable teacher provenance.
def identity(dataset, teacher_manifest):
    x, y, valid, dates, features = base._validate(dataset)
    result = base._identity(dataset, x, y, valid, dates, features, "boosting")
    root = Path(__file__).resolve().parents[2]
    result.update(
        policy=POLICY,
        train_clocks=TRAIN_CLOCKS,
        teacher_manifest_sha256=TEACHER_SHA,
        teacher_identity_sha256=teacher_manifest["identity_sha256"],
        normalized_source_sha256=teacher._file_hash(Path(__file__)),
        normalized_protocol_sha256=teacher._file_hash(
            root / "docs/research/normalized-continuation-plan-2026-10-03.md"
        ),
        normalization="prior_volatility20_times_sqrt_remaining24_minus_clock_over26",
        target="held_fold_stop_minus_suffix_execution_over_observed_close",
        estimator_heads=["buy", "sell"],
    )
    return json.loads(json.dumps(result))


# Train pooled side heads only on specified mature rows and known positive scales.
def fit_heads(dataset, days, targets):
    x, _, valid, _, _ = base._validate(dataset)
    days = np.asarray(days, dtype=np.int64)
    if (
        days.ndim != 1
        or not len(days)
        or np.any(days[1:] <= days[:-1])
        or np.any(days < 0)
        or np.any(days >= len(x))
        or np.shape(targets) != (len(days), 24, x.shape[2], 2)
    ):
        raise ValueError("Ordered training days and aligned held-fold targets required")
    scale = scales(dataset)[days, :24]
    clocks = np.isin(np.arange(24), TRAIN_CLOCKS)[None, :, None]
    stock = base._training_symbols(dataset, x.shape[2])[None, None, :]
    mask = valid[days, :24] & np.isfinite(scale) & clocks & stock
    heads, receipts = [], []
    with threadpool_limits(limits=2):
        for side in range(2):
            local, clock, name = np.nonzero(mask & np.isfinite(targets[..., side]))
            if not len(local):
                heads.append(None)
                receipts.append({"status": "no_finite_targets", "rows": 0})
                continue
            labels = targets[local, clock, name, side] / scale[local, clock, name]
            model = base._estimator("boosting")
            model.fit(x[days[local], clock, name].astype(np.float64), labels)
            heads.append(model)
            receipts.append(
                {
                    "status": "fitted",
                    "rows": len(local),
                    "training_days": len(np.unique(days[local])),
                    "row_days_sha256": base._array_hash(days[local]),
                    "row_clocks_sha256": base._array_hash(clock),
                    "row_stocks_sha256": base._array_hash(name),
                    "normalized_targets_sha256": base._array_hash(labels),
                }
            )
    return heads, receipts


# Forecast raw relative-price advantage from causal rows without reading outcomes.
def predict(heads, dataset, days):
    x, _, valid, _, _ = base._validate(dataset)
    days = np.asarray(days, dtype=np.int64)
    if days.ndim != 1 or np.any(days < 0) or np.any(days >= len(x)):
        raise ValueError("Valid scoring day indices required")
    if len(heads) != 2:
        raise ValueError("Exactly buy and sell heads required")
    scale = scales(dataset)[days]
    local, clock, stock = np.nonzero(valid[days] & np.isfinite(scale))
    result = np.full((len(days), 25, x.shape[2], 2), np.nan, dtype=np.float32)
    with threadpool_limits(limits=2):
        for side, model in enumerate(heads):
            if model is not None and len(local):
                values = model.predict(x[days[local], clock, stock].astype(np.float64))
                with np.errstate(over="ignore", invalid="ignore"):
                    values = (values * scale[local, clock, stock]).astype(np.float32)
                values[~np.isfinite(values)] = np.nan
                result[local, clock, stock, side] = values
    return result


# Restore only authenticated forecasts and fitted estimator bytes, without unpickling.
def resume(directory, receipt, days, digest, predictions):
    output = Path(directory)
    if receipt["identity_sha256"] != digest or receipt["score_days"] != days.tolist():
        raise ValueError("Saved monthly forecast identity or dates changed")
    expected_heads = (
        [i for i, head in enumerate(receipt["heads"]) if head["status"] == "fitted"]
        if receipt["status"] == "fitted"
        else []
    )
    if [m["head"] for m in receipt["models"]] != expected_heads:
        raise ValueError("Saved side heads changed")
    for model in receipt["models"]:
        path = output / model["file"]
        if (
            model["file"] != f"{receipt['month']}-head{model['head']}.joblib"
            or teacher._file_hash(path) != model["sha256"]
        ):
            raise ValueError("Saved estimator bytes changed")
    if receipt["forecast"]["file"] != f"{receipt['month']}-predictions.npz":
        raise ValueError("Saved forecast path changed")
    values = teacher._read_npz(
        output / receipt["forecast"]["file"], receipt["forecast"]
    )
    if (
        set(values) != {"days", "predictions"}
        or not np.array_equal(values["days"], days)
        or values["days"].dtype != np.int64
    ):
        raise ValueError("Saved forecast calendar changed")
    if (
        values["predictions"].shape != predictions[days].shape
        or values["predictions"].dtype != np.float32
    ):
        raise ValueError("Saved forecast shape or precision changed")
    if np.isinf(values["predictions"]).any():
        raise ValueError("Saved forecast contains infinity")
    predictions[days] = values["predictions"]


# Fit monthly policy improvements once using only the original audited suffix labels.
def walk_forward(dataset, teacher_directory, output_directory):
    teacher_directory, output = Path(teacher_directory), Path(output_directory)
    manifest = validate_teacher(teacher_directory, dataset)
    pinned = identity(dataset, manifest)
    digest = base._json_hash(pinned)
    base._output_directory(output, pinned)
    dates = np.asarray(dataset["dates"], dtype="datetime64[D]")
    predictions = np.full(np.shape(dataset["valid"]) + (2,), np.nan, np.float32)
    result = {"identity": pinned, "identity_sha256": digest, "months": []}
    for original in manifest["months"]:
        month = original["month"]
        score_days = np.flatnonzero(
            dates.astype("datetime64[M]") == np.datetime64(month)
        )
        train, cutoff = teacher.training_days(dates, int(score_days[0]))
        expected = {
            "month": month,
            "fit_date": str(dates[score_days[0]]),
            "label_end_before": str(cutoff),
            "training_days": len(train),
            "maximum_label_end": str(dates[train[-1] + 10]) if len(train) else None,
            "teacher_month_sha256": teacher._file_hash(
                teacher_directory / month / "receipt.json"
            ),
            "identity_sha256": digest,
            "score_days": score_days.tolist(),
        }
        path = output / f"{month}.json"
        if path.exists():
            receipt = json.loads(path.read_text())
            if any(receipt.get(key) != value for key, value in expected.items()):
                raise ValueError("Saved training window or teacher changed")
            if receipt.get("status") != original["status"]:
                raise ValueError("Saved fit status changed")
            resume(output, receipt, score_days, digest, predictions)
        else:
            receipt = {
                **expected,
                "status": "insufficient_mature_history",
                "models": [],
            }
            if original["status"] == "fitted":
                fit = original["fit"]
                arrays = teacher._read_npz(
                    teacher_directory / month / "models.npz", fit["bundle"]
                )
                heads, receipts = fit_heads(dataset, train, arrays["oof_targets"])
                predictions[score_days] = predict(heads, dataset, score_days)
                receipt.update(
                    status="fitted",
                    heads=receipts,
                    models=[
                        base._save_model(output, month, side, model)
                        for side, model in enumerate(heads)
                        if model is not None
                    ],
                )
            forecast_path = output / f"{month}-predictions.npz"
            arrays = {"days": score_days, "predictions": predictions[score_days]}
            teacher._save_npz(forecast_path, arrays)
            receipt["forecast"] = {
                "file": forecast_path.name,
                "sha256": teacher._file_hash(forecast_path),
                "arrays": {
                    name: base._array_hash(value) for name, value in arrays.items()
                },
            }
            base._write_json(path, receipt)
        result["months"].append(receipt)
        permitted = np.isfinite(scales(dataset)[score_days])
        if np.isfinite(predictions[score_days][~permitted]).any():
            raise ValueError(
                "Saved forecast violates observation or terminal eligibility"
            )
        base._write_json(output / "progress.json", result)
        print(json.dumps({"month": month, "status": receipt["status"]}), flush=True)
    path = output / "predictions.npz"
    teacher._save_npz(path, {"dates": dates, "predictions": predictions})
    result["forecast"] = {
        "file": path.name,
        "sha256": teacher._file_hash(path),
        "arrays": {
            "dates": base._array_hash(dates),
            "predictions": base._array_hash(predictions),
        },
    }
    base._write_json(output / "manifest.json", result)
    return predictions, result
