"""Actual crossfitted regressions and causal sequential stopping acceptance."""

import json

import numpy as np
import pytest

from backend.market import learned_entry_models as original
from backend.market import sequential_execution_models as sequential


# Supply causal features and independent next-open outcomes for real Ridge fitting.
def _dataset(days=540, start="2024-05-01", stocks=2):
    dates = np.busday_offset(start, np.arange(days), roll="forward").astype(
        "datetime64[D]"
    )
    rng = np.random.default_rng(290)
    x = rng.normal(size=(days, 25, stocks, 2)).astype(np.float32)
    level = 100 + np.arange(days)[:, None, None] * 0.005
    close = np.broadcast_to(level, x.shape[:3]).astype(np.float32).copy()
    execution = close + 0.2 * x[..., 0] + np.arange(25)[None, :, None] * 0.01
    return {
        "X": x,
        "y": np.full(x.shape[:3] + (3,), np.nan, dtype=np.float32),
        "valid": np.ones(x.shape[:3], dtype=bool),
        "dates": dates,
        "feature_names": ["causal_structure", "volatility"],
        "current_close": close,
        "next_open": execution.astype(np.float32),
        "training_symbols": np.ones(stocks, dtype=bool),
        "provenance": {"fixture": "synthetic-independent-outcomes"},
    }


# Check directional price costs, suffix starts and missing forecasts without outcomes.
def test_directional_decisions_and_suffix_specific_stops():
    assert sequential.decision(0.01, "buy") == "wait"
    assert sequential.decision(0.01, "sell") == "execute"
    assert sequential.decision(-0.01, "buy") == "execute"
    assert sequential.decision(-0.01, "sell") == "wait"
    assert sequential.decision(0, "sell") == "execute"
    assert sequential.decision(np.nan, "buy") == "unavailable"
    forecasts = np.zeros((25, 1, 2))
    forecasts[1:5, 0, 0] = 1
    forecasts[2, 0] = np.nan
    observed = np.ones((25, 1), dtype=bool)
    chosen = sequential.suffix_selection(forecasts, observed)
    assert chosen[0, 0, 0] == 0
    assert chosen[1, 0, 0] == 5
    assert chosen[2, 0, 1] == 3
    assert chosen[24, 0, 0] == 24
    observed[24] = False
    forecasts[:24, 0, 0] = 1
    assert sequential.suffix_selection(forecasts, observed)[0, 0, 0] == -1


# Reject hindsight improvement and retain a prediction-selected missing execution.
def test_selected_price_locks_missing_and_unfavorable_outcomes():
    execution = np.array([[[95.0], [np.nan], [120.0]]])
    chosen = np.array([[[1, 2]]], dtype=np.int16)
    prices = sequential._selected_prices(execution, np.array([0]), chosen)
    assert np.isnan(prices[0, 0, 0])
    assert prices[0, 0, 1] == 120
    close = np.full_like(execution, 100)
    target = sequential._target(execution, close, np.array([0]), 0, prices[..., 1])
    assert target[0, 0] == -0.25


# Fit actual independent chains and prove held prices cannot alter their own nuisance.
def test_actual_grouped_fold_exclusion_and_held_outcome_invariance():
    data = _dataset(days=60)
    days = np.arange(48)
    first, receipt = sequential.fit_window(data, days)
    changed = {**data, "next_open": data["next_open"].copy()}
    held = days[days % 3 == 1]
    changed["next_open"][held] *= 1.4
    second, changed_receipt = sequential.fit_window(changed, days)
    assert receipt["folds"][1]["heads"] == changed_receipt["folds"][1]["heads"]
    held_first = sequential.predict_window(
        {"heads": first["nuisance"]["1"]}, data, held
    )
    held_second = sequential.predict_window(
        {"heads": second["nuisance"]["1"]}, changed, held
    )
    np.testing.assert_array_equal(held_first, held_second)
    np.testing.assert_array_equal(
        first["oof_selected_clocks"][days % 3 == 1],
        second["oof_selected_clocks"][days % 3 == 1],
    )
    for record in receipt["folds"]:
        assert set(record["train_days"]).isdisjoint(record["held_days"])
        assert set(record["train_days"]) | set(record["held_days"]) == set(days)
        assert all(d % 3 == record["fold"] for d in record["held_days"])
        for head in record["heads"].values():
            if head["status"] == "fitted":
                assert head["certificate"]["normalized_gradient"] <= 1e-8
    assert first["oof_targets"].shape == (48, 24, 2, 2)


# Preserve fixed forecasts with unknown outcomes and independently valid quotes.
def test_fixed_prediction_ignores_future_prices_and_terminal_prefix():
    data = _dataset(days=60)
    bundle, _ = sequential.fit_window(data, np.arange(48))
    score = np.arange(48, 60)
    before = sequential.predict_window(bundle, data, score)
    changed = {
        **data,
        "next_open": np.full_like(data["next_open"], np.nan),
        "y": data["y"].copy(),
    }
    changed["y"][:] = 900
    after = sequential.predict_window(bundle, changed, score)
    np.testing.assert_array_equal(before, after)
    assert np.isfinite(after[:, :24]).all()
    assert np.isnan(after[:, 24]).all()
    changed["valid"] = data["valid"].copy()
    changed["valid"][:, 24] = False
    observed = np.isfinite(changed["current_close"][score[0]])
    assert np.all(sequential.suffix_selection(after[0], observed)[24] == 24)


# Exclude benchmark outcomes from nuisance and final fitting across every clock.
def test_actual_benchmark_outcomes_never_train_the_book():
    data = _dataset(days=40)
    data["training_symbols"][1] = False
    changed = {**data, "next_open": data["next_open"].copy()}
    changed["next_open"][:, :, 1] *= 12
    first, first_receipt = sequential.fit_window(data, np.arange(30))
    second, second_receipt = sequential.fit_window(changed, np.arange(30))
    for fold in range(3):
        assert (
            first_receipt["folds"][fold]["heads"]
            == second_receipt["folds"][fold]["heads"]
        )
    assert first_receipt["heads"] == second_receipt["heads"]
    np.testing.assert_array_equal(
        sequential.predict_window(first, data, np.arange(30, 40)),
        sequential.predict_window(second, changed, np.arange(30, 40)),
    )


# Keep a genuine 504-session floor, causal maturity and exact saved numeric identity.
def test_actual_mature_monthly_models_resume_and_reject_corrupt_bytes(tmp_path):
    data = _dataset()
    predictions, manifest = sequential.walk_forward(data, tmp_path)
    fitted = [m for m in manifest["months"] if m["status"] == "fitted"]
    assert fitted
    assert all(m["training_days"] >= 504 for m in fitted)
    assert all(
        m["status"] == "insufficient_mature_history"
        for m in manifest["months"]
        if m["training_days"] < 504
    )
    assert np.isfinite(predictions[-3:, :24]).all()
    assert np.isnan(predictions[:, 24]).all()
    resumed, _ = sequential.walk_forward(data, tmp_path)
    np.testing.assert_array_equal(predictions, resumed)
    changed = {**data, "next_open": data["next_open"].copy()}
    changed["next_open"][0, 0, 0] += 1
    with pytest.raises(ValueError, match="Saved run differs"):
        sequential.walk_forward(changed, tmp_path)
    archive = tmp_path / fitted[0]["month"] / "models.npz"
    with archive.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="byte mismatch"):
        sequential.validate_saved(tmp_path, data)


# Preserve holdout refits when all hidden future execution labels are changed.
def test_actual_august_september_fit_maturity_and_hidden_outcome_invariance():
    data = _dataset(days=631)
    changed = {**data, "next_open": data["next_open"].copy()}
    endpoints = np.full(len(data["dates"]), np.datetime64("NaT", "D"))
    endpoints[:-10] = data["dates"][10:]
    changed["next_open"][endpoints >= original.HOLDOUT_START] *= 1.9
    first, manifest = sequential.walk_forward(data)
    second, _ = sequential.walk_forward(changed)
    months = data["dates"].astype("datetime64[M]")
    holdout_months = months >= np.datetime64("2026-08")
    np.testing.assert_array_equal(first[holdout_months], second[holdout_months])
    records = {m["month"]: m for m in manifest["months"]}
    assert records["2026-08"]["label_end_before"] == "2026-08-03"
    assert records["2026-09"]["label_end_before"] == "2026-08-17"


# Reject a rewritten fold receipt that includes a held session in training.
def test_readback_rejects_false_fold_membership(tmp_path, monkeypatch):
    monkeypatch.setattr(original, "MIN_TRAIN_DAYS", 20)
    data = _dataset(days=65, start="2026-05-01")
    _, manifest = sequential.walk_forward(data, tmp_path)
    month = next(m for m in manifest["months"] if m["status"] == "fitted")
    month["fit"]["folds"][0]["train_days"].append(
        month["fit"]["folds"][0]["held_days"][0]
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / month["month"] / "receipt.json").write_text(json.dumps(month))
    with pytest.raises(ValueError, match="exclusion mismatch"):
        sequential.validate_saved(tmp_path, data)


# Equal numeric values must not conceal a changed persisted forecast representation.
def test_authenticated_wrong_forecast_dtype_is_rejected(tmp_path):
    data = _dataset(days=36)
    sequential.walk_forward(data, tmp_path)
    path = tmp_path / "predictions.npz"
    with np.load(path, allow_pickle=False) as saved:
        arrays = {key: saved[key] for key in saved.files}
    arrays["predictions"] = arrays["predictions"].astype(np.float64)
    np.savez(path, **arrays)
    receipt_path = tmp_path / "manifest.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["forecast"]["sha256"] = sequential._file_hash(path)
    receipt["forecast"]["arrays"] = {
        key: original._array_hash(value) for key, value in arrays.items()
    }
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="dtype"):
        sequential.validate_saved(tmp_path, data)
