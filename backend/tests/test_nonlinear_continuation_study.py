"""Actual monthly fits, immutable reuse and original bank admission boundaries."""

import copy
import json

import numpy as np
import pytest

from backend.market import nonlinear_continuation_study as study
from backend.market import nonlinear_session_continuation as model
from backend.tests.test_nonlinear_session_continuation import _dataset


# Keep the source calendar and real trees while shortening only synthetic readiness.
@pytest.fixture
def data(monkeypatch):
    monkeypatch.setattr(model, "MIN_MATURE_SESSIONS", 8)
    result = _dataset()
    x = np.zeros((*result["X"].shape[:-1], 21), dtype=np.float32)
    x[..., :3] = result["X"]
    result["X"] = x
    result["feature_names"] += [f"causal_{index}" for index in range(3, 21)]
    return result


# Resume every verified month without refitting or using scoring outcome values.
def test_all_months_and_saved_resume_use_real_numeric_models(
    data, tmp_path, monkeypatch
):
    identity = {"synthetic_archive_sha256": "1" * 64}
    values, manifest = study.walk_forward(
        data, tmp_path / "study", input_identity=identity
    )
    assert len(manifest["months"]) == 5
    assert manifest["months"][0]["status"] == "insufficient_mature_history"
    assert np.isnan(values[:, 24]).all()
    assert np.isfinite(values[data["dates"] >= np.datetime64("2026-03-02"), :24]).all()

    # Fail if a completed checkpoint ever starts fitting the same model again.
    def no_refit(*args, **kwargs):
        raise AssertionError("A completed continuation month was fitted again")

    monkeypatch.setattr(model, "fit_month", no_refit)
    again, restored = study.walk_forward(
        data, tmp_path / "study", input_identity=identity
    )
    np.testing.assert_array_equal(values, again)
    assert manifest == restored


# Reject altered original observations and a partial checkpoint instead of refitting.
def test_changed_inputs_and_incomplete_month_are_not_selected_replacements(
    data, tmp_path
):
    identity = {"synthetic_archive_sha256": "1" * 64}
    study.walk_forward(data, tmp_path / "study", input_identity=identity)
    changed = copy.deepcopy(data)
    changed["X"][0, 0, 0, 0] += 1
    with pytest.raises(ValueError, match="Saved run differs"):
        study.walk_forward(changed, tmp_path / "study", input_identity=identity)
    (tmp_path / "study/2026-03/checkpoint.json").unlink()
    with pytest.raises(ValueError, match="Incomplete continuation month"):
        study.walk_forward(data, tmp_path / "study", input_identity=identity)


# Refuse fake original evidence before any prepared archive may be decoded or written.
def test_original_loader_rejects_changed_bytes(tmp_path):
    (tmp_path / "prepared.npz").write_bytes(b"not original")
    (tmp_path / "prepared.json").write_text(json.dumps({"adoption_eligible": False}))
    with pytest.raises(ValueError, match="Original continuation bank bytes"):
        study.load_original(tmp_path)
