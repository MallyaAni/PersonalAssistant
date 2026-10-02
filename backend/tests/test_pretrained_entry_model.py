"""Causal and numerical acceptance for the optional pretrained challenger."""

import numpy as np
import pytest

from backend.market.pretrained_entry_model import (
    MODEL_REVISION,
    PretrainedEntryModel,
    causal_log_context,
    forecast_from_quantiles,
    historical_forecasts,
    verify_artifacts,
)


# Supply full raw grids with an observed final-session prefix for causal checks.
def raw_sessions():
    opens = [
        np.linspace(100, 102, 26),
        np.linspace(103, 105, 26),
        np.linspace(106, 108, 26),
    ]
    closes = [x + 0.1 for x in opens]
    return opens, closes, np.array([99.0, 102.1, 105.1])


# Produce a deterministic marginal log-price forecast without imitating real weights.
def fixed_quantiles(context, horizon, quantiles):
    return np.arange(horizon)[:, None] * 0.0001 + np.asarray(quantiles)[None, :] * 0.01


# Confirm changes after the completed observation never enter model context.
def test_future_prefix_invariance():
    opens, closes, priors = raw_sessions()
    before = causal_log_context(opens, closes, priors, 9)
    opens[-1][10:] = np.nan
    closes[-1][10:] = -999
    np.testing.assert_array_equal(before, causal_log_context(opens, closes, priors, 9))


# Confirm each session's raw split units cancel independently in its prior-close ratio.
def test_independent_session_price_units_cancel():
    opens, closes, priors = raw_sessions()
    before = causal_log_context(opens, closes, priors, 9)
    factors = np.array([10.0, 1.5, 0.25])
    after = causal_log_context(
        [x * f for x, f in zip(opens, factors, strict=True)],
        [x * f for x, f in zip(closes, factors, strict=True)],
        priors * factors,
        9,
    )
    np.testing.assert_allclose(before, after, atol=1e-14)


# Confirm normal and final-session waiting use their explicitly declared open clocks.
@pytest.mark.parametrize(("bar", "wait_step"), [(0, 2), (9, 2), (24, 4)])
def test_forecast_endpoint_and_wait_indices(bar, wait_step):
    context = np.linspace(-0.05, 0, 200)
    horizon = 2 * (25 - bar + 260)
    q = fixed_quantiles(context, horizon, np.arange(1, 10) / 10)
    result = forecast_from_quantiles(q, bar, context)
    assert result.status == "available"
    assert result.mean_log_return == pytest.approx((horizon - 1) * 0.0001)
    assert result.waiting_advantage == pytest.approx(-wait_step * 0.0001)
    assert result.second_moment_proxy >= result.mean_log_return**2
    assert not result.calibrated_risk
    assert result.endpoint == "regular-close-proxy"


# Refuse model quantiles that violate ordering instead of repairing them invisibly.
def test_crossing_quantiles_fail_closed():
    context = np.linspace(-0.05, 0, 200)
    q = fixed_quantiles(context, 552, np.arange(1, 10) / 10)
    q[0, 0] = q[0, -1] + 1
    assert forecast_from_quantiles(q, 9, context).status == "unavailable"


# Refuse NaNs, wrong endpoint spans and too little context for observed risk.
@pytest.mark.parametrize("defect", ["nan", "shape", "context"])
def test_invalid_forecasts_remain_unavailable(defect):
    context = np.linspace(-0.05, 0, 200)
    q = fixed_quantiles(context, 552, np.arange(1, 10) / 10)
    if defect == "nan":
        q[0, 0] = np.nan
    elif defect == "shape":
        q = q[:-1]
    else:
        context = context[:40]
    assert forecast_from_quantiles(q, 9, context).status == "unavailable"


# Keep visible missing-price boundaries and do not bridge irregular session geometry.
def test_invalid_observed_prices_and_early_close_refused():
    opens, closes, priors = raw_sessions()
    closes[-1][5] = np.nan
    with pytest.raises(ValueError, match="observed prefix"):
        causal_log_context(opens, closes, priors, 9)
    opens, closes, priors = raw_sessions()
    opens[0] = opens[0][:14]
    with pytest.raises(ValueError, match="full regular-session"):
        causal_log_context(opens, closes, priors, 9)


# Verify the adapter passes a private causal copy and returns stable declared outputs.
def test_adapter_copy_determinism_and_log_offset_invariance():
    context = np.linspace(10, 10.1, 200)
    original = context.copy()
    model = PretrainedEntryModel(fixed_quantiles)
    first = model.forecast(context, 9)
    second = model.forecast(context + 100, 9)
    np.testing.assert_array_equal(context, original)
    assert first.status == second.status == "available"
    assert first.mean_log_return == second.mean_log_return
    assert first.waiting_advantage == second.waiting_advantage
    assert len(MODEL_REVISION) == 40
    assert MODEL_REVISION != "main"


# Keep a missing dependency distinct from an economically flat forecast.
def test_inference_failure_is_explicit():
    # Represent an unavailable optional dependency at the inference seam.
    def unavailable(*args):
        raise ImportError("missing optional model")

    result = PretrainedEntryModel(unavailable).forecast(np.linspace(-0.1, 0, 200), 9)
    assert result.status == "unavailable"
    assert "ImportError" in result.reason
    assert np.isnan(result.mean_log_return)


# Pin local model bytes rather than trusting a mutable directory or model identifier.
def test_changed_artifact_refused(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors").write_bytes(b"wrong weights")
    with pytest.raises(ValueError, match="pinned artifact"):
        verify_artifacts(tmp_path)


# Refuse nonintegral decision clocks before computing an incorrect endpoint shape.
@pytest.mark.parametrize("bar", [9.5, "9", -1, 25])
def test_invalid_decision_clocks_fail_closed(bar):
    context = np.linspace(-0.05, 0, 200)
    result = PretrainedEntryModel(fixed_quantiles).forecast(context, bar)
    assert result.status == "unavailable"


# Exercise actual immutable weights explicitly when the private cache is supplied.
def test_real_pinned_cpu_forecast_when_enabled(monkeypatch):
    import os

    directory = os.environ.get("ANIOS_CHRONOS_TEST_WEIGHTS")
    if not directory:
        pytest.skip("optional pinned CPU weights not supplied; not a model pass")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    model = PretrainedEntryModel.load(directory, local_directory=directory)
    context = np.sin(np.arange(400) / 15) * 0.02
    first = model.forecast(context, 9)
    second = model.forecast(context, 9)
    assert first.status == "available"
    assert first == second
    assert not first.calibrated_risk
    assert model.provenance["device"] == "cpu"


# Keep the declared book denominator and fixed clock when history is incomplete.
def test_historical_cohort_missing_rows_and_artifact_identity(tmp_path):
    import json
    from types import SimpleNamespace

    dates = np.arange("2026-08-10", "2026-08-21", dtype="datetime64[D]")
    panel = SimpleNamespace(dates=dates, tickers=("ONE", "MISSING"))
    cube = SimpleNamespace(
        dates=dates,
        open=np.full((len(dates), 26), 100.0),
        close=np.full((len(dates), 26), 100.0),
        prior_close=np.full(len(dates), 100.0),
    )
    valid = np.ones((len(dates), 25, 2), dtype=bool)
    model = PretrainedEntryModel(fixed_quantiles, {"unit_test_forecaster": True})
    path = tmp_path / "predictions.npz"
    result = historical_forecasts(
        panel,
        {"ONE": cube},
        valid,
        path,
        source_identity={"snapshot_sha256": "a" * 64},
        model=model,
    )
    assert result["metadata"]["requested"] == 8
    assert result["metadata"]["available"] == 4
    assert result["metadata"]["unavailable"] == 4
    assert np.all(np.isnan(result["predictions"][:, :9]))
    assert np.all(np.isnan(result["predictions"][:, 10:]))
    assert np.all(np.isnan(result["predictions"][:, 9, 1]))
    assert result["reasons"][-1, 1] == "missing-cube"
    with np.load(path, allow_pickle=False) as stored:
        metadata = json.loads(str(stored["metadata"]))
        assert metadata["source_identity"] == {"snapshot_sha256": "a" * 64}
        np.testing.assert_array_equal(stored["predictions"], result["predictions"])
    with pytest.raises(FileExistsError):
        historical_forecasts(
            panel,
            {"ONE": cube},
            valid,
            path,
            source_identity={"snapshot_sha256": "a" * 64},
            model=model,
        )
