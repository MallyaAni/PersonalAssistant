"""Synthetic supplied-array proof of the causal daily arithmetic bridge."""

from datetime import UTC, datetime, time

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as bridge


# Build a complete reviewed exchange calendar rather than compacting missing prices.
def sessions(start="2023-01-03", count=820):
    _, actual = exchange.reviewed_sessions()
    days = np.arange(
        np.datetime64(start), np.datetime64(start) + np.timedelta64(count * 3, "D")
    )
    return days[np.is_busday(days, busdaycal=actual)][:count].astype("datetime64[D]")


# Create exact affine arithmetic labels without any real market data or model fit.
def fixture(start="2023-01-03", count=820):
    dates = sessions(start, count)
    rng = np.random.default_rng(13)
    forecasts = rng.normal(0, 0.025, (count, 4))
    target = 0.001 + 0.1 * forecasts
    opens = np.full((count, 4), 100.0)
    for day in range(count - 2):
        opens[day + 2] = opens[day + 1] * (1 + target[day])
    return {
        "dates": dates,
        "symbols": ("AAA", "BBB", "SPY", "QQQ"),
        "adjusted_opens": opens,
        "grades": np.full((count, 4), 2),
        "eligible": np.ones((count, 4), dtype=bool),
        "absolute_forecasts": forecasts,
        "calendar": dates.copy(),
        "data_as_of": datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        ),
    }


# Actual monthly synthetic fits recover the fixed arithmetic map after mature warmup.
def test_actual_monthly_affine_fit_recovers_units_and_coefficients():
    data = fixture()
    result = bridge.walk_forward(**data)
    fitted = [m for m in result.manifest["months"] if m["status"] == "fitted"]
    assert fitted
    for month in fitted:
        assert month["alpha"] == pytest.approx(0.001, abs=1e-14)
        assert month["beta"] == pytest.approx(0.1, abs=1e-12)
        assert month["training_days"] >= 504
        assert np.datetime64(month["maximum_label_end"]) < np.datetime64(
            month["label_end_before"]
        )
        assert month["total_weight"] == pytest.approx(month["training_days"])
    allowed = np.isfinite(result.calibrated)
    np.testing.assert_allclose(
        result.calibrated[allowed],
        (0.001 + 0.1 * data["absolute_forecasts"])[allowed],
        atol=1e-14,
    )
    assert np.isnan(result.calibrated[:, 2:]).all()
    first = np.flatnonzero(np.isfinite(result.calibrated).any(axis=1))[0]
    assert result.manifest["first_score_date"] == str(data["dates"][first])
    assert np.isnan(result.calibrated[:first]).all()


# Explicit affine boundaries cannot invert a model or amplify its slope beyond one.
@pytest.mark.parametrize(("slope", "expected"), [(-0.2, 0.0), (0.3, 0.3), (2.0, 1.0)])
def test_monotone_shrinkage_boundaries(slope, expected):
    x = np.array([-2.0, 0.0, 2.0])
    y = 0.04 + slope * x
    fitted = bridge.fit_affine(x, y, np.ones(3))
    assert fitted["beta"] == pytest.approx(expected)
    assert fitted["alpha"] == pytest.approx(0.04)


# A numerically nonbinary constant predictor has exactly zero fitted slope.
def test_constant_predictor_uses_only_the_past_trained_mean():
    fitted = bridge.fit_affine(
        np.full(1500, 0.3), np.linspace(-0.03, 0.07, 1500), np.ones(1500)
    )
    assert fitted["beta"] == 0
    assert fitted["predictor_variance"] == 0
    assert fitted["alpha"] == fitted["past_mean"]


# Sessions with fewer observed stocks have the same aggregate training weight.
def test_unequal_stock_coverage_is_balanced_by_whole_date():
    data = fixture(count=640)
    data["absolute_forecasts"][::2, 1] = np.nan
    result = bridge.walk_forward(**data)
    month = next(m for m in result.manifest["months"] if m["status"] == "fitted")
    training_dates = np.array(month["training_dates"], dtype="datetime64[D]")
    index = np.searchsorted(data["dates"], training_dates)
    valid = np.isfinite(data["absolute_forecasts"][index, :2])
    means = [
        np.mean(result.labels[day, :2][mask])
        for day, mask in zip(index, valid, strict=True)
    ]
    assert month["past_mean"] == pytest.approx(np.mean(means))
    assert set(month["rows_per_date"]) == {1, 2}
    assert month["total_weight"] == pytest.approx(len(index))


# Many rows on fewer than 504 mature dates never substitute for whole-date support.
def test_missing_forecast_dates_cannot_be_hidden_by_more_stock_rows():
    data = fixture(count=600)
    data["absolute_forecasts"][:150] = np.nan
    result = bridge.walk_forward(**data)
    assert np.isnan(result.calibrated).all()
    assert result.manifest["first_score_date"] is None
    assert all(m["training_days"] < 504 for m in result.manifest["months"])


# Missing future prices keep the final causal prediction opportunities intact.
def test_unknown_tail_labels_do_not_remove_prediction_rows():
    data = fixture()
    data["adjusted_opens"][-2:] = np.nan
    result = bridge.walk_forward(**data)
    assert np.isnan(result.labels[-4:]).all()
    assert np.isfinite(result.calibrated[-2:, :2]).all()
    assert result.score_mask[-2:, :2].all()
    data["absolute_forecasts"][-1, 0] = np.nan
    missing = bridge.walk_forward(**data)
    assert np.isnan(missing.calibrated[-1, 0])
    assert np.isnan(missing.past_mean[-1, 0])
    assert np.isfinite(missing.calibrated[-1, 1])


# Later market observations cannot change an earlier month's fitted map or score.
def test_future_suffix_mutation_keeps_earlier_fits_and_scores():
    data = fixture()
    original = bridge.walk_forward(**data)
    boundary = int(np.flatnonzero(data["dates"] >= np.datetime64("2025-06-02"))[0])
    data["adjusted_opens"][boundary:] *= 1.2
    data["absolute_forecasts"][boundary:] += 0.5
    altered = bridge.walk_forward(**data)
    np.testing.assert_array_equal(
        original.calibrated[:boundary], altered.calibrated[:boundary]
    )
    before = [
        m
        for m in original.manifest["months"]
        if np.datetime64(m["fit_date"]) < data["dates"][boundary]
    ]
    after = [
        m
        for m in altered.manifest["months"]
        if np.datetime64(m["fit_date"]) < data["dates"][boundary]
    ]
    assert before == after


# All August and September refits exclude outcomes at or beyond the frozen boundary.
def test_august_september_label_freeze_with_actual_monthly_fits():
    data = fixture(start="2023-01-03", count=950)
    original = bridge.walk_forward(**data)
    future = data["dates"] >= bridge.FREEZE
    data["adjusted_opens"][future] *= 1.7
    altered = bridge.walk_forward(**data)
    for month in ("2026-08", "2026-09"):
        one = next(m for m in original.manifest["months"] if m["month"] == month)
        two = next(m for m in altered.manifest["months"] if m["month"] == month)
        assert one["status"] == "fitted"
        assert one == two
        assert np.datetime64(one["maximum_label_end"]) < bridge.FREEZE
        rows = data["dates"].astype("datetime64[M]") == np.datetime64(month)
        np.testing.assert_array_equal(
            original.calibrated[rows], altered.calibrated[rows]
        )


# Earlier data outside the 756-decision-session window cannot influence a refit.
def test_preceding_window_counts_sessions_instead_of_complete_rows():
    data = fixture(count=850)
    result = bridge.walk_forward(**data)
    month = result.manifest["months"][-1]
    assert month["training_days"] <= 756
    first = month["fit_index"]
    if month["training_dates"]:
        assert (
            np.datetime64(month["training_dates"][0])
            >= data["dates"][max(0, first - 756)]
        )


# Source price rescaling cancels in outcomes without extra variance corrections.
def test_shared_price_basis_rescaling_keeps_labels_and_predictions():
    data = fixture(count=640)
    original = bridge.walk_forward(**data)
    data["adjusted_opens"] *= np.array([10.0, 2.0, 1.0, 0.5])
    equivalent = bridge.walk_forward(**data)
    np.testing.assert_allclose(
        original.labels, equivalent.labels, equal_nan=True, atol=1e-14
    )
    np.testing.assert_allclose(
        original.calibrated, equivalent.calibrated, equal_nan=True, atol=1e-14
    )


# Equivalent aware timestamps permit the same close; earlier instants cannot.
def test_timezone_and_completed_close_availability():
    data = fixture(count=640)
    data["data_as_of"] = data["data_as_of"].astimezone(UTC)
    complete = bridge.walk_forward(**data)
    assert np.isfinite(complete.calibrated[-1, :2]).all()
    data["data_as_of"] = data["data_as_of"].replace(tzinfo=None)
    with pytest.raises(ValueError, match="Timezone"):
        bridge.walk_forward(**data)
    data["data_as_of"] = datetime.combine(
        data["dates"][-1].astype(object),
        time(12),
        exchange.NEW_YORK,
    )
    incomplete = bridge.walk_forward(**data)
    assert not incomplete.score_mask[-1].any()
    assert np.isnan(incomplete.calibrated[-1]).all()


# Eligibility and grades remain causal evidence and do not become labels.
def test_ineligible_or_b_grade_rows_never_receive_scored_forecasts():
    data = fixture(count=640)
    data["eligible"][-1, 0] = False
    data["grades"][-2, 1] = 1
    result = bridge.walk_forward(**data)
    assert np.isnan(result.calibrated[-1, 0])
    assert np.isnan(result.calibrated[-2, 1])


# Calendar omissions and malformed prices are refused instead of compacted or filled.
@pytest.mark.parametrize("invalid", ["calendar", "price", "grade", "eligible"])
def test_supplied_array_contract_refuses_invalid_evidence(invalid):
    data = fixture(count=20)
    if invalid == "calendar":
        data["calendar"] = data["calendar"][1:]
    elif invalid == "price":
        data["adjusted_opens"][1, 0] = 0
    elif invalid == "grade":
        data["grades"][1, 0] = 4
    else:
        data["eligible"] = data["eligible"].astype(int)
    with pytest.raises(ValueError, match="calendar|positive|Ordinal|boolean"):
        bridge.walk_forward(**data)


# Receipts retain original typed bytes even when arithmetic internally uses float64.
def test_original_dtype_is_preserved_in_input_receipt():
    data = fixture(count=640)
    data["absolute_forecasts"] = data["absolute_forecasts"].astype(np.float32)
    data["grades"] = data["grades"].astype(np.int8)
    result = bridge.walk_forward(**data)
    for name in ("absolute_forecasts", "grades", "calendar"):
        assert result.manifest["input_sha256"][name] == bridge._hash(data[name])


# Published early closes permit completed-close scoring at the actual exchange hour.
def test_actual_early_close_clock_does_not_require_sixteen_hundred():
    data = fixture()
    day = np.datetime64("2025-11-28", "D")
    row = int(np.flatnonzero(data["dates"] == day)[0])
    data["data_as_of"] = datetime(2025, 11, 28, 13, tzinfo=exchange.NEW_YORK)
    result = bridge.walk_forward(**data)
    assert np.isfinite(result.calibrated[row, :2]).all()
    assert not result.score_mask[row + 1 :].any()
