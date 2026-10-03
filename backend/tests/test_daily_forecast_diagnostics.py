"""Supplied-array calibration clocks, price basis and causal denominators."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from backend.market import daily_forecast_diagnostics as d
from backend.market import learned_retention_models as original


# Constant samples have no identified correlation even when their mean rounds.
@pytest.mark.parametrize("rows", [1, 2, 1218])
@pytest.mark.parametrize("constant_side", ["forecast", "realization"])
def test_constant_values_do_not_fabricate_correlation(rows, constant_side):
    varying = np.arange(rows, dtype=float) / 10000
    constant = np.full(rows, 0.015)
    forecasts = constant if constant_side == "forecast" else varying
    outcomes = varying if constant_side == "forecast" else constant
    selected = np.ones(rows, dtype=bool)
    missing = np.zeros(rows, dtype=bool)
    result = d._statistics(selected, forecasts, outcomes, selected, missing, missing)
    assert result["matched_rows"] == rows
    assert result["pearson"] is None


# Build original prepared labels and monthly receipts without fitting a model.
def fixture(rows=1050):
    dates = np.busday_offset(np.datetime64("2022-01-03"), np.arange(rows))
    names = ("X", "Y", "Z", "SPY", "QQQ")
    day = np.arange(rows)[:, None]
    prices = 40 * np.exp(day * np.array([[0.002, 0.001, 0.0005, 0.001, 0.0015]]))
    panel = SimpleNamespace(
        dates=dates,
        tickers=names,
        open=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
    )
    grades, eligible = np.full(prices.shape, 2), np.ones(prices.shape, bool)
    return panel, grades, eligible


# Supply causal monthly support from original clocks with deterministic forecasts.
def saved(panel, grades, eligible):
    prepared = original.prepare(
        panel, grades, eligible, panel.dates, {"synthetic": True}
    )
    relative = np.full(grades.shape, np.nan)
    spy = np.full(len(panel.dates), np.nan)
    months = panel.dates.astype("datetime64[M]")
    receipts = {
        "identity": {
            "policy": original.POLICY,
            "minimum_days": 504,
            "maximum_days": 756,
            "label_end": 11,
            "holdout_end_before": "2026-08-17",
            "symbols": list(panel.tickers),
        },
        "months": [],
    }
    for month in np.unique(months):
        scored = np.flatnonzero(months == month)
        days, cutoff = original.training_days(prepared, int(scored[0]))
        row = {
            "month": str(month),
            "fit_date": str(panel.dates[scored[0]]),
            "label_end_before": str(cutoff),
            "maximum_label_end": str(prepared["label_end_dates"][days[-1]])
            if len(days)
            else None,
        }
        for head, labels, valid, forecast in (
            ("stock", prepared["relative_labels"], prepared["valid"], relative),
            (
                "spy",
                prepared["spy_labels"][:, None],
                prepared["spy_valid"][:, None],
                spy,
            ),
        ):
            count = int(np.any(valid[days] & np.isfinite(labels[days]), axis=1).sum())
            status = "fitted" if count >= 504 else "insufficient_mature_history"
            row[head] = {"training_days": count, "status": status}
            if status == "fitted":
                if head == "stock":
                    local = forecast[scored]
                    local[prepared["valid"][scored]] = 0.013
                    forecast[scored] = local
                else:
                    forecast[scored[prepared["spy_valid"][scored]]] = 0.01
        receipts["months"].append(row)
    return prepared, relative, spy, receipts


# Exercise the public pure-array entry point with declared original provenance.
def diagnose(panel, grades, eligible, *, as_of=None, saved_values=None):
    prepared, relative, spy, receipts = saved_values or saved(panel, grades, eligible)
    return d.diagnose(
        panel.dates,
        panel.tickers,
        panel.open,
        panel.close,
        panel.adj_close,
        grades,
        eligible,
        prepared,
        relative,
        spy,
        receipts,
        {"selection": "reconstructed_current_vintage_not_historical_publications"},
        data_as_of=as_of or f"{panel.dates[-1]}T16:00:00-05:00",
        price_basis=d.PRICE_BASIS,
    )


# Pin the fitted target and keep a twenty-session outcome separately named.
def test_original_labels_and_twenty_session_compatibility():
    panel, grades, eligible = fixture()
    result = diagnose(panel, grades, eligible)
    ten, twenty = (result["row_evidence"]["horizons"][str(h)] for h in (10, 20))
    np.testing.assert_allclose(ten["absolute"][:-11, 0], 0.02, atol=1e-13)
    np.testing.assert_allclose(ten["relative"][:-11, 0], 0.01, atol=1e-13)
    np.testing.assert_allclose(twenty["absolute"][:-21, 0], 0.04, atol=1e-13)
    assert ten["end_dates"][800] == panel.dates[811]
    assert twenty["end_dates"][800] == panel.dates[821]
    assert result["outcome_horizons"]["20"] == "horizon_compatibility_only"
    assert set(result["per_stock"]["10"]) == {"X", "Y", "Z"}
    stats = result["statistics"]["10"]["all"]["eligible"]["absolute"]["all"]
    assert stats["opportunities"] == len(panel.dates) * 3
    assert stats["immature_outcomes"] == 11 * 3
    assert stats["forecast_unavailable"] > 0
    assert stats["volatility_history_unavailable"] == 252 * 3


# A coherent split/dividend representation leaves adjusted holding labels intact.
def test_daily_price_basis_uses_one_adjusted_open_conversion():
    panel, grades, eligible = fixture()
    original_result = diagnose(panel, grades, eligible)
    panel.open[:900, 0] *= 10
    panel.close[:900, 0] *= 10
    changed = diagnose(panel, grades, eligible)
    np.testing.assert_allclose(
        changed["row_evidence"]["horizons"]["10"]["absolute"],
        original_result["row_evidence"]["horizons"]["10"]["absolute"],
        equal_nan=True,
    )


# Missing market outcomes do not erase stock absolute outcomes or opportunities.
def test_missing_spy_endpoint_keeps_stock_absolute_return():
    panel, grades, eligible = fixture()
    panel.open[911, 3] = np.nan
    result = diagnose(panel, grades, eligible)
    ten = result["row_evidence"]["horizons"]["10"]
    assert ten["absolute"][900, 0] == pytest.approx(0.02)
    assert np.isnan(ten["relative"][900, 0])
    assert result["row_evidence"]["cohort_masks"]["eligible"][900, 0]


# Cohort denominators include unavailable features and missing price outcomes.
def test_missing_history_and_future_open_are_explicit():
    panel, grades, eligible = fixture()
    panel.adj_close[:700, 1] = np.nan
    panel.open[911, 0] = np.nan
    result = diagnose(panel, grades, eligible)
    stats = result["per_stock"]["10"]["X"]["eligible"]["absolute"]
    assert stats["missing_start_prices"] == 1
    assert stats["missing_end_prices"] == 1
    assert result["row_evidence"]["cohort_masks"]["eligible"][900, 1]
    assert result["row_evidence"]["volatility_group"][900, 1] == -1
    assert result["per_stock"]["10"]["Y"]["eligible"]["absolute"][
        "opportunities"
    ] == len(panel.dates)


# Future coherent price/label changes cannot rewrite earlier opportunities or groups.
def test_future_labels_do_not_change_causal_denominators():
    panel, grades, eligible = fixture()
    as_of = f"{panel.dates[850]}T16:00:00-05:00"
    before = diagnose(panel, grades, eligible, as_of=as_of)
    panel.open[860:, 0] *= 0.4
    panel.close[860:, 0] *= 0.4
    panel.adj_close[860:, 0] *= 0.4
    after = diagnose(panel, grades, eligible, as_of=as_of)
    for key in ("decision_observed", "volatility_group", "volatility252"):
        np.testing.assert_array_equal(
            before["row_evidence"][key], after["row_evidence"][key]
        )
    for cohort in ("eligible", "eligible_A"):
        np.testing.assert_array_equal(
            before["row_evidence"]["cohort_masks"][cohort],
            after["row_evidence"]["cohort_masks"][cohort],
        )
    assert not before["row_evidence"]["horizons"]["10"]["mature"][850]


# At an opening endpoint a label matures while that day's decision close is future.
def test_label_opening_maturity_and_early_close_decision_clock():
    panel, grades, eligible = fixture()
    end = 900
    result = diagnose(
        panel, grades, eligible, as_of=f"{panel.dates[end]}T09:30:00-04:00"
    )
    assert result["row_evidence"]["horizons"]["10"]["mature"][end - 11]
    assert not result["row_evidence"]["decision_observed"][end]
    early = int(np.flatnonzero(panel.dates == np.datetime64("2024-11-29"))[0])
    before = diagnose(panel, grades, eligible, as_of="2024-11-29T12:59:00-05:00")
    after = diagnose(panel, grades, eligible, as_of="2024-11-29T13:00:00-05:00")
    assert not before["row_evidence"]["decision_observed"][early]
    assert after["row_evidence"]["decision_observed"][early]


# Tied cross-sectional volatilities share the declared midpoint tercile.
def test_tied_volatility_midpoint_rank_and_missing_group():
    values = np.exp(np.arange(260)[:, None] * 0.001)
    prices = np.repeat(values, 4, axis=1)
    prices[:10, 3] = np.nan
    _, groups = d._volatility_groups(prices, np.ones(prices.shape, bool))
    np.testing.assert_array_equal(groups[-1], [1, 1, 1, -1])
    prices = np.exp(np.sin(np.arange(260)[:, None]) * np.array([[0.01, 0.02, 0.03]]))
    _, groups = d._volatility_groups(prices, np.ones(prices.shape, bool))
    np.testing.assert_array_equal(groups[-1], [0, 1, 2])


# Reject corrupted labels and monthly clocks rather than presenting false calibration.
@pytest.mark.parametrize("fault", ["label", "cutoff", "maximum", "forecast_support"])
def test_original_artifact_relationships_are_checked(fault):
    panel, grades, eligible = fixture()
    values = deepcopy(saved(panel, grades, eligible))
    prepared, relative, _, receipts = values
    if fault == "label":
        prepared["relative_labels"][900, 0] = -0.9
    elif fault == "cutoff":
        receipts["months"][-1]["label_end_before"] = "2099-01-01"
    elif fault == "maximum":
        receipts["months"][-1]["maximum_label_end"] = receipts["months"][-1]["fit_date"]
    else:
        relative[0, 0] = 0.2
    with pytest.raises(ValueError, match="reconcile|Monthly|forecasts"):
        diagnose(panel, grades, eligible, saved_values=values)


# Refuse unspecified observation timezone and price units.
def test_ambiguous_clock_and_basis_are_rejected():
    panel, grades, eligible = fixture()
    values = saved(panel, grades, eligible)
    with pytest.raises(ValueError, match="Timezone-aware"):
        diagnose(
            panel, grades, eligible, as_of=datetime(2026, 1, 1), saved_values=values
        )
    with pytest.raises(ValueError, match="price basis"):
        d.diagnose(
            panel.dates,
            panel.tickers,
            panel.open,
            panel.close,
            panel.adj_close,
            grades,
            eligible,
            *values[:3],
            values[3],
            {"selection": "reconstructed_current_vintage_not_historical_publications"},
            data_as_of=datetime(2026, 1, 1, tzinfo=ZoneInfo("America/New_York")),
            price_basis="raw_sip",
        )


# Population errors and the zero reference share identical matched rows.
def test_statistics_population_reference_and_undefined_correlation():
    result = d._statistics(
        np.ones(3, bool),
        np.array([1.0, 1.0, np.nan]),
        np.array([0.0, 2.0, 100.0]),
        np.ones(3, bool),
        np.zeros(3, bool),
        np.zeros(3, bool),
    )
    assert result["matched_rows"] == 2
    assert result["forecast_mse"] == 1
    assert result["zero_reference_mse"] == 2
    assert result["residual_variance"] == 1
    assert result["pearson"] is None
    assert result["forecast_unavailable"] == 1
