"""Properties of real monthly estimators and their temporal artifact contract."""

import json

import numpy as np
import pytest

from backend.market import learned_entry_models as models


# Create complete synthetic exchange sessions with predictable, nonconstant labels.
def _dataset(days=70, start="2026-05-01"):
    dates = np.busday_offset(start, np.arange(days), roll="forward").astype(
        "datetime64[D]"
    )
    rng = np.random.default_rng(29)
    x = rng.normal(size=(days, 25, 20, 2)).astype(np.float32)
    y = np.stack(
        (0.05 * x[..., 0], 0.005 + 0.01 * x[..., 0] ** 2, 0.01 * x[..., 1]), axis=-1
    ).astype(np.float32)
    y[-10:] = np.nan
    return {
        "X": x,
        "y": y,
        "valid": np.ones(x.shape[:3], dtype=bool),
        "dates": dates,
        "feature_names": ["return", "waiting"],
        "provenance": {"source_sha256": "synthetic-only"},
    }


# Require strict endpoint maturity, declared clocks and the fixed history window.
def test_training_rows_purge_endpoints_and_use_fixed_clocks():
    data = _dataset(days=1000, start="2021-01-04")
    day, clock, stock, cutoff = models.training_rows(
        data["dates"], data["valid"], data["y"], 950
    )
    assert day.min() == 950 - 756
    assert day.max() == 950 - 11
    assert set(clock) == set(models.TRAIN_CLOCKS)
    assert set(stock) == set(range(20))
    assert np.all(data["dates"][day + 10] < cutoff)
    data["y"][day.min()] = np.nan
    reduced, _, _, _ = models.training_rows(
        data["dates"], data["valid"], data["y"], 950
    )
    assert reduced.min() == 950 - 755


# Freeze September labels before the holdout and respect the earlier August fit date.
def test_holdout_is_purged_for_every_refit():
    data = _dataset(days=1000, start="2023-01-03")
    for month in ("2026-08", "2026-09"):
        fit = np.flatnonzero(
            data["dates"].astype("datetime64[M]") == np.datetime64(month)
        )[0]
        day, _, _, cutoff = models.training_rows(
            data["dates"], data["valid"], data["y"], fit
        )
        assert np.all(data["dates"][day + 10] < models.HOLDOUT_START)
        assert np.all(data["dates"][day + 10] < data["dates"][fit])
        assert cutoff == min(models.HOLDOUT_START, data["dates"][fit])


# Exercise boosted fits, deterministic artifacts and verified prediction resume.
def test_real_boosting_scores_unlabelled_rows_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "MIN_TRAIN_DAYS", 8)
    data = _dataset()
    predictions, manifest = models.walk_forward(data, tmp_path / "first")
    fitted = [month for month in manifest["months"] if month["status"] == "fitted"]
    assert fitted
    assert np.isfinite(predictions[-10:]).all()
    assert (
        np.corrcoef(predictions[-10:, ..., 0].ravel(), data["X"][-10:, ..., 0].ravel())[
            0, 1
        ]
        > 0.7
    )
    repeated, second = models.walk_forward(data, tmp_path / "second")
    np.testing.assert_array_equal(predictions, repeated)
    assert [m.get("models") for m in manifest["months"]] == [
        m.get("models") for m in second["months"]
    ]
    resumed, saved = models.walk_forward(data, tmp_path / "first")
    np.testing.assert_array_equal(predictions, resumed)
    assert saved["prediction_sha256"] == manifest["prediction_sha256"]
    for month in fitted:
        assert np.datetime64(month["maximum_label_end"]) < np.datetime64(
            month["label_end_before"]
        )


# Changing labels unavailable to a fit cannot alter that month's predictions.
def test_real_ridge_future_label_invariance_and_training_only_scaling(monkeypatch):
    monkeypatch.setattr(models, "MIN_TRAIN_DAYS", 8)
    original = _dataset()
    changed = {**original, "y": original["y"].copy()}
    june = original["dates"].astype("datetime64[M]") == np.datetime64("2026-06")
    fit = np.flatnonzero(june)[0]
    changed["y"][fit - 10 :] = 123.0
    first, _ = models.walk_forward(original, method="ridge")
    second, _ = models.walk_forward(changed, method="ridge")
    np.testing.assert_array_equal(first[june], second[june])
    np.testing.assert_allclose(
        first[june, ..., 0], original["y"][june, ..., 0], atol=0.001
    )


# Enforce the declared 504 distinct-day requirement rather than merely counting rows.
def test_minimum_is_distinct_sessions_not_pooled_examples():
    data = _dataset(days=70)
    prediction, manifest = models.walk_forward(data, method="ridge")
    assert np.isnan(prediction).all()
    assert all(
        month["status"] == "insufficient_mature_history" for month in manifest["months"]
    )
    assert models.MIN_TRAIN_DAYS == 504


# Preserve missing rows and reject feature or calendar contract violations.
def test_unavailable_features_and_false_endpoint_metadata(monkeypatch):
    monkeypatch.setattr(models, "MIN_TRAIN_DAYS", 8)
    data = _dataset()
    data["valid"][-1, 0, 0] = False
    data["X"][-1, 0, 0] = np.nan
    predictions, _ = models.walk_forward(data, method="ridge")
    assert np.isnan(predictions[-1, 0, 0]).all()
    assert np.isfinite(predictions[-1, 1:]).all()
    data["valid"][-1, 0, 0] = True
    predictions, _ = models.walk_forward(data, method="ridge")
    assert np.isfinite(predictions[-1, 0, 0]).all()
    data["X"][-1, 0, 0] = np.inf
    with pytest.raises(ValueError, match="infinite causal features"):
        models.walk_forward(data, method="ridge")
    data = _dataset()
    data["label_end_dates"] = data["dates"].copy()
    with pytest.raises(ValueError, match="ten-session calendar"):
        models.walk_forward(data, method="ridge")


# Reject tampered artifacts and changed inputs instead of silently reusing stale fits.
def test_resume_requires_identical_input_and_verified_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "MIN_TRAIN_DAYS", 8)
    data = _dataset()
    _, manifest = models.walk_forward(data, tmp_path, method="ridge")
    altered = {**data, "y": data["y"].copy()}
    altered["y"][0, 0, 0, 0] += 0.5
    with pytest.raises(ValueError, match="Saved run differs"):
        models.walk_forward(altered, tmp_path, method="ridge")
    receipt = next(m for m in manifest["months"] if m["status"] == "fitted")
    artifact = tmp_path / receipt["prediction_file"]
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        models.walk_forward(data, tmp_path, method="ridge")
    assert json.loads((tmp_path / "identity.json").read_text())["method"] == "ridge"


# Benchmark outcomes cannot influence either policy trained over the declared book.
@pytest.mark.parametrize("method", ["boosting", "ridge"])
def test_benchmark_outcomes_do_not_train_models(method, monkeypatch):
    monkeypatch.setattr(models, "MIN_TRAIN_DAYS", 8)
    data = _dataset()
    mask = np.ones(data["X"].shape[2], dtype=bool)
    mask[-2:] = False
    data["training_symbols"] = mask
    changed = {**data, "y": data["y"].copy()}
    changed["y"][:, :, -2:] = -999.0
    first, manifest = models.walk_forward(data, method=method)
    second, _ = models.walk_forward(changed, method=method)
    np.testing.assert_array_equal(first, second)
    assert np.isfinite(first[-10:, :, -2:]).all()
    assert manifest["identity"]["training_symbols_sha256"] == models._array_hash(mask)


# An empty or malformed training book cannot silently trigger substitute training.
def test_training_book_mask_is_explicit_and_nonempty():
    data = _dataset()
    for bad in ([True], np.ones(20, dtype=int), np.zeros(20, dtype=bool)):
        data["training_symbols"] = bad
        with pytest.raises(ValueError, match="nonempty book"):
            models.walk_forward(data, method="ridge")


# Real 504-session fits cannot consume holdout labels during August or September.
def test_real_monthly_fit_keeps_all_holdout_labels_hidden():
    data = _dataset(days=631, start="2024-05-01")
    changed = {**data, "y": data["y"].copy()}
    endpoints = np.full(len(data["dates"]), np.datetime64("NaT", "D"))
    endpoints[:-10] = data["dates"][10:]
    changed["y"][endpoints >= models.HOLDOUT_START] = 1000.0
    first, manifest = models.walk_forward(data, method="ridge")
    second, _ = models.walk_forward(changed, method="ridge")
    months = data["dates"].astype("datetime64[M]")
    holdout_months = (months == np.datetime64("2026-08")) | (
        months == np.datetime64("2026-09")
    )
    assert np.isfinite(first[holdout_months]).all()
    np.testing.assert_array_equal(first[holdout_months], second[holdout_months])
    receipts = {m["month"]: m for m in manifest["months"]}
    assert receipts["2026-08"]["fit_date"] == "2026-08-03"
    assert receipts["2026-08"]["label_end_before"] == "2026-08-03"
    assert receipts["2026-09"]["label_end_before"] == "2026-08-17"
    assert receipts["2026-09"]["training_days"] >= 504
