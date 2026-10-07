"""Actual fits and causal artifact contracts for one-step waiting risk."""

import json

import numpy as np
import pytest

from backend.market import learned_entry_models as original
from backend.market import learned_execution_risk as risk


# Build enough independent training examples for the unchanged minimum-leaf rule.
def _dataset(days=631, start="2024-05-01", stocks=2):
    dates = np.busday_offset(start, np.arange(days), roll="forward").astype(
        "datetime64[D]"
    )
    rng = np.random.default_rng(19)
    x = rng.uniform(-1, 1, size=(days, 25, stocks, 2)).astype(np.float32)
    labels = np.empty(x.shape[:3] + (3,), dtype=np.float32)
    labels[..., 0] = 0.3
    labels[..., 1] = 0.09
    labels[..., 2] = 0.004 * x[..., 0]
    labels[-10:] = np.nan
    return {
        "X": x,
        "y": labels,
        "valid": np.ones(x.shape[:3], dtype=bool),
        "dates": dates,
        "feature_names": ["waiting_feature", "noise"],
        "training_symbols": np.ones(stocks, dtype=bool),
        "provenance": {"fixture": "synthetic"},
    }


# Train actual 504-session HGB fits and verify the short-horizon risk target.
def test_actual_504_day_fit_is_short_horizon_and_predicts_unknown_outcomes(tmp_path):
    data = _dataset()
    predictions, manifest = risk.walk_forward(data, tmp_path)
    assert predictions.shape == data["valid"].shape
    assert np.isfinite(predictions[-10:]).all()
    assert np.all(predictions[-10:] >= 0)
    assert np.max(predictions[-10:]) < 0.00002
    truth = risk.waiting_second_moment(data)
    available = np.isfinite(predictions) & np.isfinite(truth)
    assert np.corrcoef(predictions[available], truth[available])[0, 1] > 0.9
    receipt = next(m for m in manifest["months"] if m["status"] == "fitted")
    assert receipt["training_days"] >= 504
    assert len(receipt["models"]) == 1
    assert manifest["identity"]["target_schema"]["original_label_column"] == 2
    assert manifest["identity"]["target_schema"]["execution_horizon"] == (
        "one_decision_log_price_advantage"
    )
    assert manifest["identity"]["target_schema"]["terminal_wait"] == (
        "next_session_first_completed_bar"
    )
    saved, repeat = risk.walk_forward(data, tmp_path)
    np.testing.assert_array_equal(saved, predictions)
    assert repeat["prediction_sha256"] == manifest["prediction_sha256"]


# Mutating hidden waiting outcomes cannot change August or September fitted predictions.
def test_real_holdout_waiting_labels_are_hidden_from_all_refits():
    data = _dataset()
    changed = {**data, "y": data["y"].copy()}
    endpoints = np.full(len(data["dates"]), np.datetime64("NaT", "D"))
    endpoints[:-10] = data["dates"][10:]
    changed["y"][endpoints >= original.HOLDOUT_START, ..., 2] = 0.7
    first, manifest = risk.walk_forward(data)
    second, _ = risk.walk_forward(changed)
    months = data["dates"].astype("datetime64[M]")
    held = (months == np.datetime64("2026-08")) | (months == np.datetime64("2026-09"))
    assert np.isfinite(first[held]).all()
    np.testing.assert_array_equal(first[held], second[held])
    receipts = {m["month"]: m for m in manifest["months"]}
    assert receipts["2026-08"]["label_end_before"] == "2026-08-03"
    assert receipts["2026-09"]["label_end_before"] == "2026-08-17"
    assert (
        np.datetime64(receipts["2026-09"]["maximum_label_end"]) < original.HOLDOUT_START
    )


# Ten-session outcome values never select or train a short-horizon risk example.
def test_ten_session_outcomes_are_not_risk_target_or_training_filter():
    data = _dataset()
    changed = {**data, "y": data["y"].copy()}
    changed["y"][..., :2] = np.nan
    first, _ = risk.walk_forward(data)
    second, _ = risk.walk_forward(changed)
    np.testing.assert_array_equal(first, second)
    np.testing.assert_allclose(
        risk.waiting_second_moment(data), data["y"][..., 2].astype(float) ** 2
    )


# Missing waiting targets reduce training without erasing causal prediction rows.
def test_missing_targets_do_not_remove_predictions(monkeypatch):
    monkeypatch.setattr(original, "MIN_TRAIN_DAYS", 8)
    data = _dataset(days=70, start="2026-05-01", stocks=20)
    data["y"][1, :, 0, 2] = np.inf
    prediction, manifest = risk.walk_forward(data)
    assert np.isnan(risk.waiting_second_moment(data)[1, :, 0]).all()
    assert np.isfinite(prediction[-10:]).all()
    assert manifest["identity"]["schema"] == risk.SCHEMA


# Inputs, target identity and saved model bytes must match before artifact reuse.
def test_risk_resume_rejects_foreign_target_and_tampered_model(tmp_path, monkeypatch):
    monkeypatch.setattr(original, "MIN_TRAIN_DAYS", 8)
    data = _dataset(days=70, start="2026-05-01", stocks=20)
    _, manifest = risk.walk_forward(data, tmp_path)
    changed = {**data, "y": data["y"].copy()}
    changed["y"][0, 0, 0, 2] += 0.01
    with pytest.raises(ValueError, match="Saved run differs"):
        risk.walk_forward(changed, tmp_path)
    month = next(m for m in manifest["months"] if m["status"] == "fitted")
    model = tmp_path / month["models"][0]["file"]
    model.write_bytes(model.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="model artifact hash mismatch"):
        risk.walk_forward(data, tmp_path)
    identity = json.loads((tmp_path / "identity.json").read_text())
    assert identity["target_schema"]["units"] == "squared_log_price_ratio"
    assert identity["model_source_sha256"] != identity["original_model_source_sha256"]


# A changed target horizon cannot be hidden inside a previously saved monthly receipt.
def test_monthly_schema_and_calendar_maturity_guards(tmp_path, monkeypatch):
    monkeypatch.setattr(original, "MIN_TRAIN_DAYS", 8)
    data = _dataset(days=70, start="2026-05-01", stocks=20)
    _, manifest = risk.walk_forward(data, tmp_path)
    month = next(m for m in manifest["months"] if m["status"] == "fitted")
    receipt = tmp_path / (month["month"] + ".json")
    altered = json.loads(receipt.read_text())
    altered["target_schema"]["execution_horizon"] = "ten_sessions"
    receipt.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="target schema or horizon"):
        risk.walk_forward(data, tmp_path)
    data["label_end_dates"] = data["dates"].copy()
    with pytest.raises(ValueError, match="ten-session calendar"):
        risk.walk_forward(data)


# Retain negative risk and count unavailable outputs without inventing risk.
def test_invalid_model_outputs_are_retained_or_explicitly_unavailable(monkeypatch):
    # Exercise the artifact boundary with a deliberately invalid estimator response.
    class InvalidEstimator:
        # Accept the supplied training arrays without changing the feature contract.
        def fit(self, x, y):
            return self

        # Return one negative risk and one missing risk while preserving row count.
        def predict(self, x):
            result = np.ones(len(x), dtype=float)
            result[0], result[1] = -0.01, np.inf
            return result

    monkeypatch.setattr(original, "_estimator", lambda method: InvalidEstimator())
    data = _dataset(days=2, stocks=2)
    predictions = np.full(data["valid"].shape, np.nan, dtype=np.float32)
    receipt = risk._fit_month(
        data["X"],
        risk.waiting_second_moment(data),
        data["valid"],
        (np.array([0]), np.array([0]), np.array([0])),
        np.array([1]),
        "synthetic",
        None,
        predictions,
    )
    assert predictions[1, 0, 0] < 0
    assert np.isnan(predictions[1, 0, 1])
    assert receipt["prediction_rows"] == 50
    assert receipt["negative_second_moment_predictions"] == 1
    assert receipt["unavailable_nonfinite_predictions"] == 1
