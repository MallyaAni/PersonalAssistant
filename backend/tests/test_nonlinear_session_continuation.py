"""Real pooled fits and causality for the remaining-session research candidate."""

import copy

import numpy as np
import pytest

from backend.market import nonlinear_session_continuation as model
from backend.market import sequential_execution_models as suffix


# Generate causal paths whose known signal distinguishes buying from selling later.
def _dataset():
    dates = np.busday_offset("2026-01-02", np.arange(90), roll="forward")
    rng = np.random.default_rng(41)
    signal = rng.choice([-1.0, 1.0], size=(90, 1, 8))
    x = np.empty((90, 25, 8, 3), dtype=np.float32)
    x[..., 0] = 0.02
    x[..., 1] = signal
    x[..., 2] = np.arange(25)[None, :, None] / 24
    execution = 100 + signal * np.arange(25)[None, :, None] * 0.2
    return {
        "X": x, "y": np.full((90, 25, 8, 3), np.nan, np.float32),
        "valid": np.ones((90, 25, 8), dtype=bool), "dates": dates,
        "feature_names": ["volatility_20", "path_signal", "session_time"],
        "tickers": ("AAOI", "COHR", "NVDA", "STX", "WDC", "MU", "SPY", "QQQ"),
        "training_symbols": np.array([True] * 6 + [False, False]),
        "current_close": np.full((90, 25, 8), 100.0),
        "next_open": execution,
    }


# Locate the actual first supplied March session used by the synthetic monthly fit.
def _march(data):
    months = data["dates"].astype("datetime64[M]")
    return int(np.flatnonzero(months == np.datetime64("2026-03"))[0])


# Exercise fixed nonlinear fits, all clocks, opposite sides and missing terminals.
def test_real_monthly_models_distinguish_paths_and_use_all_clocks(monkeypatch):
    monkeypatch.setattr(model, "MIN_MATURE_SESSIONS", 8)
    data = _dataset()
    index = _march(data)
    fitted = model.fit_month(data, index)
    scored = model.predict_month(fitted, data, np.array([index, index + 1]))
    assert fitted["receipt"]["status"] == "fitted"
    assert np.isnan(scored[:, 24]).all()
    assert np.isfinite(scored[:, :24]).all()
    signal = data["X"][[index, index + 1], :24, :, 1]
    assert np.mean((scored[:, :24, :, 0] > 0) == (signal < 0)) > 0.9
    assert np.mean((scored[:, :24, :, 1] < 0) == (signal > 0)) > 0.9
    for fold in fitted["receipt"]["folds"]:
        assert not set(fold["train_days"]) & set(fold["held_days"])
        assert len(fold["chain"]) == 3
        for iteration in fold["chain"]:
            assert all(head["clocks"] == list(range(24)) for head in iteration["heads"])
    assert all(head["clocks"] == list(range(24)) for head in fitted["receipt"]["heads"])
    changed = copy.deepcopy(data)
    changed["next_open"][index:] = 9999
    changed["y"][index:] = 123
    np.testing.assert_array_equal(
        scored, model.predict_month(fitted, changed, np.array([index, index + 1]))
    )


# Keep held outcomes outside their nuisance chain and its preprocessing fits.
def test_held_fold_outcomes_do_not_change_nuisance_models(monkeypatch):
    monkeypatch.setattr(model, "MIN_MATURE_SESSIONS", 8)
    data = _dataset()
    index = _march(data)
    first = model.fit_month(data, index)
    held = first["receipt"]["folds"][0]["held_days"]
    changed = copy.deepcopy(data)
    changed["next_open"][held] *= 3
    second = model.fit_month(changed, index)
    a = first["receipt"]["folds"][0]
    b = second["receipt"]["folds"][0]
    assert a["chain"] == b["chain"]
    assert a["held_targets_sha256"] != b["held_targets_sha256"]


# Unknown outer-month prices and labels cannot alter the fitted model or forecast.
def test_future_month_outcomes_and_benchmark_labels_cannot_train(monkeypatch):
    monkeypatch.setattr(model, "MIN_MATURE_SESSIONS", 8)
    data = _dataset()
    index = _march(data)
    first = model.fit_month(data, index)
    changed = copy.deepcopy(data)
    changed["next_open"][index - 10:] = 9999
    changed["y"][index - 10:] = 9999
    changed["next_open"][:, :, 6:] = 99999
    second = model.fit_month(changed, index)
    assert first["receipt"]["heads"] == second["receipt"]["heads"]
    np.testing.assert_array_equal(model.predict_month(first, data, np.array([index])),
                                  model.predict_month(second, data, np.array([index])))


# Lock the prediction-selected future outcome even when it is missing or unfavorable.
def test_selected_suffix_never_searches_for_a_better_or_available_price():
    data = _dataset()
    forecasts = np.zeros((1, 25, 8, 2))
    forecasts[:, :5, :, 0] = 1
    data["next_open"][0, 5, 0] = np.nan
    targets, selected = model._targets(data, np.array([0]), forecasts)
    assert selected[0, 1, 0, 0] == 5
    assert np.isnan(targets[0, 0, 0, 0])
    data["next_open"][0, 5, 0] = 150
    targets, _ = model._targets(data, np.array([0]), forecasts)
    assert targets[0, 0, 0, 0] == -0.5
    data["next_open"][0, 24, 0] = 1
    again, _ = model._targets(data, np.array([0]), forecasts)
    assert again[0, 0, 0, 0] == -0.5


# Require distinct mature sessions rather than admitting a short pooled sample.
def test_default_readiness_is_not_bypassed_by_many_intraday_rows():
    data = _dataset()
    fitted = model.fit_month(data, _march(data))
    assert model.MIN_MATURE_SESSIONS == 504
    assert fitted["receipt"]["status"] == "insufficient_mature_history"
    assert all(head is None for head in fitted["heads"])


# Reject ambiguous dates, implicit book membership and benchmark contamination.
@pytest.mark.parametrize(("problem", "message"), [
    ("midmonth", "first supplied session"),
    ("boolean", "explicit monthly fit index"),
    ("no_membership", "Explicit stock-only"),
    ("benchmark", "Benchmark names"),
    ("duplicate_ticker", "Unique original ticker"),
])
def test_monthly_and_named_book_boundaries(problem, message):
    data = _dataset()
    index = _march(data)
    if problem == "midmonth":
        index += 1
    elif problem == "boolean":
        index = True
    elif problem == "no_membership":
        del data["training_symbols"]
    elif problem == "benchmark":
        data["training_symbols"][6] = True
    else:
        data["tickers"] = ("AAOI",) * 8
    with pytest.raises(ValueError, match=message):
        model.fit_month(data, index)


# Prevent an admitted model from being scored before its fit or outside its own month.
@pytest.mark.parametrize(("problem", "message"), [
    ("past", "Scoring must follow"),
    ("nextmonth", "Scoring month or feature"),
    ("renamed", "Scoring month or feature"),
    ("changed_fit_date", "Scoring month or feature"),
])
def test_scoring_clock_and_feature_contract(problem, message):
    data = _dataset()
    index = _march(data)
    fitted = model.fit_month(data, index)
    day = index
    if problem == "past":
        day -= 1
    elif problem == "nextmonth":
        months = data["dates"].astype("datetime64[M]")
        day = int(np.flatnonzero(months == np.datetime64("2026-04"))[0])
    elif problem == "renamed":
        data["tickers"] = ("COHR", "AAOI", *data["tickers"][2:])
    else:
        data["dates"][index:] += np.timedelta64(1, "D")
    with pytest.raises(ValueError, match=message):
        model.predict_month(fitted, data, np.array([day]))


# Preserve whole-month endpoint purging independently of any fitted estimator.
def test_calendar_endpoint_maturity_is_strict():
    data = _dataset()
    index = _march(data)
    days, cutoff = suffix.training_days(data["dates"], index)
    assert np.all(data["dates"][days + 10] < cutoff)
    assert days[-1] == index - 11


# An unavailable terminal observation cannot become a fabricated suffix outcome.
def test_unknown_terminal_observation_remains_missing():
    data = _dataset()
    data["current_close"][0, 24, 0] = np.nan
    forecasts = np.full((1, 25, 8, 2), np.nan)
    targets, selected = model._targets(data, np.array([0]), forecasts)
    assert np.all(selected[0, :, 0] == -1)
    assert np.isnan(targets[0, :, 0]).all()


# The scored prefix survives changes to later features and missing outcome arrays.
def test_predictor_uses_only_scored_observations(monkeypatch):
    monkeypatch.setattr(model, "MIN_MATURE_SESSIONS", 8)
    data = _dataset()
    index = _march(data)
    fitted = model.fit_month(data, index)
    original = model.predict_month(fitted, data, np.array([index]))
    changed = copy.deepcopy(data)
    changed["X"][index + 1:] = 17
    changed["next_open"][:] = np.nan
    changed["y"][:] = np.nan
    np.testing.assert_array_equal(
        original, model.predict_month(fitted, changed, np.array([index]))
    )


# Missing stock volatility cannot yield a receipt falsely declaring trained heads.
def test_unavailable_risk_is_not_labelled_a_successful_fit(monkeypatch):
    monkeypatch.setattr(model, "MIN_MATURE_SESSIONS", 8)
    data = _dataset()
    data["X"][..., 0] = np.nan
    index = _march(data)
    fitted = model.fit_month(data, index)
    assert fitted["receipt"]["status"] == "no_finite_training_targets"
    assert all(head is None for head in fitted["heads"])
    assert np.isnan(model.predict_month(fitted, data, np.array([index]))).all()
