"""Adversarial causal-boundary tests and real CPU convex optimizer acceptance."""

import copy
from datetime import datetime, timedelta

import numpy as np
import pytest

from backend.market.specialist_risk import (
    NY,
    MonthlySelector,
    causal_regime,
    risk_sizing,
)


# Provide three completed prediction months with complete incremental expert utilities.
def history(gain=0.002):
    rows = []
    for month in (6, 7, 8):
        for day in range(1, 11):
            prediction = datetime(2026, month, day, 16, tzinfo=NY)
            end = prediction + timedelta(days=10)
            rows.append(
                {
                    "prediction_at": prediction.isoformat(),
                    "known_at": prediction.isoformat(),
                    "label_end": end.isoformat(),
                    "label_available_at": end.isoformat(),
                    "regime": "up_high",
                    "utilities": {"risk": gain, "path": -gain},
                }
            )
    return rows


# Build a six-name capped incumbent and dated deterministic trailing return sample.
def risk_inputs():
    rng = np.random.default_rng(82)
    values = rng.normal(0, 0.015, (290, 6))
    dates = np.arange("2025-08-01", "2026-10-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates)][-290:]
    values = values[: len(dates)]
    variance = np.mean(np.log1p(values[-20:]) ** 2, axis=0) * 4
    records = [
        {
            "status": "forecast",
            "target": "mean_squared_log_return",
            "prediction_at": "2026-09-30T16:00:00-04:00",
            "known_at": "2026-09-30T16:00:00-04:00",
            "horizon_end": "2026-10-14T16:00:00-04:00",
            "predicted_risk": float(v),
        }
        for v in variance
    ]
    return np.full(6, 1 / 6), values, records, dates


# A month fit admits no test-month label, late-published label or future prediction.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label_end", "2026-09-01T00:00:00-04:00"),
        ("label_available_at", "2026-09-01T00:00:00-04:00"),
        ("known_at", "2026-09-01T00:00:00-04:00"),
        ("prediction_at", "2026-09-01T00:00:00-04:00"),
    ],
)
def test_late_and_overlapping_outcomes_are_purged(field, value):
    rows = history()
    bad = copy.deepcopy(rows[-1])
    bad["prediction_at"] = "2026-08-25T16:00:00-04:00"
    bad["known_at"] = bad["prediction_at"]
    bad["label_end"] = "2026-08-31T16:00:00-04:00"
    bad["label_available_at"] = bad["label_end"]
    bad[field] = value
    if field == "prediction_at":
        bad.update(
            known_at=value,
            label_end="2026-09-11T00:00:00-04:00",
            label_available_at="2026-09-11T00:00:00-04:00",
        )
    if field == "label_end":
        bad["label_available_at"] = value
    bad["utilities"] = {"risk": -1e8, "path": 1e8}
    baseline = MonthlySelector(("risk", "path")).select(
        "2026-09-01T16:00:00-04:00", "up_high", rows
    )
    actual = MonthlySelector(("risk", "path")).select(
        "2026-09-30T16:00:00-04:00", "up_high", rows + [bad]
    )
    assert actual["weights"] == baseline["weights"]
    assert actual["training_sha256"] == baseline["training_sha256"]
    assert actual["purged_count"] == 1
    assert actual["training_count"] == 30


# Twenty overlapping short-window labels cannot masquerade as three months of history.
def test_short_history_falls_back_despite_many_overlapping_labels():
    rows = history()[-10:]
    rows += [
        dict(
            row,
            prediction_at=row["prediction_at"].replace("T16", "T15"),
            known_at=row["known_at"].replace("T16", "T15"),
        )
        for row in rows
    ]
    result = MonthlySelector(("risk", "path")).select(
        "2026-09-30T16:00:00-04:00", "up_high", rows
    )
    assert result["training_count"] == 20
    assert result["status"] == "incumbent_fallback"
    assert result["incumbent_weight"] == 1


# Later information and caller mutation cannot refit an already frozen month.
def test_month_frozen_and_next_month_refits():
    rows = history()
    selector = MonthlySelector(("risk", "path"))
    first = selector.select("2026-09-01T16:00:00-04:00", "up_high", rows)
    changed = history(-0.002)
    again = selector.select("2026-09-30T16:00:00-04:00", "up_high", changed)
    assert first == again
    again["weights"]["risk"] = 99
    assert selector.select("2026-09-30T16:00:00-04:00", "up_high", changed) == first
    next_month = selector.select("2026-10-01T16:00:00-04:00", "up_high", changed)
    assert next_month["weights"]["path"] > next_month["weights"]["risk"]
    assert next_month["training_sha256"] != first["training_sha256"]


# A harmful specialist receives no forced positive allocation or leveraged mixture.
def test_convex_fit_can_leave_incumbent_selected():
    rows = history()
    for row in rows:
        row["utilities"] = {"risk": -0.02, "path": -0.01}
    result = MonthlySelector(("risk", "path")).select(
        "2026-09-01T16:00:00-04:00", "up_high", rows
    )
    assert result["incumbent_weight"] > 0.999
    assert all(w >= 0 for w in result["weights"].values())
    assert sum(result["weights"].values()) + result[
        "incumbent_weight"
    ] == pytest.approx(1)


# Refuse bad publication chronology, duplicates and nonfinite utilities.
@pytest.mark.parametrize("defect", ["naive", "chronology", "duplicate", "nan"])
def test_training_rows_refuse_malformed_evidence(defect):
    rows = history()
    if defect == "naive":
        rows[0]["known_at"] = "2026-06-01T16:00:00"
    elif defect == "chronology":
        rows[0]["label_available_at"] = rows[0]["prediction_at"]
    elif defect == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    else:
        rows[0]["utilities"]["risk"] = float("nan")
    with pytest.raises(ValueError, match="timezone|chronology|Duplicate|Finite"):
        MonthlySelector(("risk", "path")).select(
            "2026-09-01T16:00:00-04:00", "up_high", rows
        )


# Keep missing expert outcomes unavailable without inventing zero utility.
def test_missing_expert_and_unknown_regime_keep_explicit_fallback():
    rows = history()
    for row in rows:
        row["utilities"].pop("path")
    selector = MonthlySelector(("risk", "path"))
    result = selector.select("2026-09-01T16:00:00-04:00", "up_high", rows)
    assert result["training_count"] == 0
    assert result["purged_count"] == 30
    assert (
        selector.select("2026-09-01T16:00:00-04:00", None, rows)["reason"]
        == "regime_unavailable"
    )


# Future prices cannot alter a past regime or its volatility threshold.
def test_regime_future_prefix_invariance_and_threshold():
    dates = np.arange("2025-01-01", "2026-01-01", dtype="datetime64[D]")
    moves = np.concatenate((np.full(273, 0.001), np.full(len(dates) - 273, 0.02)))
    prices = 100 * np.exp(np.cumsum(moves))
    first = causal_regime(dates, prices, 290)
    prices[291:] = 1e10
    assert first == causal_regime(dates, prices, 290)
    returns = np.diff(np.log(prices[18:291]))
    prior = [np.mean(returns[j : j + 20] ** 2) for j in range(252)]
    assert first["prior252_median"] == pytest.approx(np.median(prior))
    assert first["key"] == "up_high"
    assert causal_regime(dates, prices, 271)["status"] == "unavailable"


# Keep flat boundaries and missing prices explicit.
def test_regime_ambiguous_and_missing():
    dates = np.arange("2025-01-01", "2026-01-01", dtype="datetime64[D]")
    prices = np.ones(len(dates)) * 100
    assert causal_regime(dates, prices, 300)["status"] == "ambiguous"
    prices[200] = np.nan
    assert causal_regime(dates, prices, 300)["reason"] == "missing_regime_prices"


# Risk composition conserves gross unless the explicit no-leverage risk sleeve cuts it.
def test_actual_risk_optimizer_preserves_gross_and_compares_matched_exposure():
    base, values, records, dates = risk_inputs()
    same = risk_sizing(
        base, values, records, "2026-09-30T16:00:00-04:00", return_dates=dates
    )
    cut = risk_sizing(
        base,
        values,
        records,
        "2026-09-30T16:00:00-04:00",
        return_dates=dates,
        reduce_gross=True,
    )
    assert sum(same["weights"]) == pytest.approx(1)
    assert 0 < cut["gross_multiplier"] < 1
    assert sum(cut["weights"]) == pytest.approx(sum(cut["exposure_matched_control"]))
    assert np.all(np.asarray(cut["weights"]) >= 0)
    assert np.all(np.asarray(cut["weights"]) <= 0.25 + 1e-8)
    assert cut["gross_multiplier"] == pytest.approx(
        np.sqrt(cut["trailing20_variance"] / cut["forecast_variance"])
    )


# Dated covariance prefixes exclude future return values and preserve the same target.
def test_risk_future_return_prefix_invariance():
    base, values, records, dates = risk_inputs()
    first = risk_sizing(
        base, values, records, "2026-09-30T16:00:00-04:00", return_dates=dates
    )
    after = np.vstack((values, np.ones((1, 6)) * 9))
    future_dates = np.append(dates, np.datetime64("2026-10-01"))
    second = risk_sizing(
        base, after, records, "2026-09-30T16:00:00-04:00", return_dates=future_dates
    )
    assert first == second


# Covariance-only sizing needs no TTM forecasts and cannot quietly reduce gross.
def test_covariance_only_control_preserves_gross_without_forecasts():
    base, values, _, dates = risk_inputs()
    result = risk_sizing(
        base,
        values,
        [],
        "2026-09-30T16:00:00-04:00",
        return_dates=dates,
        covariance_only=True,
    )
    assert result["status"] == "sized"
    assert result["covariance_only"] is True
    assert sum(result["weights"]) == pytest.approx(1)
    assert result["exposure_matched_control"] == base.tolist()
    with pytest.raises(ValueError, match="must preserve gross"):
        risk_sizing(
            base,
            values,
            [],
            "2026-09-30T16:00:00-04:00",
            return_dates=dates,
            covariance_only=True,
            reduce_gross=True,
        )


# A return stamped with today's session is not completed before the regular close.
def test_intraday_covariance_does_not_read_todays_close():
    base, values, _, dates = risk_inputs()
    first = risk_sizing(
        base,
        values,
        [],
        "2026-09-30T15:00:00-04:00",
        return_dates=dates,
        covariance_only=True,
    )
    values[-1] = 9
    second = risk_sizing(
        base,
        values,
        [],
        "2026-09-30T15:00:00-04:00",
        return_dates=dates,
        covariance_only=True,
    )
    assert first == second


# Refuse a supplied regime whose features postdate the selection.
def test_selector_accepts_causal_dict_and_refuses_future_regime():
    selector = MonthlySelector(("risk", "path"))
    regime = {
        "status": "available",
        "key": "up_high",
        "information_through": "2026-09-01",
    }
    assert (
        selector.select("2026-09-01T16:00:00-04:00", regime, history())["status"]
        == "fitted"
    )
    regime["information_through"] = "2026-09-02"
    with pytest.raises(ValueError, match="Regime features"):
        selector.select("2026-09-01T16:00:00-04:00", regime, history())


# Preserve incumbent when TTM outputs are missing, late or expired.
@pytest.mark.parametrize(
    ("defect", "reason"),
    [
        ("missing", "missing_ttm_forecast"),
        ("late", "risk_forecast_not_available"),
        ("expired", "risk_forecast_expired"),
        ("dates", "missing_return_dates"),
    ],
)
def test_risk_unavailable_never_invents_cash(defect, reason):
    base, values, records, dates = risk_inputs()
    if defect == "missing":
        records[0] = None
    elif defect == "late":
        records[0]["known_at"] = "2026-10-01T16:00:00-04:00"
    elif defect == "expired":
        records[0]["horizon_end"] = "2026-09-30T16:00:01-04:00"
    result = risk_sizing(
        base,
        values,
        records,
        "2026-09-30T17:00:00-04:00",
        return_dates=None if defect == "dates" else dates,
    )
    assert result["reason"] == reason
    assert result["weights"] == base.tolist()


# Nonfinite risk targets and over-cap incumbent weights cannot reach the optimizer.
def test_risk_refuses_invalid_target_and_base():
    base, values, records, dates = risk_inputs()
    records[0]["predicted_risk"] = float("inf")
    with pytest.raises(ValueError, match="Finite nonnegative"):
        risk_sizing(
            base, values, records, "2026-09-30T16:00:00-04:00", return_dates=dates
        )
    with pytest.raises(ValueError, match="Long-only capped"):
        risk_sizing(
            [1, 0, 0, 0, 0, 0],
            values,
            records,
            "2026-09-30T16:00:00-04:00",
            return_dates=dates,
        )


# Actual skfolio zero and near-zero covariance refusals retain funded incumbent intent.
@pytest.mark.parametrize("amplitude", [0.0, 1e-9])
@pytest.mark.parametrize("covariance_only", [False, True])
def test_degenerate_covariance_keeps_incumbent(amplitude, covariance_only):
    base, values, records, dates = risk_inputs()
    values *= amplitude
    result = risk_sizing(
        base,
        values,
        [] if covariance_only else records,
        "2026-09-30T16:00:00-04:00",
        return_dates=dates,
        covariance_only=covariance_only,
        reduce_gross=not covariance_only,
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "degenerate_covariance"
    assert result["weights"] == base.tolist()
    assert result["exposure_matched_control"] == base.tolist()
    assert result["gross_multiplier"] == 1


# An unrelated estimator failure remains a refusal rather than a cash or risk fallback.
def test_unrelated_estimator_error_is_not_swallowed(monkeypatch):
    from skfolio.prior import EmpiricalPrior

    # Simulate invalid estimator setup at the actual prior fitting boundary.
    def invalid_fit(self, *args, **kwargs):
        raise ValueError("invalid estimator setup")

    monkeypatch.setattr(EmpiricalPrior, "fit", invalid_fit)
    base, values, _, dates = risk_inputs()
    with pytest.raises(ValueError, match="invalid estimator setup"):
        risk_sizing(
            base, values, [], "2026-09-30T16:00:00-04:00",
            return_dates=dates, covariance_only=True,
        )


# A training outcome must follow its prediction by a strictly positive horizon.
@pytest.mark.parametrize(
    "label_end", ["2026-06-01T16:00:00-04:00", "2026-06-01T15:59:59-04:00"]
)
def test_zero_or_backward_label_horizon_is_refused(label_end):
    rows = history()
    rows[0]["label_end"] = label_end
    with pytest.raises(ValueError, match="chronology"):
        MonthlySelector(("risk", "path")).select(
            "2026-09-01T16:00:00-04:00", "up_high", rows
        )


# Valid strictly positive matured labels remain admitted without rewriting evidence.
def test_positive_label_horizons_remain_unchanged():
    rows = history()
    original = copy.deepcopy(rows)
    result = MonthlySelector(("risk", "path")).select(
        "2026-09-01T16:00:00-04:00", "up_high", rows
    )
    assert result["status"] == "fitted"
    assert result["training_count"] == len(rows)
    assert rows == original
