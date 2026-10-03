"""Causal labels, fitted daily heads and future-independent retention forecasts."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import learned_retention_models as m


# Omit wholly missing fields using training rows, never future feature values.
def test_real_head_handles_all_missing_training_column(tmp_path):
    import joblib

    x = np.full((504, 1, 13), np.nan)
    x[:, 0, 0] = np.linspace(0, 1, 504)
    x[:, 0, 3] = 0
    labels = x[:, :, 0] * 0.1
    head, receipt = m._fit_head(x, labels, np.ones((504, 1), bool), np.arange(504))
    assert receipt["status"] == "fitted"
    assert receipt["observed_feature_indices"] == [0, 3]
    original = head.predict(x[:, 0])
    assert np.isfinite(original).all()
    assert original[0] < original[-1]
    scored = x[:, 0].copy()
    scored[:, 1] = 1e6
    np.testing.assert_array_equal(head.predict(scored), original)
    path = tmp_path / "private-model.joblib"
    joblib.dump(head, path)
    np.testing.assert_array_equal(joblib.load(path).predict(scored), original)


# A wholly unobserved training matrix cannot fabricate a fitted forecast.
def test_head_without_any_observed_training_feature_is_unavailable():
    head, receipt = m._fit_head(
        np.full((504, 1, 13), np.nan),
        np.zeros((504, 1)),
        np.ones((504, 1), bool),
        np.arange(504),
    )
    assert head is None
    assert receipt["status"] == "no_observed_training_features"


# Provide aligned daily prices with a known stock and benchmark holding return.
def panel_data(rows=330):
    dates = np.busday_offset(np.datetime64("2024-01-02"), np.arange(rows))
    t = np.arange(rows)[:, None]
    price = 50 * np.exp(t * np.array([[0.002, 0.001, 0.0015]]))
    panel = SimpleNamespace(
        dates=dates,
        tickers=("X", "SPY", "QQQ"),
        open=price.copy(),
        close=price.copy(),
        adj_close=price.copy(),
    )
    grades = np.full(price.shape, 2)
    eligible = np.ones(price.shape, dtype=bool)
    return panel, grades, eligible


# Prepare the real adapter with its supplied complete-calendar source contract.
def prepared(rows=330):
    panel, grades, eligible = panel_data(rows)
    return m.prepare(panel, grades, eligible, panel.dates, {"basis": "synthetic"})


# Pin the exact ten-session next-open return and separate absolute SPY label.
def test_label_is_spy_relative_next_open_to_open_plus_eleven():
    data = prepared()
    np.testing.assert_allclose(data["relative_labels"][:-11, 0], 0.01, atol=1e-14)
    np.testing.assert_allclose(data["spy_labels"][:-11], 0.01, atol=1e-14)
    assert np.isnat(data["label_end_dates"][-11:]).all()
    assert np.isnan(data["relative_labels"][-11:]).all()
    assert data["label_end_dates"][0] == data["dates"][11]


# Ensure the latest row is scoreable without fabricated future holding returns.
def test_features_include_completed_close_and_do_not_require_labels():
    data = prepared()
    assert data["valid"][-1, 0]
    assert np.isnan(data["relative_labels"][-1, 0])
    assert data["X"][-1, 0, 0] == pytest.approx(0.002 * 5)
    assert data["X"][-1, 0, 8] == 2
    assert not data["valid"][:, 1:].any()


# Refuse a supplied exchange calendar that omits or adds a price session.
def test_calendar_mismatch_is_rejected():
    panel, grades, eligible = panel_data()
    with pytest.raises(ValueError, match="calendar"):
        m.prepare(panel, grades, eligible, panel.dates[:-1], {"basis": "synthetic"})


# Reject invalid supplied prices instead of silently manufacturing unavailable labels.
@pytest.mark.parametrize(
    ("field", "value"),
    [("close", np.inf), ("close", -1.0), ("open", -1.0), ("adj_close", -1.0)],
)
def test_invalid_daily_price_is_rejected(field, value):
    panel, grades, eligible = panel_data()
    getattr(panel, field)[280, 0] = value
    with pytest.raises(ValueError, match="positive-or-missing"):
        m.prepare(panel, grades, eligible, panel.dates, {"basis": "synthetic"})


# Missing future opens remain unavailable labels without cancelling valid forecasts.
def test_missing_future_open_does_not_suppress_current_feature_eligibility():
    panel, grades, eligible = panel_data()
    panel.open[281, 0] = np.nan
    data = m.prepare(panel, grades, eligible, panel.dates, {"basis": "synthetic"})
    assert data["valid"][270, 0]
    assert np.isnan(data["relative_labels"][270, 0])


# Keep opens and daily reference prices on one basis through a mechanical split.
def test_split_basis_does_not_create_a_negative_ninety_percent_label():
    panel, grades, eligible = panel_data()
    original = m.prepare(panel, grades, eligible, panel.dates, {"basis": "synthetic"})
    panel.open[:285, 0] *= 10
    panel.close[:285, 0] *= 10
    split = m.prepare(panel, grades, eligible, panel.dates, {"basis": "synthetic"})
    np.testing.assert_array_equal(original["X"], split["X"])
    np.testing.assert_allclose(
        original["relative_labels"], split["relative_labels"], equal_nan=True
    )


# Prove a future panel suffix cannot revise earlier observations or mature labels.
def test_future_prefix_invariance():
    panel, grades, eligible = panel_data()
    original = m.prepare(panel, grades, eligible, panel.dates, {"basis": "synthetic"})
    panel.adj_close[300:] *= 5
    panel.open[300:] *= 5
    panel.close[300:] *= 5
    grades[300:] = 0
    changed = m.prepare(panel, grades, eligible, panel.dates, {"basis": "synthetic"})
    np.testing.assert_array_equal(original["X"][:300], changed["X"][:300])
    np.testing.assert_array_equal(
        original["relative_labels"][:289], changed["relative_labels"][:289]
    )


# Ensure an endpoint on the fitting date is purged, not treated as already known.
def test_monthly_purge_excludes_endpoint_on_fit_date():
    data = prepared()
    days, cutoff = m.training_days(data, 300)
    assert cutoff == data["dates"][300]
    assert days[-1] == 288
    assert np.all(data["label_end_dates"][days] < cutoff)


# Freeze training outcome endpoints before the repeatedly inspected recent window.
def test_later_fits_cannot_learn_from_reused_recent_outcomes():
    data = prepared()
    dates = np.busday_offset(np.datetime64("2025-07-01"), np.arange(len(data["dates"])))
    data["dates"] = dates
    data["label_end_dates"] = np.r_[dates[11:], np.full(11, np.datetime64("NaT", "D"))]
    days, cutoff = m.training_days(data, len(dates) - 1)
    assert cutoff == np.datetime64("2026-08-17")
    assert np.all(data["label_end_dates"][days] < cutoff)


# Construct an already prepared known-feature grid for real small-estimator tests.
def synthetic_training():
    rng = np.random.default_rng(22)
    days, stocks = 90, 42
    dates = np.busday_offset(np.datetime64("2019-01-02"), np.arange(days))
    features = rng.normal(size=(days, stocks, 13))
    labels = features[..., 0] * 0.02
    labels[-11:] = np.nan
    valid = np.ones((days, stocks), dtype=bool)
    valid[:, -2:] = False
    return {
        "X": features,
        "relative_labels": labels,
        "spy_labels": np.r_[features[:-11, -2, 0] * 0.01, np.full(11, np.nan)],
        "valid": valid,
        "spy_valid": np.ones(days, dtype=bool),
        "dates": dates,
        "label_end_dates": np.r_[dates[11:], np.full(11, np.datetime64("NaT", "D"))],
        "feature_names": list(m.FEATURE_NAMES),
        "symbols": tuple(f"X{i}" for i in range(stocks - 2)) + ("SPY", "QQQ"),
        "training_symbols": np.r_[np.ones(stocks - 2, dtype=bool), False, False],
        "spy_index": stocks - 2,
        "provenance": {"basis": "synthetic"},
    }


# Exercise the real registered estimators and predict rows with unknown future labels.
def test_actual_monthly_heads_predict_driving_feature_and_unlabelled_rows(monkeypatch):
    monkeypatch.setattr(m.base, "MIN_TRAIN_DAYS", 20)
    data = synthetic_training()
    result = m.walk_forward(data)
    assert np.isnan(result.relative[:22]).all()
    assert np.isfinite(result.relative[-1, :-2]).all()
    assert np.isfinite(result.spy[-1])
    assert np.isnan(result.relative[:, -2:]).all()
    scoreable = np.isfinite(result.relative[:, :-2])
    rho = np.corrcoef(
        result.relative[:, :-2][scoreable], data["X"][:, :-2, 0][scoreable]
    )[0, 1]
    assert rho > 0.7
    assert set(result.manifest["identity"]["runtime"]) == {
        "python",
        "numpy",
        "scipy",
        "sklearn",
    }
    assert len(result.manifest["identity"]["source_sha256"]) == 5
    assert all(
        len(value) == 64
        for value in result.manifest["identity"]["source_sha256"].values()
    )
    for receipt in result.manifest["months"]:
        if receipt["maximum_label_end"] is not None:
            assert receipt["maximum_label_end"] < receipt["fit_date"]


# Require independent warmup for the stock and market heads without a shared fake fit.
def test_stock_warmup_does_not_fabricate_market_forecasts(monkeypatch):
    monkeypatch.setattr(m.base, "MIN_TRAIN_DAYS", 20)
    data = synthetic_training()
    data["spy_labels"][:] = np.nan
    result = m.walk_forward(data)
    assert np.isfinite(result.relative[-1, 0])
    assert np.isnan(result.spy).all()
    assert all(heads[1] is None for heads in result.models.values())


# Ensure future label changes cannot influence the model used for an earlier month.
def test_later_labels_do_not_change_earlier_month_forecasts(monkeypatch):
    monkeypatch.setattr(m.base, "MIN_TRAIN_DAYS", 20)
    data = synthetic_training()
    original = m.walk_forward(data)
    data["relative_labels"][35:] = 5
    data["spy_labels"][35:] = -5
    changed = m.walk_forward(data)
    feb = data["dates"].astype("datetime64[M]") == np.datetime64("2019-02")
    np.testing.assert_array_equal(original.relative[feb], changed.relative[feb])
    np.testing.assert_array_equal(original.spy[feb], changed.spy[feb])


# Refuse altered outcome clocks, benchmark training rows and malformed eligibility.
@pytest.mark.parametrize(
    "defect",
    ["endpoint", "benchmark", "valid", "feature_inf", "label_inf", "duplicate_date"],
)
def test_invalid_prepared_contract_is_rejected(defect):
    data = synthetic_training()
    if defect == "endpoint":
        data["label_end_dates"][0] = data["dates"][10]
    elif defect == "benchmark":
        data["training_symbols"][-2] = True
    elif defect == "valid":
        data["valid"] = data["valid"].astype(int)
    elif defect == "feature_inf":
        data["X"][0, 0, 0] = np.inf
    elif defect == "label_inf":
        data["relative_labels"][0, 0] = np.inf
    else:
        data["dates"][1] = data["dates"][0]
    with pytest.raises(ValueError, match="required|must"):
        m.walk_forward(data)
