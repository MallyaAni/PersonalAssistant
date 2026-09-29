"""Offline filing forecasts on original-byte, unit-preserving financial data.

No live loader, strategy, schedule or broker is changed. Historical rows are
reconstructed from a later snapshot, not certified historical acquisitions.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import numpy as np

from backend.market import fundamental_features as ff
from backend.market import qualified_fundamentals as qualified

FEATURES = (*ff.FEATURE_NAMES, "prior_period_age_days")
PLAN = "docs/research/earnings-events-plan-2026-09-29.md"
MIN_FIT = 300
MIN_VALID = 40
FIRST_YEAR = 2019
LAST_YEAR = 2026
LGBM_PARAMS = {
    "objective": "regression",
    "metric": "l2",
    "num_leaves": 7,
    "learning_rate": 0.03,
    "min_data_in_leaf": 30,
    "lambda_l2": 10.0,
    "seed": 7,
    "num_threads": 2,
    "verbosity": -1,
    "deterministic": True,
    "force_col_wise": True,
}


# Preserve missing financial values instead of asserting an economic zero.
def _values(observation):
    return [observation["features"][name]["value"] for name in ff.FEATURE_NAMES]


# Reconstruct one first-disclosure event per new quarter with strictly prior inputs.
def source_events(ticker, source, cutoff):
    events, rejected, seen = [], Counter(), set()
    days = sorted(
        {
            fact.version.available
            for fact in source.facts
            if fact.version.name == "revenue" and fact.version.available <= cutoff
        }
    )
    for day in days:
        current = qualified._observation(ticker, day, source)
        end = current["revenue_period_end"]
        if end is None or end in seen:
            continue
        seen.add(end)
        before = day - timedelta(days=1)
        prior = qualified._observation(ticker, before, source)
        previous_end = prior["revenue_period_end"]
        target = current["features"]["revenue_yoy"]
        baseline = prior["features"]["revenue_yoy"]
        if target["value"] is None:
            rejected[f"target:{target['status']}"] += 1
            continue
        if baseline["value"] is None or previous_end is None:
            rejected[f"baseline:{baseline['status']}"] += 1
            continue
        distance = (date.fromisoformat(end) - date.fromisoformat(previous_end)).days
        if not 70 <= distance <= 115:
            rejected["nonconsecutive_prior_quarter"] += 1
            continue
        features = _values(prior)
        features.append((before - date.fromisoformat(previous_end)).days)
        events.append(
            {
                "ticker": ticker,
                "cik": source.cik,
                "source_sha256": source.sha256,
                "feature_date": before.isoformat(),
                "available": day.isoformat(),
                "period_end": end,
                "previous_period_end": previous_end,
                "x": features,
                "target": target["value"],
                "baseline": baseline["value"],
                "post_features": _values(current),
                "target_evidence": target,
                "feature_evidence": prior["features"],
            }
        )
    return events, dict(rejected)


# Check event identity and chronology before any fitting or scoring occurs.
def validate_events(events):
    seen = set()
    for row in events:
        identity = row["cik"], row["period_end"]
        if identity in seen:
            raise ValueError("duplicate issuer-quarter event")
        seen.add(identity)
        feature = date.fromisoformat(row["feature_date"])
        available = date.fromisoformat(row["available"])
        if feature >= available:
            raise ValueError("features must precede target availability")
        if len(row["x"]) != len(FEATURES):
            raise ValueError("unexpected feature columns")
        if not np.isfinite([row["target"], row["baseline"]]).all():
            raise ValueError("finite target and persistence baseline required")
        if row["x"][0] != row["baseline"]:
            raise ValueError("persistence must equal the prior known growth")


# Learn clipping, imputation and scale from fit rows alone, including empty columns.
def fit_transform(x):
    x = np.asarray(x, dtype=float)
    if x.ndim != 2 or not len(x):
        raise ValueError("nonempty fit matrix required")
    columns = []
    for column in x.T:
        finite = column[np.isfinite(column)]
        if not len(finite):
            columns.append((0.0, 0.0, 0.0, 1.0))
            continue
        lo, q1, med, q3, hi = np.quantile(finite, [0.005, 0.25, 0.5, 0.75, 0.995])
        columns.append((lo, hi, med, q3 - q1 if q3 > q1 else 1.0))
    return np.asarray(columns)


# Apply frozen fit-only bounds and retain missingness as separate model inputs.
def transform(x, parameters):
    x = np.asarray(x, dtype=float)
    missing = ~np.isfinite(x)
    lo, hi, med, scale = parameters.T
    filled = np.where(missing, med, x)
    normalized = (np.clip(filled, lo, hi) - med) / scale
    return np.concatenate((normalized, missing.astype(float)), axis=1)


# Select annual fit and validation blocks using actual target availability dates.
def split(events, year):
    feature_dates = np.array([r["feature_date"] for r in events], dtype="datetime64[D]")
    available = np.array([r["available"] for r in events], dtype="datetime64[D]")
    cutoff = np.datetime64(f"{year}-01-01")
    validation = np.datetime64(f"{year - 1}-01-01")
    next_year = np.datetime64(f"{year + 1}-01-01")
    return {
        "fit": available < cutoff,
        "inner_fit": available < validation,
        "validation": (feature_dates >= validation) & (available < cutoff),
        "test": (feature_dates >= cutoff) & (feature_dates < next_year),
    }


# Require enough distinct published events and years, not duplicated daily rows.
def _enough(mask, events, minimum=MIN_FIT):
    years = {events[i]["available"][:4] for i in np.flatnonzero(mask)}
    return int(mask.sum()) >= minimum and len(years) >= 3


# Fit both registered residual models without selecting anything on scored outcomes.
def walk_forward(events):
    from sklearn.linear_model import Ridge

    validate_events(events)
    x = np.array([r["x"] for r in events], dtype=float).reshape(-1, len(FEATURES))
    target = np.array([r["target"] for r in events])
    base = np.array([r["baseline"] for r in events])
    residual = target - base
    predictions = {name: np.full(len(events), np.nan) for name in ("ridge", "lightgbm")}
    receipts = []
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        blocks = split(events, year)
        fit, test = blocks["fit"], blocks["test"]
        receipt = {"year": year, **{k: int(v.sum()) for k, v in blocks.items()}}
        if not test.any() or not _enough(fit, events):
            receipt["status"] = "insufficient_fit_or_test"
            receipts.append(receipt)
            continue
        params = fit_transform(x[fit])
        ridge = Ridge(alpha=10.0).fit(transform(x[fit], params), residual[fit])
        predictions["ridge"][test] = base[test] + ridge.predict(
            transform(x[test], params)
        )
        receipt.update(
            status="ridge_scored",
            fit_latest_available=max(
                events[i]["available"] for i in np.flatnonzero(fit)
            ),
            test_first_feature=min(
                events[i]["feature_date"] for i in np.flatnonzero(test)
            ),
            preprocessing=params.tolist(),
            ridge_coefficients=ridge.coef_.tolist(),
            ridge_intercept=float(ridge.intercept_),
        )
        inner, valid = blocks["inner_fit"], blocks["validation"]
        if _enough(inner, events) and valid.sum() >= MIN_VALID:
            import lightgbm as lgb

            inner_params = fit_transform(x[inner])
            trial = lgb.train(
                LGBM_PARAMS,
                lgb.Dataset(transform(x[inner], inner_params), label=residual[inner]),
                num_boost_round=500,
                valid_sets=[
                    lgb.Dataset(
                        transform(x[valid], inner_params), label=residual[valid]
                    )
                ],
                callbacks=[lgb.early_stopping(40, verbose=False)],
            )
            model = lgb.train(
                LGBM_PARAMS,
                lgb.Dataset(transform(x[fit], params), label=residual[fit]),
                num_boost_round=trial.best_iteration,
            )
            predictions["lightgbm"][test] = base[test] + model.predict(
                transform(x[test], params)
            )
            receipt.update(
                status="both_scored",
                best_iteration=trial.best_iteration,
                validation_mse=float(trial.best_score["valid_0"]["l2"]),
                inner_latest_available=max(
                    events[i]["available"] for i in np.flatnonzero(inner)
                ),
                validation_first_feature=min(
                    events[i]["feature_date"] for i in np.flatnonzero(valid)
                ),
                lightgbm_model=model.model_to_string(),
            )
        else:
            receipt["lightgbm_status"] = "insufficient_inner_fit_or_validation"
        receipts.append(receipt)
    return predictions, receipts


# Resample whole fixed calendar blocks so events on the same date stay together.
def benefit_interval(days, benefits):
    days = np.asarray(days, dtype="datetime64[D]").astype(np.int64)
    benefits = np.asarray(benefits, dtype=float)
    if not len(days):
        return [None, None]
    block = (days - np.datetime64("2000-01-01", "D").astype(np.int64)) // 63
    keys, inverse = np.unique(block, return_inverse=True)
    if len(keys) < 8:
        return [None, None]
    sums = np.bincount(inverse, weights=benefits)
    counts = np.bincount(inverse)
    rng = np.random.default_rng(7)
    draws = rng.integers(0, len(keys), (2000, len(keys)))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return np.quantile(means, [0.025, 0.975]).tolist()


# Score each model against persistence on exactly its own scored, finite event rows.
def summarize(events, predictions):
    target = np.array([r["target"] for r in events])
    baseline = np.array([r["baseline"] for r in events])
    years = np.array([int(r["feature_date"][:4]) for r in events])
    days = np.array([r["available"] for r in events], dtype="datetime64[D]")
    results = {}
    for name, values in predictions.items():
        mask = np.isfinite(values)
        if not mask.any():
            results[name] = {"events": 0, "verdict": "INSUFFICIENT_DATA"}
            continue
        error = values[mask] - target[mask]
        base_error = baseline[mask] - target[mask]
        mse, base_mse = float(np.mean(error**2)), float(np.mean(base_error**2))
        mae, base_mae = float(np.mean(abs(error))), float(np.mean(abs(base_error)))
        annual = []
        for year in sorted(set(years[mask])):
            on = years[mask] == year
            annual.append(
                {
                    "year": int(year),
                    "events": int(on.sum()),
                    "mse": float(np.mean(error[on] ** 2)),
                    "baseline_mse": float(np.mean(base_error[on] ** 2)),
                    "mae": float(np.mean(abs(error[on]))),
                    "baseline_mae": float(np.mean(abs(base_error[on]))),
                }
            )
        interval = benefit_interval(days[mask], base_error**2 - error**2)
        improving = sum(
            r["mse"] < r["baseline_mse"] and r["mae"] < r["baseline_mae"]
            for r in annual
        )
        passed = (
            int(mask.sum()) >= 500
            and mse <= 0.98 * base_mse
            and mae <= 0.98 * base_mae
            and improving > len(annual) / 2
            and interval[0] is not None
            and interval[0] > 0
        )
        results[name] = {
            "events": int(mask.sum()),
            "issuers": len({events[i]["cik"] for i in np.flatnonzero(mask)}),
            "mse": mse,
            "baseline_mse": base_mse,
            "mae": mae,
            "baseline_mae": base_mae,
            "median_absolute_error": float(np.median(abs(error))),
            "baseline_median_absolute_error": float(np.median(abs(base_error))),
            "mse_improvement_pct": 100 * (1 - mse / base_mse) if base_mse else None,
            "mae_improvement_pct": 100 * (1 - mae / base_mae) if base_mae else None,
            "squared_error_benefit_95pct": interval,
            "annual": annual,
            "years_improved_both": improving,
            "raw_abs_target_over_one": int((abs(target[mask]) > 1).sum()),
            "raw_abs_baseline_error_over_one": int((abs(base_error) > 1).sum()),
            "verdict": "ACCURACY_GATE_PASSED_NOT_PROMOTION"
            if passed
            else "DO_NOT_ADVANCE",
        }
    return results


# Attach gross stock and index returns with identical post-information open endpoints.
def event_returns(events, panel, horizon=20):
    if horizon < 1:
        raise ValueError("positive horizon required")
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    with np.errstate(divide="ignore", invalid="ignore"):
        adjusted_open = panel.open * panel.adj_close / panel.close
    index = {ticker: i for i, ticker in enumerate(panel.tickers)}
    result = []
    for event in events:
        start = int(
            np.searchsorted(dates, np.datetime64(event["available"]), side="right")
        )
        end = start + horizon
        row = {"entry": None, "exit": None, "stock": None, "SPY": None, "QQQ": None}
        if end >= len(dates):
            row["status"] = "immature"
        else:
            row.update(entry=str(dates[start]), exit=str(dates[end]), status="priced")
            for label, ticker in (
                ("stock", event["ticker"]),
                ("SPY", "SPY"),
                ("QQQ", "QQQ"),
            ):
                column = index.get(ticker)
                prices = (
                    adjusted_open[[start, end], column]
                    if column is not None
                    else np.array([np.nan])
                )
                if (
                    len(prices) == 2
                    and np.isfinite(prices).all()
                    and (prices > 0).all()
                ):
                    row[label] = float(np.log(prices[1]) - np.log(prices[0]))
                else:
                    row["status"] = "missing_price"
        result.append(row)
    return result


# Describe forecast-error association without choosing trade thresholds from outcomes.
def return_diagnostics(events, predictions, returns):
    from scipy.stats import spearmanr

    target = np.array([r["target"] for r in events])
    forecasts = {
        "persistence": np.array([r["baseline"] for r in events]),
        **predictions,
    }
    output = {}
    for name, pred in forecasts.items():
        by_index = {}
        for benchmark in ("SPY", "QQQ"):
            valid = [
                i
                for i, row in enumerate(returns)
                if np.isfinite(pred[i])
                and row["stock"] is not None
                and row[benchmark] is not None
            ]
            surprise = target[valid] - pred[valid]
            baseline_surprise = target[valid] - forecasts["persistence"][valid]
            excess = np.array(
                [returns[i]["stock"] - returns[i][benchmark] for i in valid]
            )
            rho = (
                float(spearmanr(surprise, excess).statistic)
                if len(valid) >= 3 and np.ptp(surprise) > 0 and np.ptp(excess) > 0
                else None
            )
            baseline_rho = (
                float(spearmanr(baseline_surprise, excess).statistic)
                if len(valid) >= 3
                and np.ptp(baseline_surprise) > 0
                and np.ptp(excess) > 0
                else None
            )
            by_index[benchmark] = {
                "events": len(valid),
                "spearman": rho,
                "persistence_spearman_same_events": baseline_rho,
            }
        output[name] = by_index
    return {
        "basis": "gross_20_session_post_filing_open_returns_not_funded_pnl",
        "status_counts": dict(Counter(row["status"] for row in returns)),
        "association": output,
    }
