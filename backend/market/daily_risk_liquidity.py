"""Offline daily risk/liquidity forecasts; no allocator, broker or live caller.

The frozen protocol is docs/research/daily-risk-liquidity-plan-2026-09-30.md.
Dollar turnover is an OHLCV proxy excluding the separate closing auction.
Gap-augmented variance includes the net overnight gap, not its unobserved path.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.market.candidate_stats import hac_t
from backend.market.session_anatomy import bar_returns
from backend.market.sip_cube import SessionCube

TARGETS = ("rth_variance_1", "gap_augmented_variance_5", "dollar_volume_1")
HORIZONS = (1, 5, 1)
MODELS = ("trailing20", "har_ridge", "lightgbm", "weekday_volume")
BENCHMARKS = ("SPY", "QQQ", "SMH", "IGV")
WINDOWS = {
    "2018-2023": ("2018-01-01", "2024-01-01"),
    "2024-2026": ("2024-01-01", "2027-01-01"),
}
EPS = 1e-12


@dataclass(frozen=True)
class Dataset:
    dates: np.ndarray
    tickers: np.ndarray
    session_index: np.ndarray
    sessions: np.ndarray
    x: np.ndarray
    feature_names: tuple[str, ...]
    history: np.ndarray  # row x target x HAR lag (1/5/20)
    baseline: np.ndarray  # row x target, original positive units
    seasonal_volume: np.ndarray  # next weekday's past-only eight-weekday mean
    y: np.ndarray  # row x target, original units; missing labels preserved
    label_end: np.ndarray  # row x target, exchange-session index
    market_variance: np.ndarray
    market_below_mean: np.ndarray
    coverage: dict[str, Any]


@dataclass(frozen=True)
class Config:
    min_train: int = 504
    validation: int = 63
    purge: int = 5
    refit: int = 126
    trees: int = 120
    patience: int = 12
    threads: int = 4
    seed: int = 17


# Average available observations on the real exchange grid, requiring 80% coverage.
def rolling(values: np.ndarray, window: int) -> np.ndarray:
    return (
        pd.Series(values)
        .rolling(window, min_periods=max(1, int(np.ceil(0.8 * window))))
        .mean()
        .to_numpy()
    )


# Take logs only of strictly positive finite observations; missing is not zero.
def positive_log(values: np.ndarray) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    with np.errstate(all="ignore"):
        return np.where((a > 0) & np.isfinite(a), np.log(a), np.nan)


# Reindex a cube without filling missing dates or accepting invalid OHLCV rows.
def cube_series(cube: SessionCube, sessions: np.ndarray) -> dict[str, np.ndarray]:
    dates = np.asarray(cube.dates, dtype="datetime64[D]")
    if len(dates) == 0 or np.any(dates[1:] <= dates[:-1]):
        raise ValueError("cube dates must be nonempty, unique and ascending")
    pos = np.searchsorted(sessions, dates)
    if np.any(pos >= len(sessions)) or not np.array_equal(sessions[pos], dates):
        raise ValueError("cube dates outside reviewed exchange calendar")
    arrays = (cube.open, cube.high, cube.low, cube.close, cube.volume)
    if any(a.shape != (len(dates), 26) for a in arrays):
        raise ValueError("expected 26 regular-session bars per cube row")
    valid = np.logical_and.reduce([np.isfinite(a).all(axis=1) for a in arrays])
    valid &= np.logical_and.reduce([(a > 0).all(axis=1) for a in arrays[:4]])
    valid &= (cube.volume >= 0).all(axis=1) & (cube.volume.sum(axis=1) > 0)
    valid &= (cube.high >= np.maximum(cube.open, cube.close)).all(axis=1)
    valid &= (cube.low <= np.minimum(cube.open, cube.close)).all(axis=1)
    valid &= np.isfinite(cube.prior_close) & (cube.prior_close > 0)
    with np.errstate(all="ignore"):
        returns = bar_returns(cube)
        gap = np.log(cube.open[:, 0] / cube.prior_close)
        rv = (returns**2).sum(axis=1)
        total = rv + gap**2
        turnover = (((cube.high + cube.low + cube.close) / 3) * cube.volume).sum(axis=1)
        own_return = np.log(cube.close[:, -1] / cube.prior_close)
        downside = ((np.minimum(returns, 0)) ** 2).sum(axis=1) + np.minimum(gap, 0) ** 2
        span = (cube.high.max(axis=1) - cube.low.min(axis=1)) / cube.open[:, 0]
    values = {
        "rv": rv,
        "total": total,
        "turnover": turnover,
        "gap": gap,
        "return": own_return,
        "downside": downside,
        "range": span,
        "close": cube.close[:, -1],
    }
    out = {}
    for key, value in values.items():
        grid = np.full(len(sessions), np.nan)
        grid[pos[valid]] = value[valid]
        out[key] = grid
    return out


# Construct future labels only when every intervening exchange session is observed.
def future_labels(histories: np.ndarray) -> np.ndarray:
    y = np.full_like(histories, np.nan)
    for k, horizon in enumerate(HORIZONS):
        for t in range(len(histories) - horizon):
            outcome = histories[t + 1 : t + horizon + 1, k]
            if np.isfinite(outcome).all() and (outcome >= 0).all():
                y[t, k] = max(float(outcome.mean()), EPS)
    return y


# Forecast next-session volume from its last eight same-weekday observations.
def seasonal_volume(
    values: np.ndarray, sessions: np.ndarray, calendar: np.busdaycalendar
) -> np.ndarray:
    weekdays = (sessions.astype(int) + 3) % 7
    tomorrow = np.busday_offset(sessions, 1, busdaycal=calendar)
    next_weekday = (tomorrow.astype(int) + 3) % 7
    out = rolling(values, 20).copy()
    for weekday in range(5):
        observations = weekdays == weekday
        estimate = np.full(len(sessions), np.nan)
        estimate[observations] = rolling(values[observations], 8)
        # Carry the dated estimator, not missing raw prices or volumes.
        estimate = pd.Series(estimate).ffill().to_numpy()
        use = (next_weekday == weekday) & np.isfinite(estimate)
        out[use] = estimate[use]
    return out


# Build causal daily features and labels; tomorrow never chooses today's row.
def build_dataset(
    cubes: Mapping[str, SessionCube],
    membership: Callable[[np.ndarray, tuple[str, ...]], np.ndarray],
    calendar: np.busdaycalendar,
) -> Dataset:
    if "SPY" not in cubes or not cubes:
        raise ValueError("SPY context and at least one eligible stock are required")
    first = min(c.dates[0] for c in cubes.values() if len(c))
    last = max(c.dates[-1] for c in cubes.values() if len(c))
    days = np.arange(first, last + np.timedelta64(1, "D"), dtype="datetime64[D]")
    sessions = days[np.is_busday(days, busdaycal=calendar)]
    names = tuple(sorted(cubes))
    eligible = membership(sessions, names)
    if eligible.shape != (len(sessions), len(names)):
        raise ValueError("membership shape mismatch")
    series = {name: cube_series(cubes[name], sessions) for name in names}
    spy = series["SPY"]
    market_var = rolling(spy["rv"], 20)
    market_below = np.where(
        np.isfinite(rolling(spy["close"], 60)) & np.isfinite(spy["close"]),
        spy["close"] < rolling(spy["close"], 60),
        np.nan,
    )
    weekday = (sessions.astype(int) + 3) % 7
    blocks: list[dict[str, np.ndarray]] = []
    selected = 0
    for column, name in enumerate(names):
        if name in BENCHMARKS:
            continue
        s = series[name]
        histories = np.column_stack([s["rv"], s["total"], s["turnover"]])
        baseline = np.column_stack([rolling(histories[:, k], 20) for k in range(3)])
        har = np.stack(
            [
                np.column_stack([rolling(histories[:, k], w) for w in (1, 5, 20)])
                for k in range(3)
            ],
            axis=1,
        )
        features: dict[str, np.ndarray] = {}
        for key in ("rv", "total", "turnover"):
            for w in (1, 5, 20, 60):
                features[f"log_{key}_{w}"] = positive_log(rolling(s[key], w))
        for w in (1, 5, 20):
            features[f"return_{w}"] = rolling(s["return"], w) * w
            features[f"downside_share_{w}"] = rolling(s["downside"], w) / np.maximum(
                rolling(s["total"], w), EPS
            )
        features["gap"] = s["gap"]
        features["range"] = s["range"]
        features["relative_turnover"] = s["turnover"] / baseline[:, 2]
        features["coverage_60"] = rolling(np.isfinite(s["rv"]).astype(float), 60)
        features["weekday"] = weekday.astype(float)
        for benchmark in ("SPY", "QQQ", "SMH"):
            b = series.get(benchmark)
            features[f"{benchmark}_log_rv20"] = (
                positive_log(rolling(b["rv"], 20))
                if b is not None
                else np.full(len(sessions), np.nan)
            )
            features[f"{benchmark}_ret5"] = (
                rolling(b["return"], 5) * 5
                if b is not None
                else np.full(len(sessions), np.nan)
            )
        x = np.column_stack(list(features.values()))
        y = future_labels(histories)
        ends = np.arange(len(sessions))[:, None] + np.asarray(HORIZONS)[None, :]
        keep = eligible[:, column] & np.isfinite(histories).all(axis=1)
        keep &= np.isfinite(baseline).all(axis=1) & (baseline > 0).all(axis=1)
        selected += int(eligible[:, column].sum())
        ix = np.flatnonzero(keep)
        blocks.append(
            {
                "dates": sessions[ix],
                "tickers": np.full(len(ix), name),
                "session_index": ix,
                "x": x[ix],
                "history": har[ix],
                "baseline": baseline[ix],
                "seasonal_volume": seasonal_volume(s["turnover"], sessions, calendar)[
                    ix
                ],
                "y": y[ix],
                "label_end": ends[ix],
                "market_variance": market_var[ix],
                "market_below_mean": market_below[ix],
            }
        )
    if not blocks or sum(len(b["dates"]) for b in blocks) == 0:
        raise ValueError("no eligible daily rows")
    joined = {key: np.concatenate([b[key] for b in blocks]) for key in blocks[0]}
    order = np.lexsort((joined["tickers"], joined["dates"]))
    joined = {key: value[order] for key, value in joined.items()}
    return Dataset(
        **joined,
        sessions=sessions,
        feature_names=tuple(features),
        coverage={
            "eligible_grid_rows": selected,
            "input_rows": len(order),
            "observed_labels": np.isfinite(joined["y"]).sum(axis=0).tolist(),
            "excluded_cube_sessions": {k: v.excluded for k, v in cubes.items()},
        },
    )


# Produce shared chronological partitions with both label-end and date purges.
def partitions(ds: Dataset, config: Config) -> list[dict[str, Any]]:
    if min(
        config.min_train,
        config.validation,
        config.refit,
        config.trees,
        config.patience,
        config.threads,
    ) < 1 or config.purge < max(HORIZONS):
        raise ValueError(
            "positive settings and a purge of at least five sessions required"
        )
    first = config.min_train + config.validation + 2 * config.purge
    folds = []
    for start in range(first, len(ds.sessions), config.refit):
        val_stop = start - config.purge
        val_start = val_stop - config.validation
        train_stop = val_start - config.purge
        folds.append(
            {
                "train_stop": train_stop,
                "validation_start": val_start,
                "validation_stop": val_stop,
                "test_start": start,
                "test_stop": min(start + config.refit, len(ds.sessions)),
            }
        )
    return folds


# Learn missing-value replacements from training rows alone, preserving large moves.
def impute(train: np.ndarray, *others: np.ndarray) -> tuple[np.ndarray, ...]:
    fill = np.zeros(train.shape[1])
    for j in range(train.shape[1]):
        good = train[np.isfinite(train[:, j]), j]
        if len(good):
            fill[j] = np.median(good)
    return tuple(np.where(np.isfinite(a), a, fill) for a in (train, *others))


# Fit the registered shallow booster with past-only validation and bounded CPU use.
def fit_booster(
    x: np.ndarray,
    y: np.ndarray,
    vx: np.ndarray,
    vy: np.ndarray,
    config: Config,
    alpha: float | None = None,
) -> Any:
    import lightgbm as lgb

    model = lgb.LGBMRegressor(
        objective="regression" if alpha is None else "quantile",
        alpha=0.5 if alpha is None else alpha,
        n_estimators=config.trees,
        max_depth=3,
        num_leaves=7,
        learning_rate=0.05,
        min_child_samples=100,
        reg_lambda=10,
        n_jobs=config.threads,
        random_state=config.seed,
        verbosity=-1,
        deterministic=True,
        force_col_wise=True,
    )
    model.fit(
        x,
        y,
        eval_set=[(vx, vy)],
        callbacks=[lgb.early_stopping(config.patience, verbose=False)],
    )
    return model


# Generate out-of-sample forecasts without letting validation/test outcomes enter fit.
def forecast(
    ds: Dataset, config: Config | None = None, log: Callable[[str], None] | None = None
) -> dict[str, Any]:
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    config = config or Config()
    n = len(ds.dates)
    points = np.full((n, 3, len(MODELS)), np.nan)
    raw_log = np.full_like(points, np.nan)
    intervals = np.full((n, 3, 2), np.nan)
    # Empirical training residual intervals make quantile skill measurable.
    baseline_intervals = np.full_like(intervals, np.nan)
    regimes = np.full(n, -1, dtype=int)
    fits = []
    for fold in partitions(ds, config):
        start = fold["test_start"]
        test = (ds.session_index >= start) & (ds.session_index < fold["test_stop"])
        base_train = ds.session_index < fold["train_stop"]
        base_val = (ds.session_index >= fold["validation_start"]) & (
            ds.session_index < fold["validation_stop"]
        )
        # One market observation per date, not one per stock in that date.
        unique = np.unique(ds.session_index[base_train], return_index=True)[1]
        mv = ds.market_variance[base_train][unique]
        mv = mv[np.isfinite(mv)]
        threshold = float(np.quantile(mv, 0.8)) if len(mv) else np.nan
        known = (
            test & np.isfinite(ds.market_variance) & np.isfinite(ds.market_below_mean)
        )
        regimes[known] = (ds.market_variance[known] > threshold).astype(
            int
        ) + 2 * ds.market_below_mean[known].astype(int)
        record = {
            **fold,
            "test_date": str(ds.sessions[start]),
            "market_variance_p80": threshold,
            "targets": {},
        }
        if not test.any():
            continue
        for k, target in enumerate(TARGETS):
            train = base_train & (ds.label_end[:, k] < fold["validation_start"])
            val = base_val & (ds.label_end[:, k] < start)
            observed = np.isfinite(ds.y[:, k]) & (ds.y[:, k] > 0)
            train &= observed
            val &= observed
            if train.sum() < 100 or val.sum() < 20:
                record["targets"][target] = {"status": "insufficient rows"}
                continue
            baseline_log = positive_log(ds.baseline[:, k])
            response = positive_log(ds.y[:, k]) - baseline_log
            tx, vx, px = impute(ds.x[train], ds.x[val], ds.x[test])
            hx, hv, hp = impute(
                positive_log(ds.history[train, k]),
                positive_log(ds.history[val, k]),
                positive_log(ds.history[test, k]),
            )
            ridge = make_pipeline(StandardScaler(), Ridge(alpha=10))
            ridge.fit(hx, response[train])
            boosted = fit_booster(tx, response[train], vx, response[val], config)
            models = ((ridge, hv, hp), (boosted, vx, px))
            points[test, k, 0] = ds.baseline[test, k]
            raw_log[test, k, 0] = baseline_log[test]
            points[test, k, 3] = (
                ds.seasonal_volume[test] if k == 2 else ds.baseline[test, k]
            )
            raw_log[test, k, 3] = positive_log(points[test, k, 3])
            scales = []
            for m, (model, validation_x, predict_x) in enumerate(models, start=1):
                predicted_log = baseline_log[test] + model.predict(predict_x)
                validation_log = baseline_log[val] + model.predict(validation_x)
                scale = float(
                    np.mean(np.exp(positive_log(ds.y[val, k]) - validation_log))
                )
                points[test, k, m] = np.exp(predicted_log) * scale
                raw_log[test, k, m] = predicted_log
                scales.append(scale)
            q = []
            iterations = {"mean": int(boosted.best_iteration_)}
            for a in (0.1, 0.9):
                model = fit_booster(tx, response[train], vx, response[val], config, a)
                q.append(baseline_log[test] + model.predict(px))
                iterations[str(a)] = int(model.best_iteration_)
            quantiles = np.column_stack(q)
            crossing = int((quantiles[:, 0] > quantiles[:, 1]).sum())
            intervals[test, k] = np.exp(np.sort(quantiles, axis=1))
            baseline_intervals[test, k] = np.exp(
                baseline_log[test, None] + np.quantile(response[train], [0.1, 0.9])
            )
            record["targets"][target] = {
                "status": "fitted",
                "train_rows": int(train.sum()),
                "validation_rows": int(val.sum()),
                "test_rows": int(test.sum()),
                "train_label_end_max": int(ds.label_end[train, k].max()),
                "validation_label_end_max": int(ds.label_end[val, k].max()),
                "calibration_scales": scales,
                "iterations": iterations,
                "quantile_crossings": crossing,
            }
        fits.append(record)
        if log:
            log(
                f"fold {len(fits)}: {record['test_date']}.."
                f"{ds.sessions[fold['test_stop'] - 1]}"
            )
    return {
        "point": points,
        "raw_log": raw_log,
        "interval": intervals,
        "baseline_interval": baseline_intervals,
        "regime": regimes,
        "fits": fits,
    }


# Average paired improvement by session before estimating serially robust uncertainty.
def paired_loss(
    dates: np.ndarray, baseline: np.ndarray, candidate: np.ndarray
) -> dict[str, Any]:
    daily = (
        pd.DataFrame({"date": dates, "gain": baseline - candidate})
        .groupby("date")["gain"]
        .mean()
        .to_numpy()
    )
    return {
        "mean_daily_loss_improvement": float(daily.mean()) if len(daily) else None,
        "hac_t": float(hac_t(daily, 20)) if len(daily) >= 40 else None,
        "dates": len(daily),
    }


# Compute predictive losses, not portfolio profits, on identical observed rows.
def score(ds: Dataset, predictions: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for window, (start, stop) in WINDOWS.items():
        in_window = (ds.dates >= np.datetime64(start)) & (
            ds.dates < np.datetime64(stop)
        )
        for regime in (-1, 0, 1, 2, 3):
            selected = (
                in_window
                if regime == -1
                else in_window & (predictions["regime"] == regime)
            )
            for k, target in enumerate(TARGETS):
                point = predictions["point"][:, k]
                good = selected & np.isfinite(ds.y[:, k]) & (ds.y[:, k] > 0)
                good &= np.isfinite(point).all(axis=1) & (point > 0).all(axis=1)
                if not good.any():
                    continue
                y = ds.y[good, k]
                log_y = np.log(y)
                errors = predictions["raw_log"][good, k] - log_y[:, None]
                qlike = y[:, None] / point[good] - np.log(y[:, None] / point[good]) - 1
                primary = np.abs(errors) if k == 2 else qlike
                low, high = predictions["interval"][good, k].T
                blo, bhi = predictions["baseline_interval"][good, k].T
                # Pinball is scored in log units for all three positive targets.
                q_errors = log_y[:, None] - np.log(np.column_stack([low, high]))
                b_errors = log_y[:, None] - np.log(np.column_stack([blo, bhi]))
                quantile_loss = np.maximum(
                    np.array([0.1, 0.9]) * q_errors,
                    (np.array([0.1, 0.9]) - 1) * q_errors,
                ).mean()
                baseline_loss = np.maximum(
                    np.array([0.1, 0.9]) * b_errors,
                    (np.array([0.1, 0.9]) - 1) * b_errors,
                ).mean()
                for m, model in enumerate(MODELS):
                    row = {
                        "window": window,
                        "regime": regime,
                        "target": target,
                        "model": model,
                        "rows": int(good.sum()),
                        "primary_loss": float(primary[:, m].mean()),
                        "primary_metric": "log_mae" if k == 2 else "qlike",
                        "log_mse": float((errors[:, m] ** 2).mean()),
                        "log_mse_skill_vs_trailing": float(
                            1
                            - (errors[:, m] ** 2).mean()
                            / max((errors[:, 0] ** 2).mean(), EPS)
                        ),
                        "log_mae": float(np.abs(errors[:, m]).mean()),
                        "qlike": float(qlike[:, m].mean()),
                        "skill_vs_trailing": float(
                            1 - primary[:, m].mean() / max(primary[:, 0].mean(), EPS)
                        ),
                        **paired_loss(ds.dates[good], primary[:, 0], primary[:, m]),
                    }
                    if m == 2:
                        comparator = min(
                            float(primary[:, 0].mean()),
                            float(primary[:, 1].mean()),
                            float(primary[:, 3].mean()),
                        )
                        row.update(
                            {
                                "skill_vs_best_simple": float(
                                    1 - primary[:, 2].mean() / max(comparator, EPS)
                                ),
                                "paired_vs_har": paired_loss(
                                    ds.dates[good], primary[:, 1], primary[:, 2]
                                ),
                                "interval_coverage": float(
                                    ((y >= low) & (y <= high)).mean()
                                ),
                                "below_q10": float((y < low).mean()),
                                "above_q90": float((y > high).mean()),
                                "log_pinball": float(quantile_loss),
                                "baseline_log_pinball": float(baseline_loss),
                            }
                        )
                    rows.append(row)
    return rows


# Identify forecast research leads while structurally refusing any live-promotion claim.
def verdict(scores: list[dict[str, Any]]) -> dict[str, Any]:
    targets = {}
    for target in TARGETS:
        rows = [
            r
            for r in scores
            if r["target"] == target and r["model"] == "lightgbm" and r["regime"] == -1
        ]
        passes = len(rows) == len(WINDOWS) and all(
            r["skill_vs_best_simple"] >= 0.02 for r in rows
        )
        targets[target] = (
            "FORECAST RESEARCH LEAD" if passes else "NO INCREMENTAL FORECAST LEAD"
        )
    return {
        "targets": targets,
        "live_promotion": False,
        "portfolio_return_test": "not run: no action policy changed",
        "fresh_holdout": False,
        "comparisons": 6,
    }
