"""Monthly original-bank fitting with immutable numeric checkpoints, research only."""

import json
from pathlib import Path

import numpy as np

from backend.cli.market_learned_entry import sha256
from backend.market import learned_entry_data as features
from backend.market import learned_entry_models as base
from backend.market import nonlinear_continuation_artifact as artifact
from backend.market import nonlinear_session_continuation as model
from backend.market import sequential_execution_models as storage

ARCHIVE_SHA = "c759ecb607e755631dacc0d28a147511a1eaa7e54e3cbcb23bdff4aafe8b76bf"
RECEIPT_SHA = "909065342925a972a45e2f1d9baf2e34031528d980bd5b43a3428671a4f80d8c"
PROTOCOL = "docs/research/nonlinear-continuation-funded-screen-plan-2026-10-07.md"


# Restore only the independently authenticated original bank, without source writes.
def load_original(directory):
    directory = Path(directory)
    if sha256(directory / "prepared.npz") != ARCHIVE_SHA or (
        sha256(directory / "prepared.json") != RECEIPT_SHA
    ):
        raise ValueError("Original continuation bank bytes required")
    receipt = json.loads((directory / "prepared.json").read_text())
    if receipt["identity"]["feature_source_sha256"] != sha256(features.__file__):
        raise ValueError("Original continuation feature source differs")
    with np.load(directory / "prepared.npz", allow_pickle=False) as archive:
        dataset = {key: archive[key] for key in archive.files}
    for key in ("tickers", "feature_names"):
        dataset[key] = tuple(dataset[key].tolist())
    dataset["training_symbols"] = np.array([
        name not in ("SPY", "QQQ") for name in dataset["tickers"]
    ])
    if dataset["X"].shape != (2953, 25, 96, 21) or (
        dataset["feature_names"] != tuple(features.FEATURE_NAMES)
    ):
        raise ValueError("Original continuation bank representation required")
    model._contract(dataset)
    return dataset, {"archive_sha256": ARCHIVE_SHA, "receipt_sha256": RECEIPT_SHA}


# Bind consumed arrays and executable dependencies before creating a private study.
def identity(dataset, input_identity):
    model._contract(dataset)
    storage._inputs(dataset)
    if not isinstance(input_identity, dict) or not input_identity or any(
        not isinstance(value, str) or len(value) != 64
        for value in input_identity.values()
    ):
        raise ValueError("Explicit authenticated input hashes required")
    root = Path(__file__).resolve().parents[2]
    return {
        "policy": model.POLICY, "inputs": input_identity,
        "sources": {**artifact._sources(), Path(__file__).name: sha256(__file__),
                    Path(PROTOCOL).name: sha256(root / PROTOCOL)},
        "arrays": {key: base._array_hash(np.asarray(dataset[key])) for key in (
            "X", "valid", "dates", "current_close", "next_open", "training_symbols"
        )},
        "features": list(dataset["feature_names"]),
        "tickers": list(dataset["tickers"]),
        "minimum_mature_sessions": model.MIN_MATURE_SESSIONS,
        "adoption_eligible": False,
    }


# Reuse only trusted complete monthly publications, never a partial fitted draft.
def _saved_month(folder, dataset, expected):
    checkpoint = json.loads((folder / "checkpoint.json").read_text())
    if any(checkpoint.get(key) != value for key, value in expected.items()):
        raise ValueError("Original continuation monthly checkpoint differs")
    _, receipt = artifact.load(
        folder, dataset, manifest_sha256=checkpoint["manifest_sha256"]
    )
    with np.load(folder / "predictions.npz", allow_pickle=False) as archive:
        predictions = archive["predictions"].copy()
    return checkpoint, receipt, predictions


# Fit each supplied source month once and preserve every missing forecast explicitly.
def walk_forward(dataset, directory, *, input_identity):
    pinned = identity(dataset, input_identity)
    directory = base._output_directory(Path(directory), pinned)
    dates = np.asarray(dataset["dates"], dtype="datetime64[D]")
    predictions = np.full(np.shape(dataset["valid"]) + (2,), np.nan)
    result = {"identity": pinned, "identity_sha256": base._json_hash(pinned),
              "months": [], "adoption_eligible": False}
    for month in np.unique(dates.astype("datetime64[M]")):
        days = np.flatnonzero(dates.astype("datetime64[M]") == month)
        expected = {"month": str(month), "fit_index": int(days[0]),
                    "identity_sha256": result["identity_sha256"]}
        folder = directory / str(month)
        if folder.exists():
            if not (folder / "checkpoint.json").exists():
                raise ValueError("Incomplete continuation month retained; no refit")
            checkpoint, receipt, values = _saved_month(folder, dataset, expected)
        else:
            fitted = model.fit_month(dataset, int(days[0]))
            receipt, digest = artifact.publish(fitted, dataset, days, folder)
            checkpoint = {**expected, "manifest_sha256": digest}
            base._write_json(folder / "checkpoint.json", checkpoint)
            _, receipt, values = _saved_month(folder, dataset, expected)
        predictions[days] = values
        result["months"].append({**checkpoint, "status": receipt["fit"]["status"]})
        base._write_json(directory / "progress.json", result)
        print(json.dumps(result["months"][-1]), flush=True)
    path = directory / "predictions.npz"
    storage._save_npz(path, {"dates": dates, "predictions": predictions})
    result["forecast_sha256"] = sha256(path)
    result["prediction_array_sha256"] = base._array_hash(predictions)
    base._write_json(directory / "manifest.json", result)
    return predictions, result
