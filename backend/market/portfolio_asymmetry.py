"""Research-only portfolio loss/gain forecasts, never a live allocation rule."""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk.grading import ORDINAL
from backend.market import filing_expectations as shared
from backend.market.research_journal_replay import verify_snapshot

PLAN = "docs/research/portfolio-asymmetry-plan-2026-09-29.md"
FEATURES = (
    "spy_return5",
    "spy_return20",
    "spy_return60",
    "qqq_return5",
    "qqq_return20",
    "qqq_return60",
    "spy_vol20",
    "spy_distance200",
    "book_return5",
    "book_return20",
    "book_downside20",
    "book_upside20",
    "book_drawdown60",
    "stock_exposure",
    "stock_concentration",
    "eligible_a_share",
)
PARAMS = {
    **shared.LGBM_PARAMS,
    "max_depth": 3,
    "min_data_in_leaf": 100,
    "feature_fraction": 1.0,
    "bagging_fraction": 1.0,
}


# Reconstruct actual holdings and five-session outcomes on one baseline account.
def dataset(bundle, snapshot):
    verified = verify_snapshot(snapshot)
    if not verified["ok"]:
        raise ValueError("baseline journal does not reconcile")
    panel = bundle["report"].panel
    manifest = snapshot["manifest"]
    if manifest["sessions"] != [str(day) for day in panel.dates]:
        raise ValueError("journal calendar differs from cached report")
    if manifest["symbols"] != list(panel.tickers):
        raise ValueError("journal symbols differ from cached report")
    marks = verified["marks"]
    start = marks[0]["session_index"]
    nav = np.full(len(panel.dates), np.nan)
    nav[start:] = [row["nav"] for row in marks]
    weights = np.zeros(panel.close.shape)
    close = np.asarray(snapshot["prices"]["close"], dtype=float)
    np.testing.assert_array_equal(close, panel.adj_close)
    for row in marks:
        t = row["session_index"]
        units = np.asarray(row["positions"])
        weights[t] = np.where(units > 0, units * close[t] / nav[t], 0.0)
    indexes = [np.asarray(bundle[name], dtype=float) for name in ("spy", "qqq")]
    if any(values.shape != nav.shape for values in indexes):
        raise ValueError("benchmark calendar length mismatch")
    if any(not np.isfinite(v).all() or (v <= 0).any() for v in indexes):
        raise ValueError("complete positive benchmark prices required")
    rows = []
    for t in range(max(200, start + 60), len(nav)):
        features = [
            values[t] / values[t - lag] - 1 for values in indexes for lag in (5, 20, 60)
        ]
        spy = indexes[0]
        recent_spy = spy[t - 20 : t + 1]
        daily = nav[t - 19 : t + 1] / nav[t - 20 : t] - 1
        membership = bundle["membership"][t]
        grades = bundle["report"].graded.grades[t]
        features.extend(
            [
                np.std(np.diff(np.log(recent_spy)), ddof=1) * np.sqrt(252),
                spy[t] / spy[t - 199 : t + 1].mean() - 1,
                nav[t] / nav[t - 5] - 1,
                nav[t] / nav[t - 20] - 1,
                np.mean(np.minimum(daily, 0) ** 2),
                np.mean(np.maximum(daily, 0) ** 2),
                nav[t] / np.max(nav[t - 59 : t + 1]) - 1,
                weights[t].sum(),
                np.square(weights[t]).sum(),
                np.mean(grades[membership] >= ORDINAL["A"])
                if membership.any()
                else np.nan,
            ]
        )
        end = t + 5
        value = nav[end] / nav[t] - 1 if end < len(nav) else None
        rows.append(
            {
                "date": str(panel.dates[t]),
                "session_index": t,
                "endpoint": str(panel.dates[end]) if value is not None else None,
                "x": np.asarray(features).tolist(),
                "return5": value,
                "target": [max(value, 0), max(-value, 0)]
                if value is not None
                else [None, None],
            }
        )
    return rows


# Purge labels that cross either annual boundary; unknown endpoints never train.
def masks(rows, year):
    days = np.array([row["date"] for row in rows], dtype="datetime64[D]")
    ends = np.array([row["endpoint"] for row in rows], dtype="datetime64[D]")
    cutoff, validation, next_year = [
        np.datetime64(f"{y}-01-01") for y in (year, year - 1, year + 1)
    ]
    return {
        "fit": ends < cutoff,
        "inner": ends < validation,
        "validation": (days >= validation) & (ends < cutoff),
        "test": (days >= cutoff) & (days < next_year),
    }


# Fit the frozen annual baselines and two-head trees, retaining re-loadable models.
def walk_forward(rows):
    import lightgbm as lgb
    from sklearn.linear_model import Ridge

    x = np.asarray([row["x"] for row in rows], dtype=float)
    y = np.asarray([row["target"] for row in rows], dtype=float)
    if x.shape != (len(rows), len(FEATURES)) or y.shape != (len(rows), 2):
        raise ValueError("unexpected feature or target columns")
    predictions = {
        name: np.full_like(y, np.nan) for name in ("mean", "ridge", "lightgbm")
    }
    fits = []
    for year in range(2019, 2027):
        split = masks(rows, year)
        fit, inner, valid, test = [
            split[key] for key in ("fit", "inner", "validation", "test")
        ]
        receipt = {"year": year, **{k: int(v.sum()) for k, v in split.items()}}
        fits.append(receipt)
        if fit.sum() < 504 or not test.any():
            receipt["status"] = "insufficient_fit_or_test"
            continue
        params = shared.fit_transform(x[fit])
        mean = y[fit].mean(axis=0)
        ridge = Ridge(alpha=10).fit(shared.transform(x[fit], params), y[fit])
        predictions["mean"][test] = mean
        predictions["ridge"][test] = np.maximum(
            ridge.predict(shared.transform(x[test], params)), 0
        )
        receipt.update(
            status="baselines_scored",
            preprocessing=params.tolist(),
            mean=mean.tolist(),
            ridge_coef=ridge.coef_.tolist(),
            ridge_intercept=ridge.intercept_.tolist(),
            latest_fit_endpoint=max(rows[i]["endpoint"] for i in np.flatnonzero(fit)),
        )
        if inner.sum() < 504 or valid.sum() < 126:
            continue
        inner_params = shared.fit_transform(x[inner])
        receipt["heads"] = []
        receipt["inner_preprocessing"] = inner_params.tolist()
        for head in range(2):
            trial = lgb.train(
                PARAMS,
                lgb.Dataset(
                    shared.transform(x[inner], inner_params), label=y[inner, head]
                ),
                num_boost_round=300,
                valid_sets=[
                    lgb.Dataset(
                        shared.transform(x[valid], inner_params), label=y[valid, head]
                    )
                ],
                callbacks=[lgb.early_stopping(30, verbose=False)],
            )
            model = lgb.train(
                PARAMS,
                lgb.Dataset(shared.transform(x[fit], params), label=y[fit, head]),
                num_boost_round=trial.best_iteration,
            )
            predictions["lightgbm"][test, head] = np.maximum(
                model.predict(shared.transform(x[test], params)), 0
            )
            receipt["heads"].append(
                {
                    "best_iteration": trial.best_iteration,
                    "validation_mse": trial.best_score["valid_0"]["l2"],
                    "model": model.model_to_string(),
                }
            )
        receipt["status"] = "all_scored"
    return predictions, fits


# Score all models on identical mature dates and reject symmetric-risk-only skill.
def summarize(rows, predictions):
    dates = np.array([r["date"] for r in rows], dtype="datetime64[D]")
    y = np.asarray([r["target"] for r in rows], dtype=float)
    common = np.isfinite(y).all(axis=1)
    for values in predictions.values():
        common &= np.isfinite(values).all(axis=1)
    net = y[:, 0] - y[:, 1]
    net_predictions = {
        name: values[:, 0] - values[:, 1] for name, values in predictions.items()
    }
    blocks = {
        "2019-2023": (dates >= np.datetime64("2019-01-01"))
        & (dates < np.datetime64("2024-01-01")),
        "2024-2026": dates >= np.datetime64("2024-01-01"),
    }
    blocks.update(
        {
            str(year): (dates >= np.datetime64(f"{year}-01-01"))
            & (dates < np.datetime64(f"{year + 1}-01-01"))
            for year in range(2019, 2027)
        }
    )
    metrics = {}
    for period, keep in blocks.items():
        keep = keep & common
        stats = {}
        for name, values in predictions.items():
            error = net_predictions[name][keep] - net[keep]
            stats[name] = {
                "net_mse": float(np.mean(error**2)) if keep.any() else None,
                "net_mae": float(np.mean(abs(error))) if keep.any() else None,
                "head_mse": np.mean((values[keep] - y[keep]) ** 2, axis=0).tolist()
                if keep.any()
                else [None, None],
            }
        metrics[period] = {"dates": int(keep.sum()), "models": stats}
    early = common & blocks["2019-2023"]
    benefit = (net_predictions["mean"] - net) ** 2 - (
        net_predictions["lightgbm"] - net
    ) ** 2
    interval = shared.benefit_interval(dates[early], benefit[early])
    checks = {
        "early_500_dates": int(early.sum()) >= 500,
        "positive_bootstrap_lower": interval[0] is not None and interval[0] > 0,
    }
    wins = 0
    for year in range(2019, 2024):
        stat = metrics[str(year)]
        if stat["dates"]:
            wins += (
                stat["models"]["lightgbm"]["net_mse"]
                < stat["models"]["mean"]["net_mse"]
            )
    checks["three_early_years"] = bool(wins >= 3)
    for period in ("2019-2023", "2024-2026"):
        stat = metrics[period]
        for reference in ("mean", "ridge"):
            for metric in ("net_mse", "net_mae"):
                factor = 0.98 if period == "2019-2023" and metric == "net_mse" else 1
                checks[f"{period}_{reference}_{metric}"] = bool(
                    stat["dates"]
                    and stat["models"]["lightgbm"][metric]
                    <= factor * stat["models"][reference][metric]
                )
    return {
        "metrics": metrics,
        "checks": checks,
        "paired_squared_error_benefit_95pct": interval,
        "verdict": "RESEARCH_PROMISING_NOT_PROMOTION"
        if all(checks.values())
        else "DO_NOT_ADVANCE",
        "immature_rows": int((~np.isfinite(y).all(axis=1)).sum()),
        "live_promotion_authorized": False,
    }
