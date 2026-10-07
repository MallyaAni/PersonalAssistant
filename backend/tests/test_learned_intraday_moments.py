"""Duration-matched actual model fits and authenticated monthly artifacts."""

import json

import numpy as np
import pytest

from backend.market import learned_entry_models as original
from backend.market import learned_intraday_moments as intraday


# Generate enough mature synthetic sessions for the unchanged pooled estimators.
def _dataset(days=631, start="2024-05-01", stocks=2):
    dates = np.busday_offset(start, np.arange(days), roll="forward").astype(
        "datetime64[D]"
    )
    rng = np.random.default_rng(190)
    x = rng.uniform(-1, 1, size=(days, 25, stocks, 2)).astype(np.float32)
    labels = np.full(x.shape[:3] + (3,), np.nan, dtype=np.float32)
    labels[..., 2] = 0.004 * x[..., 0]
    labels[:, 24, :, 2] = 0.5
    labels[-10:, :, :, 2] = np.nan
    return {
        "X": x,
        "y": labels,
        "valid": np.ones(x.shape[:3], dtype=bool),
        "dates": dates,
        "feature_names": ["waiting_feature", "noise"],
        "training_symbols": np.ones(stocks, dtype=bool),
        "provenance": {"fixture": "synthetic"},
    }


# Verify actual UTC elapsed time through weekend and daylight-saving changes.
def test_elapsed_minutes_are_calendar_metadata_not_future_price_filters():
    for days, expected in (
        (["2026-03-06", "2026-03-09"], 3900),
        (["2026-10-30", "2026-11-02"], 4020),
        (["2026-06-05", "2026-06-08"], 3960),
        (["2026-06-08", "2026-06-09"], 1080),
    ):
        elapsed = intraday.waiting_elapsed_minutes(
            np.array(days, dtype="datetime64[D]")
        )
        assert np.all(elapsed[:, :24] == 15)
        assert elapsed[0, 24] == expected
        assert np.isnan(elapsed[-1, 24])


# Restrict the unchanged clock list by duration while enforcing endpoint maturity.
def test_training_rows_exclude_overnight_and_keep_conservative_purge():
    data = _dataset()
    elapsed = intraday.waiting_elapsed_minutes(data["dates"])
    mean, _ = intraday.targets(data, elapsed)
    day, clock, _, cutoff = intraday.training_rows(
        data["dates"], data["valid"], mean, elapsed, 600, data["training_symbols"]
    )
    assert set(clock) == {0, 3, 9, 19}
    assert not np.any(clock == 24)
    assert np.all(data["dates"][day + 10] < cutoff)
    assert len(np.unique(day)) >= 504


# Fit all three actual heads and prove overnight mutations cannot change any prediction.
def test_real_models_are_overnight_invariant_and_score_missing_outcomes(tmp_path):
    data = _dataset()
    changed = {**data, "y": data["y"].copy()}
    changed["y"][:, 24, :, 2] = -1000.0
    means, risk, manifest = intraday.walk_forward(data, tmp_path / "first")
    other, other_risk, other_manifest = intraday.walk_forward(
        changed, tmp_path / "second"
    )
    for method in means:
        np.testing.assert_array_equal(means[method], other[method])
        assert np.isfinite(means[method][-10:, :23, :, 2]).all()
        assert np.isnan(means[method][..., :2]).all()
        assert np.isnan(means[method][:, 23:]).all()
    np.testing.assert_array_equal(risk, other_risk)
    assert np.isfinite(risk[-10:, :23]).all()
    assert np.isnan(risk[:, 23:]).all()
    first_models = [month.get("models") for month in manifest["months"]]
    second_models = [month.get("models") for month in other_manifest["months"]]
    assert first_models == second_models
    for month in manifest["months"]:
        if month["status"] == "fitted":
            assert month["training_days"] >= 504
            assert month["training_clocks"] == [0, 3, 9, 19]
            assert month["ridge_certificate"]["normalized_gradient"] <= 1e-8
    assert (
        manifest["identity"]["mean_target_sha256"]
        == other_manifest["identity"]["mean_target_sha256"]
    )
    assert (
        manifest["identity"]["arrays"]["y"] != other_manifest["identity"]["arrays"]["y"]
    )
    resumed, resumed_risk, saved = intraday.walk_forward(data, tmp_path / "first")
    for method in means:
        np.testing.assert_array_equal(resumed[method], means[method])
    np.testing.assert_array_equal(resumed_risk, risk)
    assert saved["prediction_sha256"] == manifest["prediction_sha256"]
    checked, checked_risk, checked_manifest = intraday.validate_saved(
        tmp_path / "first", data
    )
    for method in means:
        np.testing.assert_array_equal(checked[method], means[method])
    np.testing.assert_array_equal(checked_risk, risk)
    assert checked_manifest["identity_sha256"] == manifest["identity_sha256"]
    with np.load(tmp_path / "first/predictions.npz", allow_pickle=False) as archive:
        np.testing.assert_array_equal(archive["means_boosting"], means["boosting"])
        np.testing.assert_array_equal(archive["risk"], risk)


# Keep hidden endpoint outcomes unavailable during every holdout-month refit.
def test_real_holdout_labels_are_hidden_for_both_means_and_risk():
    data = _dataset()
    changed = {**data, "y": data["y"].copy()}
    endpoints = np.full(len(data["dates"]), np.datetime64("NaT", "D"))
    endpoints[:-10] = data["dates"][10:]
    changed["y"][endpoints >= original.HOLDOUT_START, ..., 2] = 100.0
    means, risk, manifest = intraday.walk_forward(data)
    other, other_risk, _ = intraday.walk_forward(changed)
    months = data["dates"].astype("datetime64[M]")
    keep = (months == np.datetime64("2026-08")) | (months == np.datetime64("2026-09"))
    for method in means:
        np.testing.assert_array_equal(means[method][keep], other[method][keep])
    np.testing.assert_array_equal(risk[keep], other_risk[keep])
    receipts = {m["month"]: m for m in manifest["months"]}
    assert receipts["2026-08"]["label_end_before"] == "2026-08-03"
    assert receipts["2026-09"]["label_end_before"] == "2026-08-17"


# Prove the Ridge certificate detects a broken coefficient after a real fit.
def test_actual_ridge_normal_equations_reject_bad_coefficients():
    data = _dataset(days=70, stocks=20)
    x, y = (
        data["X"][:40, :23].reshape(-1, 2).astype(float),
        data["y"][:40, :23, :, 2].ravel().astype(float),
    )
    model = original._estimator("ridge").fit(x, y)
    assert intraday.certify_ridge(model, x, y)["certified"]
    model[-1].coef_[0] += 0.01
    with pytest.raises(RuntimeError, match="normal-equation certificate"):
        intraday.certify_ridge(model, x, y)


# Detect changed original inputs, model bytes and duration semantics before resume.
def test_resume_requires_exact_inputs_schema_and_artifact_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(original, "MIN_TRAIN_DAYS", 8)
    data = _dataset(days=70, start="2026-05-01", stocks=20)
    _, _, manifest = intraday.walk_forward(data, tmp_path)
    altered = {**data, "y": data["y"].copy()}
    altered["y"][0, 24, 0, 2] += 1
    with pytest.raises(ValueError, match="Saved run differs"):
        intraday.walk_forward(altered, tmp_path)
    month = next(m for m in manifest["months"] if m["status"] == "fitted")
    path = tmp_path / (month["month"] + ".json")
    receipt = json.loads(path.read_text())
    receipt["target_schema"]["elapsed_minutes"] = 1080
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="schema or identity"):
        intraday.walk_forward(data, tmp_path)
    path.write_text(json.dumps(month))
    archive = tmp_path / month["prediction_file"]
    archive.write_bytes(archive.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="forecast hash mismatch"):
        intraday.walk_forward(data, tmp_path)


# Readback refuses altered maturity metadata or global forecast bytes before evaluation.
def test_complete_artifact_validation_is_source_and_maturity_bound(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(original, "MIN_TRAIN_DAYS", 8)
    data = _dataset(days=70, start="2026-05-01", stocks=20)
    _, _, manifest = intraday.walk_forward(data, tmp_path)
    changed = {**data, "provenance": {"fixture": "foreign-source"}}
    with pytest.raises(ValueError, match="complete identity differs"):
        intraday.validate_saved(tmp_path, changed)
    path = tmp_path / "manifest.json"
    altered = json.loads(path.read_text())
    fitted = next(m for m in altered["months"] if m["status"] == "fitted")
    fitted["maximum_label_end"] = "2099-01-01"
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="schedule or maturity"):
        intraday.validate_saved(tmp_path, data)
    path.write_text(json.dumps(manifest))
    archive = tmp_path / "predictions.npz"
    archive.write_bytes(archive.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="complete prediction bytes differ"):
        intraday.validate_saved(tmp_path, data)
