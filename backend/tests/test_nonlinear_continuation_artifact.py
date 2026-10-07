"""Actual numeric publication parity and corrupt/mismatched evidence rejection."""

import copy
import json

import numpy as np
import pytest

from backend.market import learned_entry_models as base
from backend.market import nonlinear_continuation_artifact as artifact
from backend.market import nonlinear_session_continuation as model
from backend.market import sequential_execution_models as storage
from backend.tests.test_nonlinear_session_continuation import _dataset, _march


# Fit real fixed estimators once with all twenty-one numeric inference columns.
@pytest.fixture
def fitted(monkeypatch):
    monkeypatch.setattr(model, "MIN_MATURE_SESSIONS", 8)
    data = _dataset()
    features = np.zeros((*data["X"].shape[:-1], 21), dtype=np.float32)
    features[..., :3] = data["X"]
    data["X"] = features
    data["feature_names"] += [f"causal_{index}" for index in range(3, 21)]
    index = _march(data)
    return data, model.fit_month(data, index), np.array([index, index + 1])


# Match saved inference to real sklearn predictions, including missing input routes.
def test_numeric_saved_parity_and_future_outcome_invariance(fitted, tmp_path):
    data, bundle, days = fitted
    data["X"][days[0], 2, 0, 1] = np.nan
    directory = tmp_path / "month"
    manifest, digest = artifact.publish(bundle, data, days, directory)
    loaded, saved = artifact.load(directory, data, manifest_sha256=digest)
    assert manifest == saved
    assert manifest["adoption_eligible"] is False
    expected = model.predict_month(bundle, data, days)
    np.testing.assert_allclose(model.predict_month(loaded, data, days), expected,
                               rtol=1e-13, atol=1e-15, equal_nan=True)
    changed = copy.deepcopy(data)
    changed["next_open"][:] = np.nan
    changed["y"][:] = 9999
    again, _ = artifact.load(directory, changed, manifest_sha256=digest)
    np.testing.assert_array_equal(model.predict_month(again, changed, days),
                                  model.predict_month(loaded, data, days))
    with pytest.raises(FileExistsError):
        artifact.publish(bundle, data, days, directory)


# Reject byte tampering, foreign paths, source changes and reordered ticker contracts.
@pytest.mark.parametrize("problem", [
    "digest", "head", "forecast", "path", "source", "names", "calendar",
    "self_consistent_wrong_forecast",
])
def test_saved_evidence_rejects_wrong_boundary(fitted, tmp_path, problem):
    data, bundle, days = fitted
    directory = tmp_path / "month"
    manifest, digest = artifact.publish(bundle, data, days, directory)
    if problem == "digest":
        digest = "0" * 64
    elif problem in ("head", "forecast"):
        path = directory / ("side-0.npz" if problem == "head" else "predictions.npz")
        with path.open("ab") as handle:
            handle.write(b"wrong original bytes")
    elif problem == "self_consistent_wrong_forecast":
        path = directory / "predictions.npz"
        with np.load(path, allow_pickle=False) as archive:
            arrays = {key: archive[key].copy() for key in archive.files}
        arrays["predictions"][:, :24] += 1
        storage._save_npz(path, arrays)
        manifest["forecast_sha256"] = storage._file_hash(path)
        manifest["prediction_array_sha256"] = base._array_hash(arrays["predictions"])
        (directory / "manifest.json").write_text(json.dumps(manifest))
        digest = storage._file_hash(directory / "manifest.json")
    elif problem in ("path", "source"):
        if problem == "path":
            manifest["heads"][0]["file"] = "../side-0.npz"
        else:
            manifest["sources"]["forward_execution.py"] = "0" * 64
        (directory / "manifest.json").write_text(json.dumps(manifest))
        digest = storage._file_hash(directory / "manifest.json")
    elif problem == "names":
        data["tickers"] = ("COHR", "AAOI", *data["tickers"][2:])
    else:
        data["dates"] += np.timedelta64(1, "D")
    with pytest.raises(ValueError, match="required|differs|identity"):
        artifact.load(directory, data, manifest_sha256=digest)


# Preserve unavailable month readiness without manufacturing model heads or forecasts.
def test_unready_month_can_publish_only_unavailable_evidence(tmp_path):
    data = _dataset()
    data["X"] = np.repeat(data["X"][..., :1], 21, axis=-1)
    data["feature_names"] = ["volatility_20", *[f"causal_{i}" for i in range(20)]]
    index = _march(data)
    bundle = model.fit_month(data, index)
    manifest, digest = artifact.publish(
        bundle, data, np.array([index]), tmp_path / "month"
    )
    loaded, _ = artifact.load(tmp_path / "month", data, manifest_sha256=digest)
    assert manifest["heads"] == [None, None]
    assert loaded["receipt"]["status"] == "insufficient_mature_history"
    scored = model.predict_month(loaded, data, np.array([index]))
    assert base._array_hash(scored) == manifest["prediction_array_sha256"]
