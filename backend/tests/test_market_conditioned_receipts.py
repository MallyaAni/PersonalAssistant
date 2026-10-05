"""Saved calibration proof refuses changed dates, coefficients and uncertainty."""

import hashlib
from pathlib import Path

import numpy as np
import pytest

from backend.cli.verify_joint_funded import MarketCalibrationVerifier
from backend.market import market_conditioned_calibration as model
from backend.market.daily_arithmetic_bridge import _hash
from backend.tests.test_market_conditioned_calibration import evidence


# Build a real numeric fitted receipt with an explicit synthetic historical bank.
def case(*, constant=False, default=False):
    dates, endpoints, forecast, outcome, context, support = evidence()
    endpoints[-2:] = np.datetime64("NaT", "D")
    if constant:
        forecast[:], context[:] = 0.003, [0.01, -0.1, 0.02, 0.5]
    if default:
        outcome[111] = -1
    fit = model.fit_market_log(
        dates,
        endpoints,
        forecast,
        outcome,
        context,
        support,
        fit_date=np.datetime64("2020-08-03"),
    )
    day = int(np.flatnonzero(dates == np.datetime64("2020-08-10"))[0])
    features = np.zeros((len(dates), 2, 13))
    features[:, 0, 4] = 0.02
    features[:, 1, [1, 5, 4, 12]] = context
    bank = {
        "dates": dates,
        "endpoints": endpoints,
        "symbols": ("AAA", "SPY"),
        "forecasts": np.c_[forecast, np.zeros(len(dates))],
        "labels": np.c_[outcome, np.zeros(len(dates))],
        "support": np.c_[support, np.zeros(len(dates), dtype=bool)],
        "features": features,
    }
    root = Path(__file__).resolve().parents[2]
    files = (
        "backend/market/market_conditioned_holding.py",
        "backend/market/market_conditioned_calibration.py",
        model.PROTOCOL,
    )
    source = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files
    }
    mean, multiplier = fit.predict(forecast[day], context[day])
    sample = {
        "policy": "market-conditioned-joint-holding/1-research",
        "status": "available",
        "decision_date": str(dates[day]),
        "fit_date": fit.fit_date,
        "label_end_before": fit.cutoff,
        "symbols": ["AAA"],
        "joint_dates": len(fit.selected),
        "decision_indices": fit.selected.tolist(),
        "current_context": context[day].tolist(),
        "current_context_sha256": _hash(context[day]),
        "calibration_identity": {
            "policy": "market-conditioned-joint-holding/1-research",
            "source_sha256": source[files[0]],
            "numerical_source_sha256": source[files[1]],
            "protocol_sha256": source[model.PROTOCOL],
            "context": list(model.CONTEXT),
            "context_sha256": _hash(context),
            "features_sha256": _hash(features),
            "confidence_guarantee": False,
            "adoption_eligible": False,
            "calibration_residuals": "in_sample_on_genuine_OOS_base_forecasts",
        },
        "calibration": [{"symbol": "AAA", **fit.receipt()}],
        "predictions": [
            {"conditional_log_mean": mean, "residual_multiplier": multiplier}
        ],
    }
    return bank, source, sample


# Verification calls no estimator, numeric fitter or current prediction mechanism.
@pytest.mark.parametrize(
    ("constant", "default"), [(False, False), (True, False), (False, True)]
)
def test_saved_numeric_receipt_without_refitting(monkeypatch, constant, default):
    bank, source, sample = case(constant=constant, default=default)

    # A saved proof must not regenerate the candidate whose result it checks.
    def forbidden(*args, **kwargs):
        pytest.fail("Saved verification attempted fitting or prediction")

    monkeypatch.setattr(model, "fit_market_log", forbidden)
    monkeypatch.setattr(model.MarketLogFit, "predict", forbidden)
    MarketCalibrationVerifier(bank, source).check(sample)


# Shape-valid fabricated claims cannot pass as authenticated calibration evidence.
@pytest.mark.parametrize(
    ("path", "value", "error"),
    [
        (("calibration", 0, "coefficients", 0), 0.1, "stationarity"),
        (("predictions", 0, "residual_multiplier"), 100, "mean and leverage"),
        (("predictions", 0, "conditional_log_mean"), 0.1, "mean and leverage"),
        (("calibration", 0, "center", 0), 0.1, "training centers"),
        (("calibration", 0, "singular_values", 0), 100, "singular values"),
        (("calibration", 0, "directions", 0, 0), 0.1, "orthonormal"),
        (("calibration", 0, "row_hashes", "outcomes"), "0" * 64, "value differs"),
        (("calibration_identity", "source_sha256"), "0" * 64, "value differs"),
        (("calibration", 0, "confidence_guarantee"), True, "limitations"),
        (("calibration", 0, "rank"), 5, "numbers required"),
        (("current_context", 0), 0.1, "arithmetic differs"),
        (("calibration", 0, "coefficients", 0), False, "numbers required"),
    ],
)
def test_saved_receipt_mutations_refused(path, value, error):
    bank, source, sample = case()
    target = sample
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=error):
        MarketCalibrationVerifier(bank, source).check(sample)


# Neither omitted training dates nor future training dates certify a saved model.
@pytest.mark.parametrize("future", [False, True])
def test_changed_original_training_dates_refused(future):
    bank, source, sample = case()
    rows = sample["calibration"][0]["selected_indices"]
    if future:
        rows[-1] += 10
    else:
        rows.pop(0)
    with pytest.raises(ValueError, match="Original market singleton dates"):
        MarketCalibrationVerifier(bank, source).check(sample)


# Empty or repeated stocks cannot conceal a missing independent model check.
@pytest.mark.parametrize("empty", [False, True])
def test_original_stock_list_required(empty):
    bank, source, sample = case()
    for field in ("symbols", "calibration", "predictions"):
        sample[field] = [] if empty else sample[field] * 2
    with pytest.raises(ValueError, match="Unique nonempty"):
        MarketCalibrationVerifier(bank, source).check(sample)


# Detaching arrays and source metadata prevents a caller from changing a saved proof.
def test_bank_detachment_and_original_endpoint_contract():
    bank, source, sample = case()
    verifier = MarketCalibrationVerifier(bank, source)
    bank["features"][:] = np.nan
    source.clear()
    verifier.check(sample)
    wrong, source, _ = case()
    wrong["endpoints"][100] -= np.timedelta64(1, "D")
    with pytest.raises(ValueError, match=r"D\+2"):
        MarketCalibrationVerifier(wrong, source)


# An unidentified changed current predictor is rejected instead of certifying precision.
def test_current_query_outside_fitted_span_refused():
    bank, source, sample = case(constant=True)
    day = int(
        np.flatnonzero(bank["dates"] == np.datetime64(sample["decision_date"]))[0]
    )
    bank["forecasts"][day, 0] = 0.1
    with pytest.raises(ValueError, match="identified market query"):
        MarketCalibrationVerifier(bank, source).check(sample)
