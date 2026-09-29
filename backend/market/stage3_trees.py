"""Stage 3, M1: LightGBM, walked forward exactly as the pre-registration fixes it.

`docs/research/stage3-plan-2026-09-29.md` ("M1: LightGBM, the primary
baseline" and "The walk-forward, for every family") fixed every choice
made here before any stage-3 code existed. The numbers live in
`stage3_io` and are read from there, never restated: the grid, the fixed
settings, the bagging fraction per question, the rounds and the patience,
the seeds, the refit cadence, the gap, the winsorization quantiles and
the selection metric.

`walk_forward` runs on one question's `Stage3Data` (``ti`` or ``s1``) in
session-index space, one fold of `stage3_io.folds` at a time:

* Rows. The fit part is every row of sessions [0, fit_end) with a finite
  label, the validation block every row of [val_start, window_end) with a
  finite label, the training window every row of [0, window_end) with a
  finite label, and the test block every row of [test_start, test_end),
  labelled or not. Rows are sorted by date, so each part is a contiguous
  row range: the window is sliced, not copied, when all its labels are
  known, the fit part is a prefix of it and the validation block a suffix.
* Bins. One LightGBM Dataset a fold, binned from the window rows only.
  The fit part and the validation block are subsets of it and share its
  bin mappers; the refit trains on it. A test row never reaches a
  Dataset: it is only predicted, from the trees' thresholds.
* Labels. T-I labels are winsorized at the fit rows' `WINSOR` quantiles,
  and those bounds clip every label that is trained or early-stopped on
  (fit, validation, window). The selection score always reads the raw
  label. T-S1 labels, already a per-date rank-Gauss, are used as they are.
* Selection. Each `LGBM_GRID` configuration is fit with the first seed on
  the fit part and early-stopped on the validation L2 (`LGBM_PATIENCE`
  rounds without improvement, at most `LGBM_MAX_ROUNDS`), then scored with
  `stage3_io.selection_score` on the validation block. The highest score
  is chosen: ties and NaN go to the lowest index, all NaN to the first.
  Each of these fit-part models also predicts the test block, for the PBO
  diagnostic only.
* Refit. The chosen configuration is refit on the window once for each of
  `SEEDS` (`seed`, `bagging_seed` and `feature_fraction_seed` all that
  seed) for max(1, round(best iteration x window rows / fit rows)) rounds,
  without early stopping. The per-seed test predictions are kept and the
  forecast is their mean. A row that is never in a test block keeps NaN
  and fold -1.

The same data on the same threads gives the same forecasts: LightGBM runs
`deterministic` and `force_row_wise`, every seed is fixed, and the
optional permutation importance draws from a generator fixed by the fold.
`permutation_drops` measures how much the chosen fit-part model's
validation score falls when each column is shuffled; `diagnostics`
reports the out-of-sample score by calendar year and every column's
univariate IC on 2016-2019 and 2020-2023. Both are reported and never
promote anything. Nothing here trades.
"""

from __future__ import annotations

import hashlib
import math
import platform
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from backend.market import stage3_io as io

# LightGBM's threads: the plan's num_threads, the RTX desktop's i9-10900K.
DEFAULT_THREADS = 20
# The Dataset's own settings: the registered max_bin, and no feature
# pre-filter. A pre-filter reads min_data_in_leaf, which the grid varies,
# so without this one binned Dataset could not serve every configuration
# and a column's presence would depend on the configuration.
DATASET_PARAMS: dict[str, Any] = {
    "max_bin": io.LGBM_FIXED["max_bin"],
    "feature_pre_filter": False,
    "verbosity": -1,
}
# The validation block's name in LightGBM's evaluation record.
VALIDATION_NAME = "validation"
# Permutation importance: the most validation rows it scores for T-I, and
# the seed its generator is built from (with the fold index).
IMPORTANCE_ROWS = 50_000
IMPORTANCE_SEED = 20260929
# The plan's univariate-IC windows (2016-2023, split in two).
IC_WINDOWS: dict[str, tuple[str, str]] = {
    "2016-2019": ("2016-01-01", "2019-12-31"),
    "2020-2023": ("2020-01-01", "2023-12-31"),
}
# The last day of the choosing window; later test rows are reported only.
CHOOSING_END = "2023-12-31"


@dataclass(frozen=True)
class Settings:
    """The walk-forward's knobs; every default is the registered value."""

    grid: tuple[Mapping[str, Any], ...] = io.LGBM_GRID
    seeds: tuple[int, ...] = io.SEEDS
    min_train: int = io.MIN_TRAIN
    validation: int = io.VALIDATION
    refit: int | None = None  # sessions per test block; None reads REFIT
    gap: int | None = None  # purge + embargo in sessions; None reads GAP
    max_rounds: int = io.LGBM_MAX_ROUNDS
    patience: int = io.LGBM_PATIENCE
    num_threads: int = DEFAULT_THREADS

    # The test-block length for a question: this setting, else the
    # registered cadence (126 sessions for T-I, 63 for T-S1).
    def refit_for(self, kind: str) -> int:
        """Return the sessions per test block for `kind`."""
        return int(io.REFIT[(io.LGBM, kind)] if self.refit is None else self.refit)

    # The purge-plus-embargo gap for a question: this setting, else the
    # registered one (6 for T-I, 26 for T-S1).
    def gap_for(self, kind: str) -> int:
        """Return the gap in sessions for `kind`."""
        return int(io.GAP[kind] if self.gap is None else self.gap)

    # Refuse settings no walk-forward can run with, before anything trains.
    def check(self) -> None:
        """Raise ValueError when a setting is unusable."""
        if not self.grid or not self.seeds:
            raise ValueError("the grid and the seeds must both be non-empty")
        if min(self.max_rounds, self.patience, self.num_threads) < 1:
            raise ValueError("max_rounds, patience and num_threads must be at least 1")

    # The protocol settings as plain values, cadence and gap resolved; the
    # thread count is an execution detail recorded beside them.
    def describe(self, kind: str) -> dict[str, Any]:
        """Return the protocol settings for `kind` as a JSON-ready dict."""
        return {
            "grid": [dict(config) for config in self.grid],
            "seeds": [int(seed) for seed in self.seeds],
            "min_train": int(self.min_train),
            "validation": int(self.validation),
            "refit": self.refit_for(kind),
            "gap": self.gap_for(kind),
            "max_rounds": int(self.max_rounds),
            "patience": int(self.patience),
        }

    # Whether every protocol setting is the pre-registered one, so a test
    # or exploratory run can never be read as the registered result.
    def registered(self, kind: str) -> bool:
        """Return True when the settings are the plan's for `kind`."""
        return self.describe(kind) == Settings().describe(kind)


# The LightGBM parameters of one fit: the registered fixed settings, the
# grid configuration, the question's bagging fraction, one seed for every
# random draw, and the thread count.
def lgbm_params(
    kind: str, config: Mapping[str, Any], seed: int, num_threads: int
) -> dict[str, Any]:
    """Return the parameters LightGBM trains one model with."""
    return {
        **io.LGBM_FIXED,
        **dict(config),
        "bagging_fraction": io.LGBM_BAGGING[kind],
        "seed": int(seed),
        "bagging_seed": int(seed),
        "feature_fraction_seed": int(seed),
        "num_threads": int(num_threads),
    }


# The T-I winsorization bounds: the WINSOR quantiles of the fit rows'
# finite labels (numpy's default linear interpolation).
def winsor_bounds(y_fit: np.ndarray) -> tuple[float, float]:
    """Return (low, high) from the fit rows' labels."""
    values = np.asarray(y_fit, dtype=np.float64)
    values = values[np.isfinite(values)]
    if not len(values):
        raise ValueError("no finite fit labels to take winsorization bounds from")
    low, high = np.quantile(values, io.WINSOR)
    return float(low), float(high)


# The plan's choice: the highest finite selection score; ties go to the
# lowest index, and when no score is finite, configuration 0 is chosen.
def choose_config(scores: Sequence[float | None]) -> int:
    """Return the index of the chosen configuration."""
    chosen, best = 0, -math.inf
    for index, value in enumerate(scores):
        if value is not None and math.isfinite(value) and value > best:
            chosen, best = index, float(value)
    return chosen


# Rounds of the window refit: the chosen configuration's best iteration
# scaled by window rows over fit rows, rounded as Python rounds (half to
# even; the ratio is an exact Fraction, so no float can tip a half), and
# at least one.
def refit_rounds(best_iter: int, n_window: int, n_fit: int) -> int:
    """Return max(1, round(best_iter * n_window / n_fit))."""
    if n_fit <= 0:
        raise ValueError("the fit part has no rows")
    return max(1, round(Fraction(int(best_iter) * int(n_window), int(n_fit))))


@dataclass(frozen=True)
class FoldRows:
    """One fold's rows: the labelled training window and the whole test block."""

    window: slice | np.ndarray  # the labelled rows of [0, window_end), in order
    n_fit: int  # the first n_fit window rows are the fit part
    n_validation: int  # the last n_validation window rows are the validation block
    test: slice  # every row of [test_start, test_end), labelled or not

    # Rows in the training window.
    @property
    def n_window(self) -> int:
        """Return the number of window rows."""
        if isinstance(self.window, slice):
            return int(self.window.stop - self.window.start)
        return int(len(self.window))

    # Rows in the test block.
    @property
    def n_test(self) -> int:
        """Return the number of test rows."""
        return int(self.test.stop - self.test.start)


# A fold's rows from each row's session index (non-decreasing: rows are
# sorted by date) and whether its label is finite. Every part is a
# contiguous row range. The window is a slice when all its labels are
# finite, so it is a view of the data, and otherwise the positions of its
# labelled rows; the test block is a slice of every row, labelled or not.
def fold_rows(fold: io.Fold, index: np.ndarray, finite: np.ndarray) -> FoldRows:
    """Return the rows of `fold`."""
    edges = (
        fold.fit_end,
        fold.val_start,
        fold.window_end,
        fold.test_start,
        fold.test_end,
    )
    fit_hi, val_lo, window_hi, test_lo, test_hi = (
        int(edge) for edge in np.searchsorted(index, edges, side="left")
    )
    n_window = int(np.count_nonzero(finite[:window_hi]))
    window: slice | np.ndarray = (
        slice(0, window_hi)
        if n_window == window_hi
        else np.flatnonzero(finite[:window_hi])
    )
    return FoldRows(
        window=window,
        n_fit=int(np.count_nonzero(finite[:fit_hi])),
        n_validation=int(np.count_nonzero(finite[val_lo:window_hi])),
        test=slice(test_lo, test_hi),
    )


@dataclass(frozen=True)
class _Block:
    """Rows handed to a model: features, raw labels and dates."""

    x: np.ndarray
    y: np.ndarray
    dates: np.ndarray


@dataclass(frozen=True)
class _Outputs:
    """The arrays a walk-forward fills in, one fold's test rows at a time."""

    seeds: np.ndarray  # (R, seeds): the window refits' forecasts
    configs: np.ndarray  # (R, grid): the fit-part models' forecasts (PBO only)
    fold: np.ndarray  # (R,) int32: the fold that forecast the row, -1 if none

    # Outputs for `rows` rows: every forecast NaN, every fold -1.
    @staticmethod
    def empty(rows: int, seeds: int, configs: int) -> _Outputs:
        """Return unfilled outputs."""
        return _Outputs(
            seeds=np.full((rows, seeds), np.nan),
            configs=np.full((rows, configs), np.nan),
            fold=np.full(rows, -1, dtype=np.int32),
        )


# LightGBM, imported only when a model is trained: the unit-gate container
# has none, and nothing else in this module needs it.
def _lightgbm() -> Any:
    try:
        import lightgbm
    except ImportError as error:  # pragma: no cover - the research venv has it
        raise ImportError(
            "stage-3 M1 needs LightGBM, which the research environment provides"
        ) from error
    return lightgbm


# Walk M1 forward over one question's dataset (see the module docstring).
# `settings` defaults to the registered protocol; `max_folds` stops after
# the first folds (the meta records the run as partial); `importance` adds
# the permutation importance on each fold's validation block; `source` is
# the dataset's file, hashed into the meta; `log` receives a header line
# and one line per fold.
def walk_forward(
    data: io.Stage3Data,
    settings: Settings | None = None,
    *,
    max_folds: int | None = None,
    importance: bool = False,
    source: Path | str | None = None,
    log: Callable[[str], None] | None = None,
) -> io.Stage3Forecast:
    """Return the M1 forecast of every row of `data`."""
    settings = Settings() if settings is None else settings
    settings.check()
    io.validate(data)
    lgb = _lightgbm()
    began = time.perf_counter()
    kind = data.kind
    sessions, index = io.session_index(data.dates)
    plan = io.folds(
        len(sessions),
        settings.refit_for(kind),
        settings.gap_for(kind),
        settings.min_train,
        settings.validation,
    )
    run = _limit(plan, max_folds, len(sessions), settings.min_train)
    finite = np.isfinite(data.y)
    out = _Outputs.empty(len(data), len(settings.seeds), len(settings.grid))
    if log is not None:
        log(_header(kind, len(plan), len(run), settings))
    records: list[dict[str, Any]] = []
    drops: list[np.ndarray] = []
    for number, fold in enumerate(run):
        record, fold_drops = _run_fold(
            lgb, data, number, fold_rows(fold, index, finite), settings, out, importance
        )
        record.update(_fold_dates(fold, sessions))
        records.append(record)
        if fold_drops is not None:
            drops.append(fold_drops)
        if log is not None:
            log(progress_line(record, len(run)))
    yhat = out.seeds.mean(axis=1)
    meta = {
        "model": "M1",
        "lightgbm": str(lgb.__version__),
        "num_threads": int(settings.num_threads),
        "settings": settings.describe(kind),
        "registered": settings.registered(kind),
        "folds_total": len(plan),
        "folds_run": len(run),
        "max_folds": max_folds,
        "complete": len(run) == len(plan),
        "folds": records,
        "rows": len(data),
        "labelled_rows": int(np.count_nonzero(finite)),
        "sessions": len(sessions),
        "forecast_rows": int(np.count_nonzero(np.isfinite(yhat))),
        "first_forecast": str(sessions[run[0].test_start]),
        "last_forecast": str(sessions[run[-1].test_end - 1]),
        "importance": (
            importance_ranking(data.feature_names, np.vstack(drops))
            if importance
            else None
        ),
        **_run_meta(data, kind, importance, source),
        "seconds": time.perf_counter() - began,
    }
    return io.Stage3Forecast(
        kind=kind,
        family=io.LGBM,
        dates=data.dates,
        tickers=data.tickers,
        slot=data.slot,
        yhat=yhat,
        yhat_seeds=out.seeds,
        yhat_configs=out.configs,
        fold=out.fold,
        meta=_json_ready(meta),
    )


# The folds a run covers: all of the plan's, or its first `max_folds`. A
# dataset too short for any test block is an error, not an empty forecast.
def _limit(
    plan: list[io.Fold], max_folds: int | None, n_sessions: int, min_train: int
) -> list[io.Fold]:
    if not plan:
        raise ValueError(
            f"no test block: {n_sessions} sessions, and the first block starts"
            f" at session {min_train}"
        )
    if max_folds is None:
        return plan
    if max_folds < 1:
        raise ValueError("max_folds must be at least 1")
    return plan[:max_folds]


# One fold: bin the window, choose the configuration on the validation
# block, refit it on the window with every seed, and fill the fold's test
# rows of `out`. Returns the fold's record and, with `importance`, the
# columns' drops in the validation score.
def _run_fold(
    lgb: Any,
    data: io.Stage3Data,
    number: int,
    rows: FoldRows,
    settings: Settings,
    out: _Outputs,
    importance: bool,
) -> tuple[dict[str, Any], np.ndarray | None]:
    began = time.perf_counter()
    kind = data.kind
    if rows.n_fit == 0 or rows.n_validation == 0:
        raise ValueError(
            f"fold {number}: {rows.n_fit} labelled fit rows and"
            f" {rows.n_validation} labelled validation rows; both must be positive"
        )
    x_window = data.x[rows.window]
    y_window = np.asarray(data.y[rows.window], dtype=np.float64)
    bounds = winsor_bounds(y_window[: rows.n_fit]) if kind == io.TI else None
    label = y_window if bounds is None else np.clip(y_window, bounds[0], bounds[1])
    window_set = _dataset(lgb, x_window, label, settings.num_threads)
    val_lo = rows.n_window - rows.n_validation
    fit_set = window_set.subset(range(rows.n_fit)).construct()
    val_set = window_set.subset(range(val_lo, rows.n_window)).construct()
    validation = _Block(
        x_window[val_lo:], y_window[val_lo:], data.dates[rows.window][val_lo:]
    )
    x_test = data.x[rows.test]
    configs, boosters, config_predictions = _select(
        lgb, kind, settings, fit_set, val_set, validation, x_test
    )
    chosen = choose_config([config["score"] for config in configs])
    best = int(configs[chosen]["best_iter"])
    rounds = refit_rounds(best, rows.n_window, rows.n_fit)
    seed_predictions, trees = _refit(
        lgb, kind, settings, window_set, settings.grid[chosen], rounds, x_test
    )
    out.configs[rows.test] = config_predictions
    out.seeds[rows.test] = seed_predictions
    out.fold[rows.test] = number
    record: dict[str, Any] = {
        "fold": number,
        "rows": {
            "fit": rows.n_fit,
            "validation": rows.n_validation,
            "window": rows.n_window,
            "test": rows.n_test,
        },
        "winsor": list(bounds) if bounds is not None else None,
        "configs": configs,
        "chosen": chosen,
        "chosen_params": dict(settings.grid[chosen]),
        "best_iter": best,
        "score": configs[chosen]["score"],
        "refit_rounds": rounds,
        "refit_trees": trees,
    }
    drops = None
    if importance:
        drops, record["importance"] = _fold_importance(
            boosters[chosen], best, kind, validation, number, settings.num_threads
        )
    record["seconds"] = time.perf_counter() - began
    return record, drops


# The fold's LightGBM Dataset, binned from the window rows only. The raw
# rows are released once binned, so a later parameter clash raises rather
# than silently re-binning.
def _dataset(lgb: Any, x: np.ndarray, label: np.ndarray, num_threads: int) -> Any:
    params = {**DATASET_PARAMS, "num_threads": int(num_threads)}
    return lgb.Dataset(x, label=label, params=params, free_raw_data=True).construct()


# Every grid configuration fit with the first seed on the fit part and
# early-stopped on the validation L2, then scored by the contract's
# selection_score on the raw validation labels; each also predicts the
# test block (for the PBO diagnostic only). Returns the per-configuration
# records, the boosters and the (test rows, grid) predictions.
def _select(
    lgb: Any,
    kind: str,
    settings: Settings,
    fit_set: Any,
    val_set: Any,
    validation: _Block,
    x_test: np.ndarray,
) -> tuple[list[dict[str, Any]], list[Any], np.ndarray]:
    records: list[dict[str, Any]] = []
    boosters: list[Any] = []
    predictions = np.full((len(x_test), len(settings.grid)), np.nan)
    for index, config in enumerate(settings.grid):
        began = time.perf_counter()
        booster = lgb.train(
            lgbm_params(kind, config, settings.seeds[0], settings.num_threads),
            fit_set,
            num_boost_round=settings.max_rounds,
            valid_sets=[val_set],
            valid_names=[VALIDATION_NAME],
            callbacks=[
                lgb.early_stopping(
                    settings.patience, first_metric_only=True, verbose=False
                )
            ],
        )
        best = max(1, int(booster.best_iteration))
        fitted = booster.predict(
            validation.x, num_iteration=best, num_threads=settings.num_threads
        )
        predictions[:, index] = booster.predict(
            x_test, num_iteration=best, num_threads=settings.num_threads
        )
        records.append(
            {
                "config": index,
                "params": dict(config),
                "best_iter": best,
                "val_l2": float(booster.best_score[VALIDATION_NAME]["l2"]),
                "score": io.selection_score(
                    kind, fitted, validation.y, validation.dates
                ),
                "seconds": time.perf_counter() - began,
            }
        )
        boosters.append(booster)
    return records, boosters, predictions


# The chosen configuration refit on the whole window once per seed, for a
# fixed number of rounds (no validation set, no early stopping). Returns
# the (test rows, seeds) predictions and each refit's tree count.
def _refit(
    lgb: Any,
    kind: str,
    settings: Settings,
    window_set: Any,
    config: Mapping[str, Any],
    rounds: int,
    x_test: np.ndarray,
) -> tuple[np.ndarray, list[int]]:
    predictions = np.full((len(x_test), len(settings.seeds)), np.nan)
    trees: list[int] = []
    for index, seed in enumerate(settings.seeds):
        booster = lgb.train(
            lgbm_params(kind, config, seed, settings.num_threads),
            window_set,
            num_boost_round=rounds,
        )
        predictions[:, index] = booster.predict(
            x_test, num_iteration=-1, num_threads=settings.num_threads
        )
        trees.append(int(booster.num_trees()))
    return predictions, trees


# One fold's permutation importance: the chosen configuration's fit-part
# model (the first seed) at its best iteration on the validation block;
# T-I scores at most IMPORTANCE_ROWS of its rows. The generator is fixed by
# the fold index. Returns the drops and the fold's importance record.
def _fold_importance(
    booster: Any,
    best_iter: int,
    kind: str,
    validation: _Block,
    number: int,
    num_threads: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    # The fit-part model's forecast of a block of rows.
    def predict(x: np.ndarray) -> np.ndarray:
        return np.asarray(
            booster.predict(x, num_iteration=best_iter, num_threads=num_threads),
            dtype=np.float64,
        )

    rng = np.random.default_rng((IMPORTANCE_SEED, number))
    limit = IMPORTANCE_ROWS if kind == io.TI else None
    baseline, drops, used = permutation_drops(
        predict, kind, validation.x, validation.y, validation.dates, rng, limit
    )
    return drops, {"baseline": baseline, "rows": used, "drops": drops.tolist()}


# Permutation importance on one block of rows: the selection score of
# `predict` on the block, then, column by column, the score with that
# column shuffled across the rows; a column's importance is the drop. A
# block longer than `max_rows` is first subsampled without replacement
# (kept in row order). Every draw comes from `rng`, so a fixed generator
# gives fixed drops, and the caller's arrays are never modified.
def permutation_drops(
    predict: Callable[[np.ndarray], np.ndarray],
    kind: str,
    x: np.ndarray,
    y: np.ndarray,
    dates: np.ndarray,
    rng: np.random.Generator,
    max_rows: int | None = None,
) -> tuple[float, np.ndarray, int]:
    """Return (the baseline score, the (F,) drops, the rows scored)."""
    if max_rows is not None and len(y) > max_rows:
        pick = np.sort(rng.choice(len(y), size=max_rows, replace=False))
        work, y, dates = np.ascontiguousarray(x[pick]), y[pick], dates[pick]
    else:
        work = np.array(x, order="C", copy=True)
    baseline = fast_score(kind, predict(work), y, dates)
    drops = np.full(work.shape[1], np.nan)
    for column in range(work.shape[1]):
        kept = work[:, column].copy()
        work[:, column] = kept[rng.permutation(len(kept))]
        drops[column] = baseline - fast_score(kind, predict(work), y, dates)
        work[:, column] = kept
    return baseline, drops, int(len(y))


# The fold-averaged permutation importance, largest mean drop first (ties
# and columns with no finite drop in column order): each column's mean and
# standard deviation over the folds where its drop is finite, and how many
# folds that is.
def importance_ranking(names: Sequence[str], drops: np.ndarray) -> list[dict[str, Any]]:
    """Return one record per column, ranked by mean drop."""
    drops = np.asarray(drops, dtype=np.float64).reshape(-1, len(names))
    means = np.full(len(names), np.nan)
    spreads = np.full(len(names), np.nan)
    counts = np.count_nonzero(np.isfinite(drops), axis=0)
    for column in np.flatnonzero(counts):
        values = drops[np.isfinite(drops[:, column]), column]
        means[column], spreads[column] = float(values.mean()), float(values.std())
    key = np.where(np.isfinite(means), -means, np.inf)
    order = np.lexsort((np.arange(len(names)), key))
    return [
        {
            "rank": rank + 1,
            "feature": str(names[column]),
            "column": int(column),
            "drop": means[column],
            "std": spreads[column],
            "folds": int(counts[column]),
        }
        for rank, column in enumerate(order)
    ]


# The diagnostics the plan reports and never promotes on: the selection
# score (`fast_score`, the contract's metric) of the ensemble on the test
# rows by calendar year; the ensemble, each seed and each grid
# configuration on the choosing window (to 2023) and the later one (2024
# on); and every column's univariate IC on 2016-2019 and 2020-2023 over
# all the dataset's rows. JSON-ready: NaN becomes None.
def diagnostics(data: io.Stage3Data, forecast: io.Stage3Forecast) -> dict[str, Any]:
    """Return the diagnostics of `forecast` against the dataset it forecasts."""
    _check_keys(data, forecast)
    payload = {
        "kind": data.kind,
        "family": forecast.family,
        "oos": _oos(data.kind, forecast, np.asarray(data.y, dtype=np.float64)),
        "univariate_ic": univariate_ic(data),
    }
    ready: dict[str, Any] = _json_ready(payload)
    return ready


# Refuse a forecast whose rows are not the dataset's, key for key.
def _check_keys(data: io.Stage3Data, forecast: io.Stage3Forecast) -> None:
    same = (
        forecast.kind == data.kind
        and len(forecast.dates) == len(data)
        and np.array_equal(forecast.dates, data.dates)
        and np.array_equal(forecast.tickers, data.tickers)
        and np.array_equal(forecast.slot, data.slot)
    )
    if not same:
        raise ValueError("the forecast's rows are not the dataset's rows")


# Out-of-sample scores: the ensemble by calendar year of the test rows, and
# the ensemble, every seed and every configuration on the choosing and
# later windows.
def _oos(kind: str, forecast: io.Stage3Forecast, y: np.ndarray) -> dict[str, Any]:
    dates = np.asarray(forecast.dates, dtype="datetime64[D]")
    tested = np.asarray(forecast.fold) >= 0
    years = dates.astype("datetime64[Y]").astype(np.int64) + 1970
    by_year = {
        str(int(year)): _scored(kind, forecast.yhat, y, dates, tested & (years == year))
        for year in np.unique(years[tested])
    }
    end = np.datetime64(CHOOSING_END, "D")
    windows = {"choosing": tested & (dates <= end), "later": tested & (dates > end)}
    configs = forecast.yhat_configs
    return {
        "by_year": by_year,
        "windows": {
            name: {
                "ensemble": _scored(kind, forecast.yhat, y, dates, mask),
                "seeds": [
                    _scored(kind, column, y, dates, mask)
                    for column in forecast.yhat_seeds.T
                ],
                "configs": (
                    []
                    if configs is None
                    else [_scored(kind, column, y, dates, mask) for column in configs.T]
                ),
            }
            for name, mask in windows.items()
        },
    }


# One score over the rows of `mask`, with the labelled pairs and the
# sessions behind it.
def _scored(
    kind: str, values: np.ndarray, y: np.ndarray, dates: np.ndarray, mask: np.ndarray
) -> dict[str, Any]:
    rows = np.flatnonzero(mask)
    values = np.asarray(values, dtype=np.float64)[rows]
    pairs = int(np.count_nonzero(np.isfinite(values) & np.isfinite(y[rows])))
    return {
        "score": fast_score(kind, values, y[rows], dates[rows]) if pairs else math.nan,
        "pairs": pairs,
        "sessions": int(len(np.unique(dates[rows]))),
    }


# Every column's univariate IC with the raw label on each window's rows:
# pooled Spearman for T-I, the mean daily Spearman IC for T-S1 (the plan's
# metric, `fast_score`). Rows are sorted by date, so a window is a
# contiguous row range. A window with no rows gives None.
def univariate_ic(
    data: io.Stage3Data, windows: Mapping[str, tuple[str, str]] = IC_WINDOWS
) -> dict[str, Any]:
    """Return {windows: their row counts, columns: one IC record per column}."""
    y = np.asarray(data.y, dtype=np.float64)
    dates = np.asarray(data.dates, dtype="datetime64[D]")
    spans = {
        name: (
            int(np.searchsorted(dates, np.datetime64(start, "D"), side="left")),
            int(np.searchsorted(dates, np.datetime64(end, "D"), side="right")),
        )
        for name, (start, end) in windows.items()
    }
    columns: list[dict[str, Any]] = []
    for column, feature in enumerate(data.feature_names):
        entry: dict[str, Any] = {"feature": feature}
        for name, (lo, hi) in spans.items():
            entry[name] = (
                fast_score(data.kind, data.x[lo:hi, column], y[lo:hi], dates[lo:hi])
                if hi > lo
                else math.nan
            )
        columns.append(entry)
    return {
        "windows": {
            name: {
                "start": windows[name][0],
                "end": windows[name][1],
                "rows": hi - lo,
                "sessions": int(len(np.unique(dates[lo:hi]))),
            }
            for name, (lo, hi) in spans.items()
        },
        "columns": columns,
    }


# Average 1-based ranks with ties split, vectorized: the same values as the
# contract's element-by-element loop (`stage3_io._average_ranks`), which is
# too slow for the T-I dataset's hundreds of thousands of rows per column.
def average_ranks(values: np.ndarray) -> np.ndarray:
    """Return the average ranks of `values` (ties share their mean rank)."""
    values = np.asarray(values, dtype=np.float64)
    ranks = np.empty(len(values))
    if not len(values):
        return ranks
    order = np.argsort(values, kind="mergesort")
    ordered = values[order]
    starts = np.flatnonzero(np.concatenate(([True], ordered[1:] != ordered[:-1])))
    ends = np.append(starts[1:], len(values)) - 1
    ranks[order] = np.repeat((starts + ends) / 2.0 + 1.0, ends - starts + 1)
    return ranks


# Spearman correlation over the jointly finite pairs, computed as the
# contract's `spearman` computes it, with vectorized ranks.
def fast_spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Return the Spearman rank correlation over the finite pairs."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    keep = np.isfinite(a) & np.isfinite(b)
    if np.count_nonzero(keep) < 3:
        return math.nan
    ra = average_ranks(a[keep])
    rb = average_ranks(b[keep])
    ra -= ra.mean()
    rb -= rb.mean()
    denominator = math.sqrt(float(ra @ ra) * float(rb @ rb))
    return float(ra @ rb) / denominator if denominator > 0 else math.nan


# The plan's selection metric exactly as `stage3_io.selection_score`
# defines it (pooled Spearman for T-I; for T-S1 the mean of the per-date
# Spearman ICs over dates with at least S1_MIN_NAMES finite pairs), with
# vectorized ranks and one grouping pass over the dates. Used where the
# score is taken many times on large blocks - the permutation importance
# and the diagnostics; the configuration choice calls the contract's own.
def fast_score(kind: str, yhat: np.ndarray, y: np.ndarray, dates: np.ndarray) -> float:
    """Return the selection score of `yhat` against `y`."""
    yhat = np.asarray(yhat, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if kind == io.TI:
        return fast_spearman(yhat, y)
    if kind != io.S1:
        raise ValueError(f"unknown kind {kind!r}")
    if not len(y):
        return math.nan
    _, index = io.session_index(dates)
    order = np.argsort(index, kind="stable")
    cuts = np.searchsorted(index[order], np.arange(int(index.max()) + 2))
    finite = np.isfinite(yhat) & np.isfinite(y)
    ics = []
    for group in range(len(cuts) - 1):
        rows = order[cuts[group] : cuts[group + 1]]
        keep = rows[finite[rows]]
        if len(keep) >= io.S1_MIN_NAMES:
            ic = fast_spearman(yhat[keep], y[keep])
            if math.isfinite(ic):
                ics.append(ic)
    return float(np.mean(ics)) if ics else math.nan


# The sha256 of a file, read in 16 MB chunks (the T-I dataset is ~2 GB).
def file_sha256(path: Path | str) -> str:
    """Return the hex sha256 of the file at `path`."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1 << 24):
            digest.update(chunk)
    return digest.hexdigest()


# The run-level meta that does not depend on the folds: the environment
# (results are reproducible on the same versions and threads), the fixed
# parameters, the dataset's own meta, its file and its hash.
def _run_meta(
    data: io.Stage3Data, kind: str, importance: bool, source: Path | str | None
) -> dict[str, Any]:
    return {
        "numpy": np.__version__,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "fixed_params": dict(io.LGBM_FIXED),
        "bagging_fraction": io.LGBM_BAGGING[kind],
        "dataset_params": dict(DATASET_PARAMS),
        "winsor_quantiles": list(io.WINSOR) if kind == io.TI else None,
        "feature_names": list(data.feature_names),
        "importance_settings": (
            {
                "max_rows_ti": IMPORTANCE_ROWS,
                "seed": IMPORTANCE_SEED,
                "measure": "validation score minus the score with the column shuffled",
            }
            if importance
            else None
        ),
        "dataset_meta": dict(data.meta),
        "dataset_file": str(source) if source is not None else None,
        "dataset_sha256": file_sha256(source) if source is not None else None,
    }


# A fold's session boundaries and the dates they fall on.
def _fold_dates(fold: io.Fold, sessions: np.ndarray) -> dict[str, Any]:
    return {
        "sessions": asdict(fold),
        "fit_last": str(sessions[fold.fit_end - 1]),
        "validation_first": str(sessions[fold.val_start]),
        "validation_last": str(sessions[fold.window_end - 1]),
        "test_first": str(sessions[fold.test_start]),
        "test_last": str(sessions[fold.test_end - 1]),
    }


# The line announcing a run: the question, the folds, the protocol, the
# threads, and whether the settings are the registered ones.
def _header(kind: str, planned: int, running: int, settings: Settings) -> str:
    verdict = "registered" if settings.registered(kind) else "NOT the registered"
    return (
        f"M1 LightGBM on {kind}: {running} of {planned} folds (test blocks of"
        f" {settings.refit_for(kind)} sessions, gap {settings.gap_for(kind)});"
        f" {len(settings.grid)} configurations with seed {settings.seeds[0]},"
        f" the chosen one refit with {len(settings.seeds)} seeds;"
        f" {settings.num_threads} threads; {verdict} settings"
    )


# One fold's progress line: its index (the forecast's fold number), its
# test dates, the chosen configuration, its best iteration and validation
# score, the refit, and the time the fold took.
def progress_line(record: Mapping[str, Any], folds: int) -> str:
    """Return the progress line of one fold's record."""
    params = record["chosen_params"]
    return (
        f"fold {record['fold']} of {folds}: test {record['test_first']}.."
        f"{record['test_last']} ({record['rows']['test']:,} rows); chosen"
        f" #{record['chosen']} (num_leaves {params.get('num_leaves')},"
        f" learning_rate {params.get('learning_rate')}, min_data_in_leaf"
        f" {params.get('min_data_in_leaf')}), best_iter {record['best_iter']},"
        f" validation score {_signed(record['score'])}; refit"
        f" {record['refit_rounds']} rounds x {len(record['refit_trees'])} seeds;"
        f" {record['seconds']:.1f} s"
    )


# A score with its sign, or "nan".
def _signed(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "nan"
    return f"{value:+.4f}"


# Plain JSON values: numpy scalars and arrays unwrapped, tuples as lists,
# dates as ISO text, non-finite floats as None (so a payload writes with
# allow_nan=False and reads back the same everywhere).
def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.datetime64):
        return str(value)
    return value
