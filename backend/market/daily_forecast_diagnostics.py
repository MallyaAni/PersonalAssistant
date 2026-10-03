"""Inspect saved daily forecasts without fitting, selecting a policy or trading.

The caller authenticates original files. This module checks their supplied-array
relationships and simulated training clocks; no historical publication clock
is inferred. Twenty-session outcomes are compatibility diagnostics only.
"""

from __future__ import annotations

from datetime import datetime, time

import numpy as np

from backend.market import calendar

PRICE_BASIS = "original_store_daily_ohlc_basis_preserved_without_conversion"
FIRST = np.datetime64("2018-02-01")
LAST = np.datetime64("2026-09-30")
FREEZE = np.datetime64("2026-08-17")
WINDOWS = {
    "all": (FIRST, LAST),
    "2018_2020": (FIRST, np.datetime64("2020-12-31")),
    "2021_2026": (np.datetime64("2021-01-01"), LAST),
    "reused_2026_08_17_09_30": (FREEZE, LAST),
}


# Reject ambiguous observation times rather than assuming a publication clock.
def _as_of(value):
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    if (
        not isinstance(instant, datetime)
        or instant.tzinfo is None
        or instant.utcoffset() is None
    ):
        raise ValueError("Timezone-aware data_as_of required")
    return instant.astimezone(calendar.NEW_YORK)


# Compare missing values explicitly while allowing only arithmetic rounding.
def _same_values(actual, expected, name):
    if np.shape(actual) != np.shape(expected) or not np.allclose(
        actual, expected, rtol=1e-12, atol=1e-12, equal_nan=True
    ):
        raise ValueError(f"Original prepared {name} does not reconcile")


# Reconstruct exact next-open endpoints without coupling stock returns to SPY.
def _labels(opens, dates, spy, horizon):
    shape = opens.shape
    absolute = np.full(shape, np.nan)
    end_dates = np.full(len(dates), np.datetime64("NaT", "D"))
    start_missing = np.zeros(shape, bool)
    end_missing = np.zeros(shape, bool)
    count = max(0, len(dates) - horizon - 1)
    if count:
        start = opens[1 : count + 1]
        end = opens[horizon + 1 :]
        start_missing[:count] = ~np.isfinite(start)
        end_missing[:count] = ~np.isfinite(end)
        known = np.isfinite(start) & np.isfinite(end)
        absolute[:count][known] = np.log(end[known] / start[known])
        end_dates[:count] = dates[horizon + 1 :]
    market = absolute[:, spy].copy()
    relative = absolute - market[:, None]
    return absolute, relative, market, end_dates, start_missing, end_missing


# Check supplied monthly causal clocks; original model certification is external.
def _fit_clocks(prepared, dates, symbols, receipts, relative, spy_values):
    identity = receipts.get("identity", {})
    if (
        identity.get("policy") != "learned-held-b-forecast/1"
        or identity.get("minimum_days") != 504
        or identity.get("maximum_days") != 756
        or identity.get("label_end") != 11
        or identity.get("holdout_end_before") != str(FREEZE)
        or identity.get("symbols") != list(symbols)
    ):
        raise ValueError("Original daily fit identity required")
    months = dates.astype("datetime64[M]")
    supplied = receipts.get("months", [])
    if [row.get("month") for row in supplied] != [str(m) for m in np.unique(months)]:
        raise ValueError("Exact chronological monthly fit receipts required")
    endpoint = np.asarray(prepared["label_end_dates"])
    summary = []
    for receipt, month in zip(supplied, np.unique(months), strict=True):
        scored = np.flatnonzero(months == month)
        first = int(scored[0])
        cutoff = min(dates[first], FREEZE)
        days = np.arange(max(0, first - 756), first, dtype=np.int64)
        days = days[~np.isnat(endpoint[days]) & (endpoint[days] < cutoff)]
        maximum = str(endpoint[days[-1]]) if len(days) else None
        if (
            receipt.get("fit_date") != str(dates[first])
            or receipt.get("label_end_before") != str(cutoff)
            or receipt.get("maximum_label_end") != maximum
        ):
            raise ValueError("Monthly fit cutoff or maximum matured endpoint mismatch")
        for head, label_key, valid_key, forecast in (
            ("stock", "relative_labels", "valid", relative),
            ("spy", "spy_labels", "spy_valid", spy_values),
        ):
            labels = np.asarray(prepared[label_key])
            valid = np.asarray(prepared[valid_key])
            if head == "spy":
                labels, valid = labels[:, None], valid[:, None]
            known_dates = int(
                np.any(valid[days] & np.isfinite(labels[days]), axis=1).sum()
            )
            record = receipt.get(head, {})
            status = record.get("status")
            if (
                status
                not in (
                    "fitted",
                    "insufficient_mature_history",
                    "no_observed_training_features",
                )
                or record.get("training_days") != known_dates
                or (status == "fitted" and known_dates < 504)
            ):
                raise ValueError("Invalid monthly fit status or warmup")
            if status != "fitted" and np.isfinite(forecast[scored]).any():
                raise ValueError("Unavailable monthly head has finite forecasts")
        summary.append(
            {
                "month": str(month),
                "fit_date": str(dates[first]),
                "label_end_before": str(cutoff),
                "maximum_label_end": maximum,
                "publication_status": (
                    "simulated_maturity_only_no_original_publication_clock"
                ),
            }
        )
    return summary


# Give tied eligible volatilities one midpoint rank and one shared tercile.
def _volatility_groups(prices, members):
    volatility = np.full(prices.shape, np.nan)
    groups = np.full(prices.shape, -1, dtype=np.int8)
    for day in range(252, len(prices)):
        history = prices[day - 252 : day + 1]
        known = np.isfinite(history).all(axis=0)
        if known.any():
            volatility[day, known] = np.std(
                np.diff(np.log(history[:, known]), axis=0), axis=0
            )
        chosen = np.flatnonzero(members[day] & np.isfinite(volatility[day]))
        values = volatility[day, chosen]
        if len(chosen):
            ranks = (
                (values[None, :] < values[:, None]).sum(axis=1)
                + 0.5 * (values[None, :] == values[:, None]).sum(axis=1)
            ) / len(chosen)
            groups[day, chosen] = np.where(
                ranks <= 1 / 3, 0, np.where(ranks <= 2 / 3, 1, 2)
            )
    return volatility, groups


# Calculate descriptive population errors on exactly the same matched rows.
def _statistics(opportunities, forecasts, actual, mature, start_missing, end_missing):
    finite = np.isfinite(forecasts)
    known = np.isfinite(actual)
    matched = opportunities & finite & mature & known
    prediction, realization = forecasts[matched], actual[matched]
    result = {
        "opportunities": int(opportunities.sum()),
        "finite_forecasts": int((opportunities & finite).sum()),
        "forecast_unavailable": int((opportunities & ~finite).sum()),
        "mature_endpoints": int((opportunities & mature).sum()),
        "mature_labels": int((opportunities & mature & known).sum()),
        "immature_outcomes": int((opportunities & ~mature).sum()),
        "missing_start_prices": int((opportunities & mature & start_missing).sum()),
        "missing_end_prices": int((opportunities & mature & end_missing).sum()),
        "matched_rows": int(matched.sum()),
    }
    for key in (
        "mean_prediction",
        "mean_realized_log_return",
        "mean_error",
        "mae",
        "rmse",
        "residual_variance",
        "pearson",
        "forecast_mse",
        "zero_reference_mse",
    ):
        result[key] = None
    if len(prediction):
        error = prediction - realization
        result.update(
            {
                "mean_prediction": float(prediction.mean()),
                "mean_realized_log_return": float(realization.mean()),
                "mean_error": float(error.mean()),
                "mae": float(np.abs(error).mean()),
                "rmse": float(np.sqrt(np.mean(error**2))),
                "residual_variance": float(np.var(error)),
                "forecast_mse": float(np.mean(error**2)),
                "zero_reference_mse": float(np.mean(realization**2)),
            }
        )
        if (
            len(prediction) > 1
            and np.ptp(prediction) > 0
            and np.ptp(realization) > 0
            and np.std(prediction) > 0
            and np.std(realization) > 0
        ):
            result["pearson"] = float(np.corrcoef(prediction, realization)[0, 1])
    return result


# Validate aligned original daily inputs without altering their preserved basis.
def _validate_daily(
    dates,
    names,
    open_prices,
    close_prices,
    adjusted_close,
    grades,
    eligible,
    provenance,
):
    if (
        dates.ndim != 1
        or dates.dtype != np.dtype("datetime64[D]")
        or not len(dates)
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
        or len(set(names)) != len(names)
        or "SPY" not in names
        or not all(isinstance(name, str) and name for name in names)
    ):
        raise ValueError(
            "Chronological complete supplied calendar and unique symbols required"
        )
    shape = (len(dates), len(names))
    prices = []
    for supplied in (open_prices, close_prices, adjusted_close):
        value = np.asarray(supplied)
        if (
            value.shape != shape
            or value.dtype.kind not in "fiu"
            or np.isinf(value).any()
            or np.any(np.isfinite(value) & (value <= 0))
        ):
            raise ValueError("Positive-or-missing aligned daily prices required")
        prices.append(value)
    if (
        grades.shape != shape
        or grades.dtype.kind not in "fiu"
        or not np.isfinite(grades).all()
        or np.any(~np.isin(grades, [-1, 0, 1, 2, 3]))
        or eligible.shape != shape
        or eligible.dtype.kind != "b"
    ):
        raise ValueError("Aligned ordinal grades and boolean eligibility required")
    stock = np.array([name not in ("SPY", "QQQ") for name in names])
    if not stock.any() or not isinstance(provenance, dict) or not provenance:
        raise ValueError("Declared stock book and original provenance required")
    if (
        provenance.get("selection")
        != "reconstructed_current_vintage_not_historical_publications"
    ):
        raise ValueError("Original current-vintage reconstruction disclosure required")
    return prices, stock


# Keep original causal eligibility separate from later label availability.
def _validate_prepared(
    prepared, dates, names, grades, eligible, relative_forecasts, spy_forecasts
):
    shape = (len(dates), len(names))
    stock = np.array([name not in ("SPY", "QQQ") for name in names])
    if not np.array_equal(prepared["dates"], dates):
        raise ValueError("Original prepared calendar mismatch")
    for key, expected in (
        ("valid", shape),
        ("spy_valid", (len(dates),)),
        ("training_symbols", (len(names),)),
    ):
        values = np.asarray(prepared[key])
        if values.shape != expected or values.dtype.kind != "b":
            raise ValueError("Original boolean prepared masks required")
    if (
        np.shape(prepared["X"]) != (*shape, 13)
        or not np.array_equal(prepared["training_symbols"], stock)
        or np.any(
            np.asarray(prepared["valid"]) & ~(eligible & stock[None, :] & (grades >= 0))
        )
    ):
        raise ValueError("Original features or prediction eligibility mismatch")
    for forecast, expected, mask in (
        (relative_forecasts, shape, prepared["valid"]),
        (spy_forecasts, (len(dates),), prepared["spy_valid"]),
    ):
        if (
            forecast.shape != expected
            or forecast.dtype.kind != "f"
            or np.isinf(forecast).any()
            or np.any(np.isfinite(forecast) & ~mask)
        ):
            raise ValueError("Original finite-or-missing valid-row forecasts required")


# Diagnose authenticated saved heads while retaining every causal opportunity.
def diagnose(
    dates,
    symbols,
    open_prices,
    close_prices,
    adjusted_close,
    grades,
    eligible,
    prepared,
    relative_forecasts,
    spy_forecasts,
    fit_receipts,
    provenance,
    *,
    data_as_of,
    price_basis,
):
    as_of = _as_of(data_as_of)
    if price_basis != PRICE_BASIS:
        raise ValueError("Explicit original daily price basis required")
    dates, names = np.asarray(dates), tuple(symbols)
    grades, eligible = np.asarray(grades), np.asarray(eligible)
    relative_forecasts = np.asarray(relative_forecasts)
    spy_forecasts = np.asarray(spy_forecasts)
    prices, stock = _validate_daily(
        dates,
        names,
        open_prices,
        close_prices,
        adjusted_close,
        grades,
        eligible,
        provenance,
    )
    _validate_prepared(
        prepared,
        dates,
        names,
        grades,
        eligible,
        relative_forecasts,
        spy_forecasts,
    )
    opens = prices[0] * prices[2] / prices[1]
    spy = names.index("SPY")
    ten = _labels(opens, dates, spy, 10)
    _same_values(prepared["relative_labels"], ten[1], "relative labels")
    _same_values(prepared["spy_labels"], ten[2], "SPY labels")
    if not np.array_equal(
        np.asarray(prepared["label_end_dates"]).view("i8"), ten[3].view("i8")
    ):
        raise ValueError("Original prepared opening endpoints mismatch")
    clocks = _fit_clocks(
        prepared, dates, names, fit_receipts, relative_forecasts, spy_forecasts
    )
    observed = np.array(
        [
            datetime.combine(day, calendar.session_close(day), calendar.NEW_YORK)
            <= as_of
            for day in dates.astype(object)
        ]
    )
    in_cohort = observed & (dates >= FIRST) & (dates <= LAST)
    members = eligible & stock[None, :]
    cohorts = {
        "eligible": members & in_cohort[:, None],
        "eligible_A": members & (grades >= 2) & in_cohort[:, None],
    }
    volatility, groups = _volatility_groups(prices[2], members)
    # Unobserved histories are never exposed as contemporaneously known groups.
    groups[~observed] = -1
    volatility[~observed] = np.nan
    absolute_forecasts = relative_forecasts + spy_forecasts[:, None]
    horizons, summaries, per_stock = {}, {}, {}
    for horizon, labels in ((10, ten), (20, _labels(opens, dates, spy, 20))):
        absolute, relative, market, end_dates, start_missing, end_missing = labels
        mature = np.array(
            [
                False
                if np.isnat(end)
                else datetime.combine(
                    end.astype(object), time(9, 30), calendar.NEW_YORK
                )
                <= as_of
                for end in end_dates
            ]
        )
        absolute, relative, market = absolute.copy(), relative.copy(), market.copy()
        absolute[~mature], relative[~mature], market[~mature] = np.nan, np.nan, np.nan
        relative_start = start_missing | start_missing[:, spy, None]
        relative_end = end_missing | end_missing[:, spy, None]
        horizons[str(horizon)] = {
            "end_dates": end_dates,
            "mature": mature,
            "absolute": absolute,
            "relative": relative,
            "spy": market,
            "start_missing": start_missing,
            "end_missing": end_missing,
        }
        heads = (
            ("absolute", absolute_forecasts, absolute, start_missing, end_missing),
            ("relative", relative_forecasts, relative, relative_start, relative_end),
        )
        summaries[str(horizon)] = _window_stats(
            dates,
            cohorts,
            heads,
            groups,
            in_cohort,
            spy_forecasts,
            market,
            mature,
            start_missing[:, spy],
            end_missing[:, spy],
        )
        per_stock[str(horizon)] = _stock_stats(names, stock, cohorts, heads, mature)
    return {
        "schema": "daily-forecast-calibration/1",
        "data_as_of": as_of.isoformat(),
        "price_basis": price_basis,
        "forecast_horizon_sessions": 10,
        "outcome_horizons": {
            "10": "exact_registered_target",
            "20": "horizon_compatibility_only",
        },
        "selection": provenance["selection"],
        "symbols": list(names),
        "stock_symbols": [
            name for name, is_stock in zip(names, stock, strict=True) if is_stock
        ],
        "publication_status": "simulated_fit_maturity_not_historical_publication",
        "volatility_rank": (
            "(strictly_less+0.5*equal)/eligible_known_count; <=1/3 low; <=2/3 middle"
        ),
        "limitations": [
            "Reused data; not a new untouched out-of-sample test.",
            "Current-vintage grades and membership; "
            "original publication times unavailable.",
            "Overlapping stock labels are not independent trials.",
            "Open-to-open outcomes do not establish intraday returns "
            "or profitable execution.",
            "Twenty-session outcomes do not evaluate a fitted twenty-session forecast.",
        ],
        "fit_clocks": clocks,
        "statistics": summaries,
        "per_stock": per_stock,
        "row_evidence": {
            "decision_observed": observed,
            "cohort_masks": cohorts,
            "volatility_group": groups,
            "volatility252": volatility,
            "horizons": horizons,
        },
    }


# Preserve every predeclared window, cohort and descriptive volatility group.
def _window_stats(
    dates,
    cohorts,
    heads,
    groups,
    in_cohort,
    spy_forecasts,
    market,
    mature,
    spy_start_missing,
    spy_end_missing,
):
    summaries = {}
    for window, (first, last) in WINDOWS.items():
        day_mask = (dates >= first) & (dates <= last)
        result = {}
        for cohort, opportunities in cohorts.items():
            own = opportunities & day_mask[:, None]
            result[cohort] = {}
            for head, forecast, actual, missing_start, missing_end in heads:
                by_group = {}
                for group, code in (
                    ("all", None),
                    ("low", 0),
                    ("middle", 1),
                    ("high", 2),
                    ("history_unavailable", -1),
                ):
                    selected = own if code is None else own & (groups == code)
                    stats = _statistics(
                        selected,
                        forecast,
                        actual,
                        mature[:, None],
                        missing_start,
                        missing_end,
                    )
                    stats["volatility_history_unavailable"] = int(
                        (selected & (groups == -1)).sum()
                    )
                    by_group[group] = stats
                result[cohort][head] = by_group
        result["spy"] = _statistics(
            in_cohort & day_mask,
            spy_forecasts,
            market,
            mature,
            spy_start_missing,
            spy_end_missing,
        )
        summaries[window] = result
    return summaries


# Retain all original stock names without selecting a subset from their errors.
def _stock_stats(names, stock, cohorts, heads, mature):
    return {
        names[column]: {
            cohort: {
                head: _statistics(
                    opportunities[:, column],
                    forecast[:, column],
                    actual[:, column],
                    mature,
                    missing_start[:, column],
                    missing_end[:, column],
                )
                for head, forecast, actual, missing_start, missing_end in heads
            }
            for cohort, opportunities in cohorts.items()
        }
        for column in np.flatnonzero(stock)
    }
