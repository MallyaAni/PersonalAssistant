"""Authenticated numeric publication of research continuation heads, without pickle.

A historical fit date is not a real publication timestamp or adoption approval.
The caller must supply an independently trusted manifest digest before loading.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

from backend.market import forward_execution as numeric
from backend.market import learned_entry_models as base
from backend.market import nonlinear_session_continuation as model
from backend.market import sequential_execution_models as storage

SCHEMA = "nonlinear-continuation-numeric/1"


# Identify exact inference code so changed numeric arithmetic cannot reuse approval.
def _sources():
    from backend.market import direct_daily_arithmetic

    paths = (Path(__file__), Path(model.__file__), Path(numeric.__file__),
             Path(direct_daily_arithmetic.__file__), Path(base.__file__),
             Path(storage.__file__), Path(model.normalized.__file__),
             Path(__file__).resolve().parents[2] / model.PROTOCOL)
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


# Export fixed fitted trees once and verify their actual in-memory scoring parity.
def publish(bundle, dataset, days, directory):
    days = np.asarray(days)
    expected = model.predict_month(bundle, dataset, days)
    sources = _sources()
    receipt = bundle["receipt"]
    if receipt["source_sha256"] != sources[Path(model.__file__).name] or (
        receipt["protocol_sha256"] != sources[Path(model.PROTOCOL).name]
        or any(sources.get(name) != digest
               for name, digest in receipt["dependencies"].items())
    ):
        raise ValueError("Original fitted continuation source differs")
    if np.shape(dataset["X"])[-1] != 21:
        raise ValueError("Original twenty-one continuation features required")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    numeric_heads, records = [], []
    for side, head in enumerate(bundle["heads"]):
        if head is None:
            numeric_heads.append(None)
            records.append(None)
            continue
        if model._model_hash(head) != bundle["receipt"]["heads"][side]["model_sha256"]:
            raise ValueError("Fitted continuation model identity differs")
        arrays, identity = numeric._snapshot(head)
        numeric_heads.append(numeric._head(arrays, identity))
        path = directory / f"side-{side}.npz"
        storage._save_npz(path, arrays)
        records.append({"file": path.name, "sha256": storage._file_hash(path),
                        "identity": identity})
    portable = {**bundle, "heads": numeric_heads}
    actual = model.predict_month(portable, dataset, days)
    np.testing.assert_allclose(actual, expected, rtol=1e-13, atol=1e-15, equal_nan=True)
    arrays = {"days": days, "predictions": actual}
    forecast = directory / "predictions.npz"
    storage._save_npz(forecast, arrays)
    manifest = {
        "schema": SCHEMA, "policy": model.POLICY, "sources": sources,
        "fit_index": bundle["fit_index"], "fit": bundle["receipt"],
        "heads": records, "days": days.tolist(), "adoption_eligible": False,
        "calendar_sha256": base._array_hash(np.asarray(dataset["dates"])),
        "forecast_sha256": storage._file_hash(forecast),
        "prediction_array_sha256": base._array_hash(actual),
        "parity": "real_estimator_and_numeric_reader_match",
    }
    manifest = json.loads(json.dumps(manifest, allow_nan=False))
    base._write_json(directory / "manifest.json", manifest)
    return manifest, storage._file_hash(directory / "manifest.json")


# Authenticate complete non-executable artifacts before constructing any scorer.
def load(directory, dataset, *, manifest_sha256):
    directory = Path(directory)
    path = directory / "manifest.json"
    if not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64 or (
        storage._file_hash(path) != manifest_sha256
    ):
        raise ValueError("Trusted continuation manifest hash required")
    manifest = json.loads(path.read_text())
    if (manifest["schema"] != SCHEMA or manifest["policy"] != model.POLICY
        or manifest["sources"] != _sources()
        or manifest["adoption_eligible"] is not False
        or manifest["calendar_sha256"] != base._array_hash(np.asarray(dataset["dates"]))
        or len(manifest["heads"]) != 2):
        raise ValueError("Continuation source or calendar identity differs")
    heads = []
    for side, record in enumerate(manifest["heads"]):
        if record is None:
            heads.append(None)
            continue
        if record["file"] != f"side-{side}.npz":
            raise ValueError("Fixed continuation head filename required")
        artifact = directory / record["file"]
        if storage._file_hash(artifact) != record["sha256"]:
            raise ValueError("Continuation numeric head hash differs")
        with np.load(artifact, allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}
        heads.append(numeric._head(arrays, record["identity"]))
    fit = {**manifest["fit"], "tickers": tuple(manifest["fit"]["tickers"])}
    bundle = {"heads": heads, "receipt": fit,
              "fit_index": manifest["fit_index"]}
    forecast = directory / "predictions.npz"
    if storage._file_hash(forecast) != manifest["forecast_sha256"]:
        raise ValueError("Continuation forecast hash differs")
    actual = model.predict_month(
        bundle, dataset, np.asarray(manifest["days"], dtype=np.int64)
    )
    with np.load(forecast, allow_pickle=False) as archive:
        if set(archive.files) != {"days", "predictions"} or (
            archive["days"].tolist() != manifest["days"]
            or base._array_hash(archive["predictions"])
            != manifest["prediction_array_sha256"]
        ):
            raise ValueError("Continuation saved prediction identity differs")
        if not np.array_equal(actual, archive["predictions"], equal_nan=True):
            raise ValueError("Continuation saved forecast differs from numeric model")
    return bundle, manifest
