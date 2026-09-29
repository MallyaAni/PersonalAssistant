"""Daily-only economic forecasts for the registered, offline action experiment.

No live strategy imports this module. The label is a five-session adjusted
open-to-open return, not an action or a promised executable portfolio return.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.market.stage3_features import (
    lag,
    rolling_extreme,
    rolling_mean,
    rolling_std,
)

PLAN = "docs/research/daily-actions-plan-2026-09-29.md"
HORIZONS = (1, 5, 20, 60)
RIDGE_ALPHAS = (10.0, 1000.0)
TREE_LEAVES = (7, 15)
TREE_ITERATIONS = (25, 50, 100)
MIN_TRAIN = 500
MIN_VALIDATION = 100
# The frozen A/A+ ordinal gate; grades are gates, never model features.
MIN_GRADE = 2


@dataclass(frozen=True)
class DailyData:
    """Aligned daily inputs; label_end is a date, NaT without a future endpoint."""

    dates: np.ndarray
    tickers: tuple[str, ...]
    features: np.ndarray
    labels: np.ndarray
    eligible: np.ndarray
    feature_names: tuple[str, ...]
    label_end: np.ndarray


@dataclass(frozen=True)
class TrainingResult:
    """Out-of-sample predictions and the exact decisions made by each fold."""

    predictions: dict[str, np.ndarray]
    receipts: list[dict]


# Keep invalid prices missing instead of turning them into observations.
def _positive(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return np.where(np.isfinite(values) & (values > 0), values, np.nan)


# Compute log ratios only where both endpoints are positive and finite.
def _log_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        result = np.log(_positive(numerator) / _positive(denominator))
    return np.where(np.isfinite(result), result, np.nan)


# Build causal daily price/volume features and independent future labels.
def build_dataset(panel, membership, grades, qqq_adj_close: np.ndarray) -> DailyData:  # noqa: C901 - one frozen feature block
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    close = _positive(panel.adj_close)
    shape = close.shape
    if close.ndim != 2 or shape != (len(dates), len(panel.tickers)):
        raise ValueError("panel prices must match dates and tickers")
    if np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
        raise ValueError("panel dates must be distinct and increasing")
    if np.shape(membership) != shape or np.shape(grades) != shape:
        raise ValueError("membership and grades must match panel prices")
    if np.shape(qqq_adj_close) != (len(dates),):
        raise ValueError("QQQ must already be aligned to panel dates")
    raw = [
        _positive(getattr(panel, name))
        for name in ("open", "high", "low", "close", "volume")
    ]
    if any(values.shape != shape for values in raw):
        raise ValueError("all OHLCV arrays must have the same shape")
    open_, high, low, raw_close, volume = raw
    valid = np.isfinite(np.stack(raw, axis=-1)).all(axis=-1) & np.isfinite(close)
    valid &= (low <= np.minimum(open_, raw_close)) & (
        high >= np.maximum(open_, raw_close)
    )
    with np.errstate(all="ignore"):
        factor = close / raw_close
    open_, high, low, close, volume = [
        np.where(valid, values, np.nan)
        for values in (open_ * factor, high * factor, low * factor, close, volume)
    ]
    columns = {}
    for horizon in HORIZONS:
        columns[f"stock_log_return_{horizon}"] = _log_ratio(close, lag(close, horizon))
    returns = columns["stock_log_return_1"]
    columns["stock_volatility_20"] = rolling_std(returns, 20)
    for horizon in (20, 60):
        columns[f"stock_log_close_mean_{horizon}"] = _log_ratio(
            close, rolling_mean(close, horizon)
        )
    with np.errstate(all="ignore"):
        columns["stock_peak_drawdown_20"] = close / rolling_extreme(close, 20, True) - 1
    columns["stock_log_open_gap"] = _log_ratio(open_, lag(close, 1))
    columns["stock_log_high_low"] = _log_ratio(high, low)
    columns["stock_log_close_open"] = _log_ratio(close, open_)
    columns["stock_log_relative_volume_20"] = _log_ratio(
        volume, rolling_mean(volume, 20)
    )
    for name, benchmark in (
        ("spy", close[:, panel.index(panel.benchmark)]),
        ("qqq", _positive(qqq_adj_close)),
    ):
        for horizon in HORIZONS:
            value = _log_ratio(benchmark, lag(benchmark, horizon))
            columns[f"{name}_log_return_{horizon}"] = np.broadcast_to(
                value[:, None], shape
            )
        value = rolling_std(_log_ratio(benchmark, lag(benchmark, 1)), 20)
        columns[f"{name}_volatility_20"] = np.broadcast_to(value[:, None], shape)
    features = np.stack(list(columns.values()), axis=-1)
    eligible = np.asarray(membership, dtype=bool) & (np.asarray(grades) >= MIN_GRADE)
    eligible &= np.isfinite(features).all(axis=-1)
    eligible[:, panel.index(panel.benchmark)] = False
    labels = np.full(shape, np.nan)
    label_end = np.full(len(dates), np.datetime64("NaT", "D"))
    if len(dates) > 6:
        labels[:-6] = _log_ratio(open_[6:], open_[1:-5])
        label_end[:-6] = dates[6:]
    return DailyData(
        dates.copy(),
        tuple(panel.tickers),
        features,
        labels,
        eligible,
        tuple(columns),
        label_end,
    )


# Select only matured labels in one chronological decision interval.
def _rows(data: DailyData, start: np.datetime64, stop: np.datetime64) -> np.ndarray:
    decisions = (data.dates >= start) & (data.dates < stop)
    mature = ~np.isnat(data.label_end) & (data.label_end < stop)
    return data.eligible & np.isfinite(data.labels) & (decisions & mature)[:, None]


# Summarize actual decision and endpoint bounds for the selected observations.
def _bounds(data: DailyData, rows: np.ndarray) -> dict:
    days = np.flatnonzero(rows.any(axis=1))
    return {
        "rows": int(rows.sum()),
        "first_decision": str(data.dates[days[0]]) if len(days) else None,
        "last_decision": str(data.dates[days[-1]]) if len(days) else None,
        "last_label_end": str(data.label_end[days].max()) if len(days) else None,
    }


# Construct the exact registered tree without random internal validation.
def _tree(leaves: int, iterations: int):
    from sklearn.ensemble import HistGradientBoostingRegressor

    return HistGradientBoostingRegressor(
        learning_rate=0.05,
        max_leaf_nodes=leaves,
        l2_regularization=10.0,
        min_samples_leaf=100,
        loss="squared_error",
        random_state=29,
        max_iter=iterations,
        early_stopping=False,
    )


# Fit a scaler and ridge together so preprocessing cannot see later rows.
def _ridge(alpha: float):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), Ridge(alpha=alpha))


# Score a prediction in the target's log-return units without trimming extremes.
def _mse(observed: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean((observed - predicted) ** 2))


# Preserve fold evidence incrementally so an interrupted run is not mislabeled complete.
def _save_receipts(output: Path, receipts: list[dict], complete: bool) -> None:
    import sklearn

    payload = {
        "plan": PLAN,
        "complete": complete,
        "sklearn_version": sklearn.__version__,
        "folds": receipts,
    }
    (output / "training_receipts.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n"
    )


# Run the fixed annual validation search, refit matured history, and save real models.
def train(  # noqa: C901 - one bounded fold protocol
    data: DailyData,
    output: Path,
    *,
    first_test_year: int = 2019,
    last_test_year: int = 2026,
) -> TrainingResult:
    import joblib

    if not 2019 <= first_test_year <= last_test_year <= 2026:
        raise ValueError(
            "test years must be a subset of the registered 2019..2026 range"
        )
    if (
        data.features.shape[:2] != data.labels.shape
        or data.eligible.shape != data.labels.shape
    ):
        raise ValueError("features, labels and eligibility must align")
    if (
        data.features.shape[2] != len(data.feature_names)
        or data.label_end.shape != data.dates.shape
    ):
        raise ValueError("feature names and label endpoints must align")
    if np.any(data.eligible & ~np.isfinite(data.features).all(axis=-1)):
        raise ValueError("eligible rows must have finite features")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "models").mkdir()
    predictions = {
        name: np.full(data.labels.shape, np.nan) for name in ("ridge", "tree", "mean")
    }
    receipts = []
    start = np.datetime64("2016-01-01")
    for year in range(first_test_year, last_test_year + 1):
        validation_start = np.datetime64(f"{year - 1}-01-01")
        test_start = np.datetime64(f"{year}-01-01")
        test_end = np.datetime64(f"{year + 1}-01-01")
        test_days = (data.dates >= test_start) & (data.dates < test_end)
        if not test_days.any():
            continue
        fit_rows = _rows(data, start, validation_start)
        validation_rows = _rows(data, validation_start, test_start)
        refit_rows = _rows(data, start, test_start)
        test_rows = data.eligible & test_days[:, None]
        receipt = {
            "year": year,
            "fit": _bounds(data, fit_rows),
            "validation": _bounds(data, validation_rows),
            "refit": _bounds(data, refit_rows),
            "test_first": str(data.dates[test_days][0]),
            "test_last": str(data.dates[test_days][-1]),
            "prediction_rows": int(test_rows.sum()),
            "settings": [],
        }
        receipts.append(receipt)
        if fit_rows.sum() < MIN_TRAIN or validation_rows.sum() < MIN_VALIDATION:
            receipt["status"] = "INVALID_INSUFFICIENT_LABELS"
            _save_receipts(output, receipts, False)
            raise ValueError(
                f"invalid {year} fold: fewer than required fit/validation labels"
            )
        if not test_rows.any():
            receipt["status"] = "INVALID_NO_ELIGIBLE_TEST_ROWS"
            _save_receipts(output, receipts, False)
            raise ValueError(f"invalid {year} fold: no eligible prediction rows")
        print(
            f"daily actions {year}: fit={int(fit_rows.sum())}, "
            f"validation={int(validation_rows.sum())}, test={int(test_rows.sum())}",
            flush=True,
        )
        xfit, yfit = data.features[fit_rows], data.labels[fit_rows]
        xvalidation, yvalidation = (
            data.features[validation_rows],
            data.labels[validation_rows],
        )
        ridge_scores = []
        for alpha in RIDGE_ALPHAS:
            model = _ridge(alpha).fit(xfit, yfit)
            score = _mse(yvalidation, model.predict(xvalidation))
            ridge_scores.append(score)
            receipt["settings"].append(
                {"family": "ridge", "alpha": alpha, "validation_mse": score}
            )
        tree_settings = []
        tree_scores = []
        for leaves in TREE_LEAVES:
            model = _tree(leaves, max(TREE_ITERATIONS)).fit(xfit, yfit)
            for iteration, values in enumerate(
                model.staged_predict(xvalidation), start=1
            ):
                if iteration in TREE_ITERATIONS:
                    score = _mse(yvalidation, values)
                    tree_settings.append((leaves, iteration))
                    tree_scores.append(score)
                    receipt["settings"].append(
                        {
                            "family": "tree",
                            "max_leaf_nodes": leaves,
                            "max_iter": iteration,
                            "validation_mse": score,
                        }
                    )
        alpha = RIDGE_ALPHAS[int(np.argmin(ridge_scores))]
        leaves, iterations = tree_settings[int(np.argmin(tree_scores))]
        xrefit, yrefit = data.features[refit_rows], data.labels[refit_rows]
        models = {
            "ridge": _ridge(alpha).fit(xrefit, yrefit),
            "tree": _tree(leaves, iterations).fit(xrefit, yrefit),
        }
        mean = float(np.mean(yrefit))
        for family, model in models.items():
            if test_rows.any():
                predictions[family][test_rows] = model.predict(data.features[test_rows])
            path = output / "models" / f"{year}-{family}.joblib"
            joblib.dump(
                {
                    "model": model,
                    "feature_names": data.feature_names,
                    "year": year,
                    "plan": PLAN,
                },
                path,
            )
            receipt[f"{family}_model_sha256"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        predictions["mean"][test_rows] = mean
        receipt.update(
            {
                "status": "FITTED",
                "selected_ridge_alpha": alpha,
                "selected_tree_leaves": leaves,
                "selected_tree_iterations": iterations,
                "refit_mean": mean,
                "validation_mean_mse": _mse(
                    yvalidation, np.full(len(yvalidation), np.mean(yfit))
                ),
            }
        )
        _save_receipts(output, receipts, False)
        print(
            f"daily actions {year}: ridge alpha={alpha:g} "
            f"validation MSE={min(ridge_scores):.8g}; "
            f"tree leaves={leaves} iterations={iterations} "
            f"validation MSE={min(tree_scores):.8g}",
            flush=True,
        )
    if not receipts:
        _save_receipts(output, receipts, False)
        raise ValueError("no dates in the registered outer test years")
    np.savez_compressed(
        output / "predictions.npz",
        dates=data.dates,
        tickers=np.asarray(data.tickers),
        **predictions,
    )
    _save_receipts(output, receipts, True)
    return TrainingResult(predictions, receipts)
