"""Actual fixed sklearn fits prove the controlled direct arithmetic learner."""

from datetime import datetime

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as bridge
from backend.market import direct_daily_arithmetic as direct


# Supply reviewed synthetic sessions, causal features and exact arithmetic prices.
def fixture(count=570, start="2023-01-03"):
    _, actual = exchange.reviewed_sessions()
    first = np.datetime64(start)
    candidates = np.arange(first, first + np.timedelta64(count * 3, "D"))
    dates = candidates[np.is_busday(candidates, busdaycal=actual)][:count]
    rng = np.random.default_rng(87)
    signal = rng.uniform(-1, 1, (count, 4))
    features = np.zeros((count, 4, 13), dtype=np.float32)
    features[..., 0] = signal
    features[..., 2] = np.nan
    labels = 0.0003 + 0.008 * features[..., 0]
    prices = np.full((count, 4), 100.0)
    for day in range(count - 2):
        prices[day + 2] = prices[day + 1] * (1 + labels[day])
    absolute = features[..., 0].astype(np.float64) * 0.04
    reference = bridge.walk_forward(
        dates,
        ("AAA", "BBB", "SPY", "QQQ"),
        prices,
        np.full((count, 4), 2),
        np.ones((count, 4), dtype=bool),
        absolute,
        dates,
        data_as_of=datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        ),
    )
    prepared = {
        "dates": dates,
        "symbols": ("AAA", "BBB", "SPY", "QQQ"),
        "X": features,
        "valid": np.ones((count, 4), dtype=bool),
        "feature_names": direct.FEATURE_NAMES,
        "absolute_forecasts": absolute,
    }
    return prepared, reference


# Direct fixed boosting learns signed one-day arithmetic returns from actual features.
def test_actual_fixed_boosting_learns_signed_arithmetic_target():
    prepared, parent = fixture()
    result = direct.walk_forward(prepared, parent)
    known = np.isfinite(result.forecasts)
    assert known.any()
    assert np.nanmin(result.forecasts) < 0 < np.nanmax(result.forecasts)
    matched = known & np.isfinite(parent.labels)
    assert np.corrcoef(result.forecasts[matched], parent.labels[matched])[0, 1] > 0.8
    assert np.isnan(result.forecasts[:, 2:]).all()
    assert result.manifest["first_score_date"] == parent.manifest["first_score_date"]
    for own, original in zip(
        result.manifest["months"], parent.manifest["months"], strict=True
    ):
        assert own["row_hashes"] == original["row_hashes"]
        assert own["training_days"] == original["training_days"]
        if own["status"] == "fitted":
            assert own["past_mean"] == pytest.approx(original["past_mean"], abs=1e-15)
            assert own["model"]["iterations"] == 64
            assert 2 not in own["observed_feature_indices"]


# An unchanged input yields identical numeric tree and forecast evidence on repeat fits.
def test_actual_fit_is_deterministic_without_changing_original_arrays():
    prepared, parent = fixture(count=530)
    source = prepared["X"].copy()
    one = direct.walk_forward(prepared, parent)
    two = direct.walk_forward(prepared, parent)
    np.testing.assert_array_equal(one.forecasts, two.forecasts)
    assert one.manifest == two.manifest
    np.testing.assert_array_equal(prepared["X"], source)


# Prepared validity cannot quietly remove an original bridge opportunity.
def test_original_feature_support_disagreement_refuses_fit():
    prepared, parent = fixture(count=530)
    prepared["valid"][10, 0] = False
    with pytest.raises(ValueError, match="support disagrees"):
        direct.walk_forward(prepared, parent)


# A modified old absolute forecast cannot pass the authenticated row lineage.
def test_original_absolute_forecast_bytes_are_required():
    prepared, parent = fixture(count=530)
    prepared["absolute_forecasts"][10, 0] += 1e-7
    with pytest.raises(ValueError, match="absolute_forecasts bytes"):
        direct.walk_forward(prepared, parent)


# Per-date training weights are the identical date-balanced parent selection.
def test_actual_date_weights_and_past_mean_match_unequal_coverage():
    prepared, parent = fixture(count=530)
    prepared["absolute_forecasts"][::2, 1] = np.nan
    raw = prepared["absolute_forecasts"]
    # Rebuild only synthetic parent evidence through the real causal bridge.
    prices = np.full(parent.labels.shape, 100.0)
    for day in range(len(prices) - 2):
        prices[day + 2] = prices[day + 1] * (1 + parent.labels[day])
    dates = prepared["dates"]
    parent = bridge.walk_forward(
        dates,
        prepared["symbols"],
        prices,
        np.full(prices.shape, 2),
        np.ones(prices.shape, bool),
        raw,
        dates,
        data_as_of=parent.manifest["data_as_of"],
    )
    result = direct.walk_forward(prepared, parent)
    for own, old in zip(
        result.manifest["months"], parent.manifest["months"], strict=True
    ):
        assert own["row_hashes"]["weights"] == old["row_hashes"]["weights"]
        assert own["rows_per_date"] == old["rows_per_date"]
        if own["status"] == "fitted":
            assert own["past_mean"] == pytest.approx(old["past_mean"], abs=1e-15)


# Scoring never requires the final rows' future arithmetic outcomes.
def test_tail_with_missing_labels_is_still_predicted():
    prepared, parent = fixture(count=530)
    result = direct.walk_forward(prepared, parent)
    assert np.isnan(parent.labels[-2:]).all()
    assert np.isfinite(result.forecasts[-2:, :2]).all()


# A column unseen during training is not selected because it appears while scoring.
def test_observed_columns_are_selected_on_training_only():
    prepared, parent = fixture(count=530)
    before = direct.walk_forward(prepared, parent)
    final_month = prepared["dates"].astype("datetime64[M]")[-1]
    scored = prepared["dates"].astype("datetime64[M]") == final_month
    prepared["X"][scored, :, 2] = 50000
    after = direct.walk_forward(prepared, parent)
    np.testing.assert_array_equal(before.forecasts[scored], after.forecasts[scored])
    head = after.models[str(final_month)]
    assert 2 not in head.columns


# Later feature observations cannot alter a previous monthly model or forecast.
def test_future_feature_suffix_preserves_prior_fitted_models():
    prepared, parent = fixture(count=570)
    before = direct.walk_forward(prepared, parent)
    month = prepared["dates"].astype("datetime64[M]")[-1]
    future = prepared["dates"].astype("datetime64[M]") == month
    prepared["X"][future, :, 0] *= -5
    after = direct.walk_forward(prepared, parent)
    np.testing.assert_array_equal(before.forecasts[~future], after.forecasts[~future])
    for receipt in before.manifest["months"]:
        if receipt["month"] != str(month):
            other = next(
                row
                for row in after.manifest["months"]
                if row["month"] == receipt["month"]
            )
            assert receipt == other


# Exact row receipt disagreement fails before an estimator sees any labels.
@pytest.mark.parametrize(
    "field", ["weights", "labels", "forecasts", "decision_indices"]
)
def test_bridge_training_row_hash_disagreement_refuses_fit(field):
    prepared, parent = fixture(count=530)
    parent.manifest["months"][0]["row_hashes"][field] = "0" * 64
    with pytest.raises(ValueError, match="training support mismatch"):
        direct.walk_forward(prepared, parent)


# A forged fitted status cannot bypass the whole-date warmup or fit availability clock.
def test_insufficient_whole_dates_cannot_be_marked_fitted():
    prepared, parent = fixture(count=30)
    parent.manifest["months"][0]["status"] = "fitted"
    with pytest.raises(ValueError, match="fit status"):
        direct.walk_forward(prepared, parent)


# Invalid actual fitted-head predictions are counted and never clipped into returns.
def test_nonfinite_and_impossible_predictions_remain_unavailable():
    prepared, parent = fixture(count=530)
    result = direct.walk_forward(prepared, parent)
    head = next(value for value in result.models.values() if value is not None)
    head.estimator._baseline_prediction[:] = -10
    values, counts = direct.predict(head, prepared["X"][-2:], parent.score_mask[-2:])
    assert np.isnan(values).all()
    assert counts["at_or_below_minus_one"] == 4
    head.estimator._baseline_prediction[:] = np.nan
    values, counts = direct.predict(head, prepared["X"][-2:], parent.score_mask[-2:])
    assert np.isnan(values).all()
    assert counts["nonfinite"] == 4


# August and September whole-date endpoints remain strictly before the fixed freeze.
def test_actual_frozen_refits_exclude_holdout_outcomes():
    prepared, parent = fixture(count=800, start="2023-09-01")
    result = direct.walk_forward(prepared, parent)
    for month in ("2026-08", "2026-09"):
        receipt = next(
            row for row in result.manifest["months"] if row["month"] == month
        )
        assert receipt["status"] == "fitted"
        assert np.datetime64(receipt["maximum_label_end"]) < bridge.FREEZE
        assert np.datetime64(receipt["label_end_before"]) <= bridge.FREEZE


# Feature infinities are an invalid source grid instead of an imputed market state.
def test_infinite_original_feature_is_refused():
    prepared, parent = fixture(count=30)
    prepared["X"][5, 0, 0] = np.inf
    with pytest.raises(ValueError, match="thirteen causal"):
        direct.walk_forward(prepared, parent)
