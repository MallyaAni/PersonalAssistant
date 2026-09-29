"""Holdings-aware, net action-advantage models for an offline selective trial.

Labels come from actual counterfactual /4 continuations, not from this module.
No trained model is connected to live trading or the dashboard.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.market.daily_action_model import (
    MIN_TRAIN,
    MIN_VALIDATION,
    RIDGE_ALPHAS,
    TREE_ITERATIONS,
    TREE_LEAVES,
    _mse,
    _ridge,
    _tree,
)

PLAN = "docs/research/selective-actions-plan-2026-09-29.md"
ACTIONS = ("Buy", "Add", "Trim", "Sell")
DAILY_FEATURE_COUNT = 22
STATE_FEATURE_NAMES = (
    "held_weight",
    "cash_share",
    "target_gap",
    "holding_age",
    "sessions_to_reset",
    "signed_incremental_weight",
    "incumbent_weight",
    "action_Buy",
    "action_Add",
    "action_Trim",
    "action_Sell",
)
FEATURE_COUNT = DAILY_FEATURE_COUNT + len(STATE_FEATURE_NAMES)


# Encode the current account and feasible action without any outcome information.
def action_features(
    daily_row,
    *,
    held_weight,
    cash_share,
    target_gap,
    holding_age,
    sessions_to_reset,
    signed_incremental_weight,
    incumbent_weight,
    action,
) -> np.ndarray:
    daily_row = np.asarray(daily_row, dtype=float)
    if daily_row.shape != (DAILY_FEATURE_COUNT,) or not np.isfinite(daily_row).all():
        raise ValueError("exactly 22 finite current daily features are required")
    if action not in ACTIONS:
        raise ValueError("action must be Buy, Add, Trim or Sell")
    state = np.asarray(
        [
            held_weight,
            cash_share,
            target_gap,
            holding_age,
            sessions_to_reset,
            signed_incremental_weight,
            incumbent_weight,
        ],
        dtype=float,
    )
    if not np.isfinite(state).all() or np.any(state[[0, 1, 3, 4, 6]] < 0):
        raise ValueError(
            "account state must be finite with nonnegative holdings and age"
        )
    increasing = action in ("Buy", "Add")
    if (increasing and signed_incremental_weight <= 0) or (
        not increasing and signed_incremental_weight >= 0
    ):
        raise ValueError("signed intervention weight must agree with the action")
    if (action == "Buy" and held_weight != 0) or (action != "Buy" and held_weight <= 0):
        raise ValueError("Buy requires no holding; Add, Trim and Sell require holdings")
    return np.concatenate(
        [daily_row, state, np.asarray([action == a for a in ACTIONS], dtype=float)]
    )


# Validate model inputs while preserving every candidate whose current inputs exist.
def _current_inputs(features, actions):
    features = np.asarray(features, dtype=float)
    actions = np.asarray(actions, dtype=str)
    if features.ndim != 2 or features.shape[1] != FEATURE_COUNT:
        raise ValueError("action features must have shape (rows, 33)")
    if actions.shape != (len(features),) or not np.isin(actions, ACTIONS).all():
        raise ValueError("one valid action is required for each feature row")
    if not np.isfinite(features).all():
        raise ValueError("current action features must be finite")
    expected = actions[:, None] == np.asarray(ACTIONS)[None, :]
    if not np.array_equal(features[:, -len(ACTIONS) :], expected.astype(float)):
        raise ValueError("action one-hot features disagree with action labels")
    return features, actions


@dataclass(frozen=True)
class ActionData:
    """Flat causal candidates; unavailable future labels stay NaN in retained rows."""

    dates: np.ndarray
    features: np.ndarray
    labels: np.ndarray
    label_end: np.ndarray
    actions: np.ndarray
    feature_names: tuple[str, ...]

    # Own and freeze aligned arrays so later caller mutation cannot alter a fit.
    def __post_init__(self):
        features, actions = _current_inputs(self.features, self.actions)
        dates = np.asarray(self.dates, dtype="datetime64[D]")
        labels = np.asarray(self.labels, dtype=float)
        ends = np.asarray(self.label_end, dtype="datetime64[D]")
        shape = (len(features),)
        if dates.shape != shape or labels.shape != shape or ends.shape != shape:
            raise ValueError("candidate dates, labels and endpoints must align")
        if np.isnat(dates).any() or np.any(dates[1:] < dates[:-1]):
            raise ValueError("candidate dates must be known and chronologically sorted")
        if np.isinf(labels).any():
            raise ValueError("unknown labels must be NaN, not infinite")
        if np.any(np.isfinite(labels) & (np.isnat(ends) | (ends <= dates))):
            raise ValueError("every observed label needs a later endpoint")
        names = tuple(self.feature_names)
        if (
            len(names) != FEATURE_COUNT
            or names[-len(STATE_FEATURE_NAMES) :] != STATE_FEATURE_NAMES
        ):
            raise ValueError(
                "feature names must identify the 22 daily and 11 state columns"
            )
        if len(set(names)) != len(names):
            raise ValueError("feature names must be distinct")
        for name, value in (
            ("dates", dates),
            ("features", features),
            ("labels", labels),
            ("label_end", ends),
            ("actions", actions),
        ):
            owned = np.array(value, copy=True)
            owned.setflags(write=False)
            object.__setattr__(self, name, owned)
        object.__setattr__(self, "feature_names", names)


@dataclass(frozen=True)
class TrainingResult:
    """Annual fits and teacher predictions; inference reads its caller's state."""

    models: dict[int, dict[str, Any]]
    means: dict[int, dict[str, float]]
    receipts: list[dict]
    predictions: dict[str, np.ndarray]
    feature_names: tuple[str, ...]

    # Select only the decision year's past-fitted model and score current candidates.
    def predict(self, family, decision_date, features, actions) -> np.ndarray:
        features, actions = _current_inputs(features, actions)
        day = np.datetime64(decision_date, "D")
        if np.isnat(day):
            raise ValueError("prediction requires a known decision date")
        year = int(day.astype("datetime64[Y]").astype(int)) + 1970
        if year not in self.models:
            raise ValueError(f"no past-fitted model for decision year {year}")
        if family == "mean":
            return np.asarray([self.means[year][a] for a in actions], dtype=float)
        if family not in ("ridge", "tree"):
            raise ValueError("family must be ridge, tree or mean")
        if not len(features):
            return np.empty(0, dtype=float)
        return np.asarray(self.models[year][family].predict(features), dtype=float)


# Keep labels only when their entire counterfactual outcome precedes the boundary.
def _rows(data: ActionData, start, stop) -> np.ndarray:
    return (
        (data.dates >= start)
        & (data.dates < stop)
        & np.isfinite(data.labels)
        & ~np.isnat(data.label_end)
        & (data.label_end < stop)
    )


# Record exact date and action coverage for one fit or validation partition.
def _bounds(data: ActionData, rows: np.ndarray) -> dict:
    positions = np.flatnonzero(rows)
    return {
        "rows": int(rows.sum()),
        "first_decision": str(data.dates[positions[0]]) if len(positions) else None,
        "last_decision": str(data.dates[positions[-1]]) if len(positions) else None,
        "last_label_end": str(data.label_end[rows].max()) if len(positions) else None,
        "actions": {a: int((data.actions[rows] == a).sum()) for a in ACTIONS},
    }


# Form the action-specific constant control using only the selected past labels.
def _means(data: ActionData, rows: np.ndarray) -> dict[str, float]:
    return {
        action: float(data.labels[rows & (data.actions == action)].mean())
        if np.any(rows & (data.actions == action))
        else 0.0
        for action in ACTIONS
    }


# Save incomplete evidence after each fold and mark completion only after all fits.
def _save_receipts(output, receipts, feature_names, complete):
    import sklearn

    payload = {
        "plan": PLAN,
        "complete": complete,
        "sklearn_version": sklearn.__version__,
        "feature_names": list(feature_names),
        "folds": receipts,
    }
    (output / "training_receipts.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n"
    )


# Select among the fixed settings using one chronological validation partition.
def _select(xfit, yfit, xvalidation, yvalidation):
    settings = []
    ridge_scores = []
    for alpha in RIDGE_ALPHAS:
        fitted = _ridge(alpha).fit(xfit, yfit)
        score = _mse(yvalidation, fitted.predict(xvalidation))
        ridge_scores.append(score)
        settings.append({"family": "ridge", "alpha": alpha, "validation_mse": score})
    tree_scores, tree_settings = [], []
    for leaves in TREE_LEAVES:
        fitted = _tree(leaves, max(TREE_ITERATIONS)).fit(xfit, yfit)
        for iteration, predicted in enumerate(
            fitted.staged_predict(xvalidation), start=1
        ):
            if iteration in TREE_ITERATIONS:
                score = _mse(yvalidation, predicted)
                tree_scores.append(score)
                tree_settings.append((leaves, iteration))
                settings.append(
                    {
                        "family": "tree",
                        "max_leaf_nodes": leaves,
                        "max_iter": iteration,
                        "validation_mse": score,
                    }
                )
    alpha = RIDGE_ALPHAS[int(np.argmin(ridge_scores))]
    leaves, iterations = tree_settings[int(np.argmin(tree_scores))]
    return alpha, leaves, iterations, settings


# Fit the registered action-advantage models without consuming outer-test outcomes.
def train(
    data: ActionData, output: Path, *, first_test_year=2019, last_test_year=2026
) -> TrainingResult:
    import joblib

    if not 2019 <= first_test_year <= last_test_year <= 2026:
        raise ValueError("test years must be within the registered 2019..2026 range")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "models").mkdir()
    predictions = {
        family: np.full(len(data.dates), np.nan) for family in ("ridge", "tree", "mean")
    }
    models, means, receipts = {}, {}, []
    for year in range(first_test_year, last_test_year + 1):
        first = np.datetime64("2016-01-01")
        validation_start = np.datetime64(f"{year - 1}-01-01")
        test_start = np.datetime64(f"{year}-01-01")
        test_end = np.datetime64(f"{year + 1}-01-01")
        test_rows = (data.dates >= test_start) & (data.dates < test_end)
        if not test_rows.any():
            continue
        fit = _rows(data, first, validation_start)
        validation = _rows(data, validation_start, test_start)
        refit = _rows(data, first, test_start)
        receipt = {
            "year": year,
            "fit": _bounds(data, fit),
            "validation": _bounds(data, validation),
            "refit": _bounds(data, refit),
            "prediction_rows": int(test_rows.sum()),
            "test_first": str(data.dates[test_rows][0]),
            "test_last": str(data.dates[test_rows][-1]),
        }
        receipts.append(receipt)
        if fit.sum() < MIN_TRAIN or validation.sum() < MIN_VALIDATION:
            receipt["status"] = "INVALID_INSUFFICIENT_LABELS"
            _save_receipts(output, receipts, data.feature_names, False)
            raise ValueError(
                f"invalid {year} action fold: fewer than required fit/validation labels"
            )
        print(
            f"selective actions {year}: fit={int(fit.sum())}, "
            f"validation={int(validation.sum())}, test={int(test_rows.sum())}",
            flush=True,
        )
        alpha, leaves, iterations, settings = _select(
            data.features[fit],
            data.labels[fit],
            data.features[validation],
            data.labels[validation],
        )
        fitted = {
            "ridge": _ridge(alpha).fit(data.features[refit], data.labels[refit]),
            "tree": _tree(leaves, iterations).fit(
                data.features[refit], data.labels[refit]
            ),
        }
        models[year], means[year] = fitted, _means(data, refit)
        for family, model in fitted.items():
            predictions[family][test_rows] = model.predict(data.features[test_rows])
            path = output / "models" / f"{year}-{family}.joblib"
            joblib.dump(
                {
                    "model": model,
                    "feature_names": data.feature_names,
                    "year": year,
                    "plan": PLAN,
                    "label_boundary": str(test_start),
                },
                path,
            )
            receipt[f"{family}_model_sha256"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        predictions["mean"][test_rows] = [
            means[year][a] for a in data.actions[test_rows]
        ]
        fit_means = _means(data, fit)
        receipt.update(
            {
                "status": "FITTED",
                "settings": settings,
                "selected_ridge_alpha": alpha,
                "selected_tree_leaves": leaves,
                "selected_tree_iterations": iterations,
                "action_means": means[year],
                "validation_mean_mse": _mse(
                    data.labels[validation],
                    np.asarray([fit_means[a] for a in data.actions[validation]]),
                ),
            }
        )
        _save_receipts(output, receipts, data.feature_names, False)
        print(
            f"selective actions {year}: ridge alpha={alpha:g}; "
            f"tree leaves={leaves}, iterations={iterations}",
            flush=True,
        )
    if not receipts:
        _save_receipts(output, receipts, data.feature_names, False)
        raise ValueError("no candidates in the registered outer test years")
    np.savez_compressed(
        output / "predictions.npz",
        dates=data.dates,
        actions=data.actions,
        **predictions,
    )
    _save_receipts(output, receipts, data.feature_names, True)
    return TrainingResult(models, means, receipts, predictions, data.feature_names)
