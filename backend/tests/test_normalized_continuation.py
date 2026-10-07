"""Actual nonlinear fitting and causal stock-volatility continuation acceptance."""

import numpy as np
import pytest

from backend.market import normalized_continuation as model
from backend.market import sequential_execution_replay as replay


# Supply independently generated outcomes with a nonlinear observed signal.
def data():
    rng = np.random.default_rng(72)
    x = rng.normal(size=(160, 25, 3, 3)).astype(np.float32)
    x[..., 0] = 0.02
    x[..., 2] = np.arange(25)[None, :, None] / 24
    return {
        "X": x,
        "y": np.full((160, 25, 3, 3), np.nan, np.float32),
        "valid": np.ones((160, 25, 3), bool),
        "dates": np.busday_offset("2020-01-02", np.arange(160)),
        "feature_names": ("volatility_20", "path", "session_time"),
        "training_symbols": np.array([True, True, False]),
        "current_close": np.full((160, 25, 3), 100, np.float32),
    }


# Fit the real fixed estimator and learn opposite actions from nonlinear paths.
def test_actual_nonlinear_fit_and_direction():
    fixture = data()
    days = np.arange(120)
    scale = model.scales(fixture)[days, :24]
    normalized = np.where(fixture["X"][days, :24, :, 1] ** 2 > 1, 1.0, -1.0)
    target = np.repeat((normalized * scale)[..., None], 2, axis=-1)
    heads, receipts = model.fit_heads(fixture, days, target)
    prediction = model.predict(heads, fixture, np.arange(120, 160))
    actual = fixture["X"][120:, :24, :, 1] ** 2 > 1
    assert np.mean((prediction[:, :24, :, 0] > 0) == actual) > 0.85
    assert all(row["rows"] == 120 * 4 * 2 for row in receipts)
    assert np.isnan(prediction[:, 24]).all()
    delta = np.array([1.0, -1.0])
    counters = {"waiting_decisions": 0, "forecast_unavailable": 0}
    np.testing.assert_array_equal(
        replay.choose(
            np.array([[0.002, 0.002], [-0.002, -0.002]]),
            delta,
            np.ones(2, bool),
            np.ones(2, bool),
            False,
            counters,
        ),
        [False, False],
    )


# Keep model forecasts independent of unknown execution prices and future labels.
def test_future_outcomes_and_benchmark_training_excluded():
    fixture = data()
    days = np.arange(120)
    target = np.repeat(model.scales(fixture)[days, :24, :, None], 2, axis=-1)
    heads, receipt = model.fit_heads(fixture, days, target)
    baseline = model.predict(heads, fixture, np.array([150]))
    changed = {
        **fixture,
        "X": fixture["X"].copy(),
        "y": fixture["y"].copy(),
        "next_open": np.full((160, 25, 3), 999.0),
    }
    changed["y"][150:] = 1e6
    changed["X"][151:] = 5
    np.testing.assert_array_equal(
        baseline, model.predict(heads, changed, np.array([150]))
    )
    target[:, :, 2] = 1e10
    changed["X"][:120, :, 2, 1] = 100
    second, second_receipt = model.fit_heads(changed, days, target)
    assert receipt == second_receipt
    np.testing.assert_array_equal(
        baseline, model.predict(second, fixture, np.array([150]))
    )


# Refuse zero or invalid stock risk instead of inventing an epsilon price threshold.
@pytest.mark.parametrize("value", [0, -0.01, np.nan])
def test_unavailable_volatility(value):
    fixture = data()
    fixture["X"][:, :, 0, 0] = value
    assert np.isnan(model.scales(fixture)[:, :, 0]).all()


# Rescale the forecast with stock risk, without confusing it with confidence.
def test_scale_units_and_missing_current_observation():
    fixture = data()
    fixture["X"][:, :, 1, 0] *= 3
    scale = model.scales(fixture)
    np.testing.assert_allclose(scale[:, :24, 1], scale[:, :24, 0] * 3)
    fixture["current_close"][0, 0, 0] = np.nan
    assert np.isnan(model.scales(fixture)[0, 0, 0])


# Authenticate teacher bytes before permitting any real-data label reuse.
def test_wrong_teacher_is_rejected_before_fit(tmp_path):
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="original continuation"):
        model.validate_teacher(tmp_path, data())


# Reject fabricated finite forecasts for a month or side without a fitted model.
@pytest.mark.parametrize("status", ["insufficient_mature_history", "fitted"])
def test_resume_requires_a_fitted_side(tmp_path, status):
    days = np.array([0], dtype=np.int64)
    values = np.full((1, 25, 1, 2), np.nan, np.float32)
    values[0, 0, 0, 0] = 0.01
    arrays = {"days": days, "predictions": values}
    path = tmp_path / "2026-09-predictions.npz"
    model.teacher._save_npz(path, arrays)
    receipt = {
        "identity_sha256": "synthetic",
        "score_days": [0],
        "models": [],
        "status": status,
        "month": "2026-09",
        "heads": [{"status": "no_finite_targets"}] * 2,
        "forecast": {
            "file": path.name,
            "sha256": model.teacher._file_hash(path),
            "arrays": {
                key: model.base._array_hash(value) for key, value in arrays.items()
            },
        },
    }
    with pytest.raises(ValueError, match="Unfitted"):
        model.resume(tmp_path, receipt, days, "synthetic", np.full_like(values, np.nan))
