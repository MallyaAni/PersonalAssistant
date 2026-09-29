"""Stage 3's shared contract: the frozen registration, the files, the folds.

`docs/research/stage3-plan-2026-09-29.md` fixed every number a stage-3 run
uses before any stage-3 code existed; they live here once, so the feature
export, the tree and network trainers and the decision tests read the same
values and a change to any of them is a visible, counted edit of this file.

Two datasets (`Stage3Data`), one per question:

* ``ti`` - "now or the close": one row per (name, session s, slot k),
  k = 0..23, the label `y` = 1e4 * ln(official close / bar k's close) in bp.
* ``s1`` - "which graded names to hold": one row per (name, decision date
  t), the label `y` the per-date rank-Gauss of the 20-session relative
  open-to-open return, `r` that return itself (the chart CNN's label is
  whether it is above the date's median).

Every file is an ``.npz`` of plain arrays plus one JSON ``meta`` string, so
the Spark (which builds it from the store) and the RTX desktop (which
trains on it) need nothing in common but numpy. Rows are sorted by (date,
ticker, slot).

The walk-forward (`folds`) works in *session index* space: the sorted
unique row dates. A test block [b, e) trains on sessions [0, b - gap); the
nested validation block is the last `VALIDATION` sessions of that window,
the fit part ends `gap` sessions before it. The gap is the label's purge
plus the embargo (26 for ``s1``, 6 for ``ti``). Test blocks never touch a
choice.

A trainer writes a `Stage3Forecast`: the ensemble forecast per row (NaN
where the row was never out of sample), the per-seed forecasts, optionally
every grid configuration's fit-part forecast (for the PBO diagnostic), the
fold of each row, and a JSON record of what was chosen in each fold.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np

# The plan this module freezes, carried in every file's meta.
PLAN = "docs/research/stage3-plan-2026-09-29.md"
# File format version: bump when a key or its meaning changes.
FORMAT_VERSION = 1

# The two questions.
TI = "ti"
S1 = "s1"
KINDS = (TI, S1)

# T-I: the slots that carry a row (bars closing 09:45..15:30).
TI_SLOTS = 24
# T-S1: the label runs open to open over this many sessions, from the
# session after the decision; its purge is the label's reach past t.
S1_HORIZON = 20
S1_LABEL_REACH = S1_HORIZON + 1

# The walk-forward: sessions of rows before the first test block, the
# nested validation block, and the purge + embargo gap per question.
MIN_TRAIN = 500
VALIDATION = 252
EMBARGO = 5
GAP = {S1: S1_LABEL_REACH + EMBARGO, TI: 1 + EMBARGO}

# Model families and their refit cadence (sessions per test block).
LGBM = "lgbm"
SEQ = "seq"
CNN_I5 = "cnn_i5"
CNN_I20 = "cnn_i20"
FAMILIES = {TI: (LGBM, SEQ), S1: (LGBM, CNN_I5, CNN_I20, SEQ)}
REFIT = {
    (LGBM, S1): 63,
    (LGBM, TI): 126,
    (SEQ, S1): 252,
    (SEQ, TI): 252,
    (CNN_I5, S1): 252,
    (CNN_I20, S1): 252,
}

# Seeds of every ensemble; the grid is chosen with the first.
SEEDS = (0, 1, 2, 3, 4)

# M1: LightGBM. The 8-configuration grid and the fixed settings.
LGBM_GRID = tuple(
    {"num_leaves": leaves, "learning_rate": rate, "min_data_in_leaf": leaf}
    for leaves in (15, 63)
    for rate in (0.02, 0.05)
    for leaf in (200, 1000)
)
LGBM_FIXED: dict[str, Any] = {
    "objective": "regression",
    "metric": "l2",
    "feature_fraction": 0.7,
    "bagging_freq": 1,
    "lambda_l2": 10.0,
    "max_bin": 255,
    "max_depth": -1,
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}
LGBM_BAGGING = {S1: 0.7, TI: 0.3}
LGBM_MAX_ROUNDS = 3000
LGBM_PATIENCE = 200

# M3: the sequence model's grid and fixed settings.
SEQ_GRID = tuple(
    {"lr": lr, "dropout": dropout, "width": width}
    for lr in (3e-4, 1e-3)
    for dropout in (0.1, 0.3)
    for width in (32, 64)
)
SEQ_FIXED: dict[str, Any] = {
    "optimizer": "AdamW",
    "weight_decay": 1e-2,
    "batch": 512,
    "clip": 1.0,
    "max_epochs": 60,
    "patience": 6,
    "warmup_share": 0.05,
    "schedule": "cosine",
    "kernel": 3,
    "dilations": (1, 2, 4, 8, 16),
}
# Sessions of bars in a sequence row, per question; steps per session
# (the overnight gap step, then the 26 bars).
SEQ_SESSIONS = {TI: 6, S1: 60}
STEPS_PER_SESSION = 27
SEQ_CHANNELS = (
    "z",
    "since_open",
    "vwap_distance",
    "prior_close_distance",
    "prior_high_distance",
    "prior_low_distance",
    "ema21_15m_distance",
    "rvol",
    "side_relative",
    "spy",
    "opening_range_position",
    "gap_step",
)

# M2: the Jiang-Kelly-Xiu CNN, as published.
CNN_FIXED: dict[str, Any] = {
    "optimizer": "Adam",
    "lr": 1e-5,
    "batch": 128,
    "patience": 2,
    "max_epochs": 100,
    "dropout": 0.5,
    "leaky_slope": 0.01,
}
CNN_IMAGES = {CNN_I5: (5, 32, 15), CNN_I20: (20, 64, 60)}  # days, height, width

# Robust scaling for the networks: clip after the median/IQR z.
NET_CLIP = 5.0
# T-I labels are winsorized at these fit-part quantiles, for training only.
WINSOR = (0.005, 0.995)

# The decision tests' floors and the multiplicity gate.
FLOOR_BP = 2.0
FLOOR_T = 2.0
HAC_LAG = 20
OUTER_CANDIDATES = 8
CONFIG_TRIALS = 50
CUMULATIVE_TRIALS = 282
DEFLATED_SHARPE_GATE = 0.95
IMMATERIAL_BP_PER_ORDER = 25.0
IMMATERIAL_T = 3.0
S1_DROP_SHARE = 0.1
S1_MIN_NAMES = 5


@dataclass(frozen=True)
class Stage3Data:
    """One question's rows: features, labels, keys."""

    kind: str
    dates: np.ndarray  # (R,) datetime64[D]: session s (ti) or decision date t (s1)
    tickers: np.ndarray  # (R,) str
    slot: np.ndarray  # (R,) int8, the slot for ti; all zero for s1
    x: np.ndarray  # (R, F) float32
    feature_names: tuple[str, ...]
    y: np.ndarray  # (R,) float32, NaN where the label is unknown
    extra: dict[str, np.ndarray] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    # Rows in the dataset.
    def __len__(self) -> int:
        return int(len(self.dates))


# Check a dataset's arrays agree in length and kind before it is written or
# trained on, so a malformed export fails where it was made.
def validate(data: Stage3Data) -> None:
    """Raise ValueError when the dataset's arrays disagree."""
    if data.kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {data.kind!r}")
    rows = len(data.dates)
    for name, array in (("tickers", data.tickers), ("slot", data.slot), ("y", data.y)):
        if len(array) != rows:
            raise ValueError(f"{name} has {len(array)} rows; dates has {rows}")
    if data.x.shape != (rows, len(data.feature_names)):
        raise ValueError(
            f"x is {data.x.shape}; expected ({rows}, {len(data.feature_names)})"
        )
    for name, array in data.extra.items():
        if len(array) != rows:
            raise ValueError(f"extra {name!r} has {len(array)} rows; dates has {rows}")
    if rows:
        order = np.lexsort((data.slot, data.tickers, data.dates))
        if not np.array_equal(order, np.arange(rows)):
            raise ValueError("rows must be sorted by (date, ticker, slot)")


# Write a dataset as one .npz: the arrays, the extras under "extra_<name>",
# and a JSON meta string carrying the plan and the format version.
def save_data(path: Path, data: Stage3Data) -> Path:
    """Write `data` to `path` (.npz) and return the path."""
    validate(data)
    meta = {**data.meta, "plan": PLAN, "format": FORMAT_VERSION, "kind": data.kind}
    arrays = {
        "dates": np.asarray(data.dates, dtype="datetime64[D]"),
        "tickers": np.asarray(data.tickers, dtype=str),
        "slot": np.asarray(data.slot, dtype=np.int8),
        "x": np.asarray(data.x, dtype=np.float32),
        "feature_names": np.asarray(data.feature_names, dtype=str),
        "y": np.asarray(data.y, dtype=np.float32),
        "meta": np.asarray(json.dumps(meta, sort_keys=True, default=str)),
    }
    for name, array in data.extra.items():
        arrays[f"extra_{name}"] = np.asarray(array)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.savez(handle, **arrays)
    return path


# Read a dataset written by `save_data`, refusing another format version.
def load_data(path: Path) -> Stage3Data:
    """Return the Stage3Data stored at `path`."""
    with np.load(Path(path), allow_pickle=False) as npz:
        meta = json.loads(str(npz["meta"]))
        if meta.get("format") != FORMAT_VERSION:
            raise ValueError(f"{path}: format {meta.get('format')}, expected {FORMAT_VERSION}")
        extra = {
            key[len("extra_") :]: npz[key] for key in npz.files if key.startswith("extra_")
        }
        data = Stage3Data(
            kind=str(meta["kind"]),
            dates=npz["dates"].astype("datetime64[D]"),
            tickers=npz["tickers"].astype(str),
            slot=npz["slot"].astype(np.int8),
            x=npz["x"].astype(np.float32),
            feature_names=tuple(str(n) for n in npz["feature_names"]),
            y=npz["y"].astype(np.float32),
            extra=extra,
            meta=meta,
        )
    validate(data)
    return data


# The sorted unique session dates of a dataset and each row's index into them.
def session_index(dates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return ((S,) unique sessions, (R,) each row's session index)."""
    sessions, index = np.unique(np.asarray(dates, dtype="datetime64[D]"), return_inverse=True)
    return sessions, index.astype(np.int64)


@dataclass(frozen=True)
class Fold:
    """One walk-forward step, in session-index space (half-open ranges)."""

    test_start: int
    test_end: int
    window_end: int  # training window [0, window_end)
    fit_end: int  # fit part [0, fit_end)
    val_start: int  # validation [val_start, window_end)

    # The rows of a session-index array that fall in [lo, hi).
    @staticmethod
    def rows(index: np.ndarray, lo: int, hi: int) -> np.ndarray:
        """Return the row positions whose session index is in [lo, hi)."""
        return np.nonzero((index >= lo) & (index < hi))[0]


# The expanding walk-forward: first test block at MIN_TRAIN, blocks of
# `refit` sessions to the end, each training on [0, test_start - gap), with
# the last VALIDATION sessions of that window as the nested validation
# block and the fit part ending `gap` sessions before it. A fold whose fit
# part would be empty is an error, not a silent skip.
def folds(
    n_sessions: int,
    refit: int,
    gap: int,
    min_train: int = MIN_TRAIN,
    validation: int = VALIDATION,
) -> list[Fold]:
    """Return the walk-forward folds for `n_sessions` sessions."""
    if refit <= 0 or gap < 0 or validation <= 0:
        raise ValueError("refit and validation must be positive and gap non-negative")
    out: list[Fold] = []
    start = min_train
    while start < n_sessions:
        end = min(start + refit, n_sessions)
        window_end = start - gap
        val_start = window_end - validation
        fit_end = val_start - gap
        if fit_end <= 0:
            raise ValueError(
                f"fold at {start}: no fit sessions (window {window_end}, "
                f"validation {validation}, gap {gap})"
            )
        out.append(Fold(start, end, window_end, fit_end, val_start))
        start = end
    return out


# The standard normal quantile, vectorized: scipy's ndtri where scipy is
# installed (every research environment has it through scikit-learn or
# LightGBM), else the standard library's, element by element.
def norm_ppf(p: np.ndarray) -> np.ndarray:
    """Return Phi^-1(p) elementwise; NaN stays NaN."""
    p = np.asarray(p, dtype=float)
    try:
        from scipy.special import ndtri
    except ImportError:  # pragma: no cover - every research venv has scipy
        inverse = NormalDist().inv_cdf
        out = np.full(p.shape, np.nan)
        finite = np.isfinite(p)
        out[finite] = [inverse(float(v)) for v in p[finite]]
        return out
    return ndtri(p)


# Per-date rank-Gauss: Phi^-1((rank - 0.5) / n) over the finite values of
# each date, ties at their average rank; NaN stays NaN, a date with one
# finite value maps it to 0.
def rank_gauss(values: np.ndarray, dates: np.ndarray) -> np.ndarray:
    """Return the per-date rank-Gauss transform of `values`."""
    values = np.asarray(values, dtype=float)
    out = np.full(values.shape, np.nan)
    if not len(values):
        return out
    _, index = session_index(dates)
    order = np.argsort(index, kind="stable")
    bounds = np.searchsorted(index[order], np.arange(int(index.max()) + 2))
    for g in range(len(bounds) - 1):
        rows = order[bounds[g] : bounds[g + 1]]
        rows = rows[np.isfinite(values[rows])]
        n = len(rows)
        if n == 0:
            continue
        out[rows] = norm_ppf((_average_ranks(values[rows]) - 0.5) / n)
    return out


# Rank-Gauss across names for every (date, column) of a (T, N, F) panel,
# over the names `mask` marks eligible on that date; everything else NaN.
# Vectorized over dates and columns: average ranks from a double argsort
# with ties split by the sorted run lengths.
def rank_gauss_panel(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return the (T, N, F) per-date cross-sectional rank-Gauss of `values`."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 3 or mask.shape != values.shape[:2]:
        raise ValueError("values must be (T, N, F) and mask (T, N)")
    live = np.where(mask[:, :, None] & np.isfinite(values), values, np.nan)
    out = np.full(values.shape, np.nan)
    t_count, _, f_count = values.shape
    for t in range(t_count):
        block = live[t]  # (N, F)
        for f in range(f_count):
            column = block[:, f]
            keep = np.nonzero(np.isfinite(column))[0]
            n = len(keep)
            if n == 0:
                continue
            out[t, keep, f] = norm_ppf((_average_ranks(column[keep]) - 0.5) / n)
    return out


# Average 1-based ranks with ties split.
def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values))
    sorted_values = values[order]
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


# Spearman correlation of two arrays over their jointly finite entries.
def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Return the Spearman rank correlation over the finite pairs."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    keep = np.isfinite(a) & np.isfinite(b)
    if keep.sum() < 3:
        return math.nan
    ra = _average_ranks(a[keep])
    rb = _average_ranks(b[keep])
    ra -= ra.mean()
    rb -= rb.mean()
    denominator = math.sqrt(float(ra @ ra) * float(rb @ rb))
    return float(ra @ rb) / denominator if denominator > 0 else math.nan


# The selection metric of the plan: pooled Spearman for T-I, the mean of
# the per-date Spearman IC for T-S1 (dates with at least S1_MIN_NAMES rows).
def selection_score(kind: str, yhat: np.ndarray, y: np.ndarray, dates: np.ndarray) -> float:
    """Return the validation score a configuration is chosen on."""
    if kind == TI:
        return spearman(yhat, y)
    if kind != S1:
        raise ValueError(f"unknown kind {kind!r}")
    _, index = session_index(dates)
    ics = []
    for g in np.unique(index):
        rows = np.nonzero(index == g)[0]
        keep = rows[np.isfinite(yhat[rows]) & np.isfinite(y[rows])]
        if len(keep) >= S1_MIN_NAMES:
            ic = spearman(yhat[keep], y[keep])
            if math.isfinite(ic):
                ics.append(ic)
    return float(np.mean(ics)) if ics else math.nan


@dataclass(frozen=True)
class Stage3Forecast:
    """A family's out-of-sample forecasts for one question."""

    kind: str
    family: str
    dates: np.ndarray  # (R,) the dataset's keys, same order
    tickers: np.ndarray
    slot: np.ndarray
    yhat: np.ndarray  # (R,) the seed ensemble; NaN where never out of sample
    yhat_seeds: np.ndarray  # (R, len(SEEDS))
    yhat_configs: np.ndarray | None  # (R, grid size) fit-part forecasts, or None
    fold: np.ndarray  # (R,) int, the fold that predicted the row, -1 if none
    meta: dict[str, Any] = field(default_factory=dict)


# Write a forecast file (.npz) with its JSON meta.
def save_forecast(path: Path, forecast: Stage3Forecast) -> Path:
    """Write `forecast` to `path` and return the path."""
    rows = len(forecast.dates)
    if forecast.yhat.shape != (rows,) or forecast.yhat_seeds.shape[0] != rows:
        raise ValueError("forecast arrays disagree with the keys")
    meta = {
        **forecast.meta,
        "plan": PLAN,
        "format": FORMAT_VERSION,
        "kind": forecast.kind,
        "family": forecast.family,
    }
    arrays = {
        "dates": np.asarray(forecast.dates, dtype="datetime64[D]"),
        "tickers": np.asarray(forecast.tickers, dtype=str),
        "slot": np.asarray(forecast.slot, dtype=np.int8),
        "yhat": np.asarray(forecast.yhat, dtype=np.float32),
        "yhat_seeds": np.asarray(forecast.yhat_seeds, dtype=np.float32),
        "fold": np.asarray(forecast.fold, dtype=np.int32),
        "meta": np.asarray(json.dumps(meta, sort_keys=True, default=str)),
    }
    if forecast.yhat_configs is not None:
        arrays["yhat_configs"] = np.asarray(forecast.yhat_configs, dtype=np.float32)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.savez(handle, **arrays)
    return path


# Read a forecast file written by `save_forecast`.
def load_forecast(path: Path) -> Stage3Forecast:
    """Return the Stage3Forecast stored at `path`."""
    with np.load(Path(path), allow_pickle=False) as npz:
        meta = json.loads(str(npz["meta"]))
        if meta.get("format") != FORMAT_VERSION:
            raise ValueError(f"{path}: format {meta.get('format')}, expected {FORMAT_VERSION}")
        return Stage3Forecast(
            kind=str(meta["kind"]),
            family=str(meta["family"]),
            dates=npz["dates"].astype("datetime64[D]"),
            tickers=npz["tickers"].astype(str),
            slot=npz["slot"].astype(np.int8),
            yhat=npz["yhat"].astype(np.float32),
            yhat_seeds=npz["yhat_seeds"].astype(np.float32),
            yhat_configs=npz["yhat_configs"].astype(np.float32)
            if "yhat_configs" in npz.files
            else None,
            fold=npz["fold"].astype(np.int32),
            meta=meta,
        )


# The T-I forecast as a lookup the fill engine reads: for each (ticker,
# session) the (TI_SLOTS,) forecast vector, NaN where a slot has none.
def ti_lookup(forecast: Stage3Forecast, column: np.ndarray | None = None) -> dict[
    tuple[str, np.datetime64], np.ndarray
]:
    """Return {(ticker, session): (TI_SLOTS,) forecasts} from a T-I forecast."""
    if forecast.kind != TI:
        raise ValueError("ti_lookup needs a T-I forecast")
    values = forecast.yhat if column is None else np.asarray(column, dtype=float)
    out: dict[tuple[str, np.datetime64], np.ndarray] = {}
    for i in range(len(forecast.dates)):
        key = (str(forecast.tickers[i]), np.datetime64(forecast.dates[i], "D"))
        vector = out.get(key)
        if vector is None:
            vector = np.full(TI_SLOTS, np.nan)
            out[key] = vector
        k = int(forecast.slot[i])
        if 0 <= k < TI_SLOTS:
            vector[k] = values[i]
    return out


# Column-name prefixes: every daily-block column starts with DAILY_PREFIX,
# every intraday-block column with INTRADAY_PREFIX. The sequence model's
# daily branch reads only the daily columns; its intraday information comes
# from the sequence tensor, not the tabular intraday block.
DAILY_PREFIX = "d_"
INTRADAY_PREFIX = "i_"


# The indices of the daily-block columns of a dataset.
def daily_columns(feature_names: tuple[str, ...]) -> np.ndarray:
    """Return the positions of the columns whose names start with DAILY_PREFIX."""
    return np.array(
        [i for i, name in enumerate(feature_names) if name.startswith(DAILY_PREFIX)],
        dtype=np.int64,
    )


@dataclass(frozen=True)
class SeqTensor:
    """Every name's cube sessions as (gap step + 26 bars) x SEQ_CHANNELS."""

    tickers: np.ndarray  # (N,) str
    sessions: np.ndarray  # (S,) datetime64[D], the union of cube sessions, ascending
    seq: np.ndarray  # (N, S, STEPS_PER_SESSION, len(SEQ_CHANNELS)) float16
    valid: np.ndarray  # (N, S) bool: the name has a complete cube session that day
    meta: dict[str, Any] = field(default_factory=dict)


# Write the sequence tensor (.npz, uncompressed so it can be memory-mapped
# after extraction) with its meta.
def save_seq(path: Path, tensor: SeqTensor) -> Path:
    """Write `tensor` to `path` and return the path."""
    n, s = len(tensor.tickers), len(tensor.sessions)
    expected = (n, s, STEPS_PER_SESSION, len(SEQ_CHANNELS))
    if tensor.seq.shape != expected or tensor.valid.shape != (n, s):
        raise ValueError(f"seq is {tensor.seq.shape}, valid {tensor.valid.shape}; expected {expected}")
    meta = {**tensor.meta, "plan": PLAN, "format": FORMAT_VERSION, "channels": list(SEQ_CHANNELS)}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.savez(
            handle,
            tickers=np.asarray(tensor.tickers, dtype=str),
            sessions=np.asarray(tensor.sessions, dtype="datetime64[D]"),
            seq=np.asarray(tensor.seq, dtype=np.float16),
            valid=np.asarray(tensor.valid, dtype=bool),
            meta=np.asarray(json.dumps(meta, sort_keys=True, default=str)),
        )
    return path


# Read a sequence tensor written by `save_seq`.
def load_seq(path: Path) -> SeqTensor:
    """Return the SeqTensor stored at `path`."""
    with np.load(Path(path), allow_pickle=False) as npz:
        meta = json.loads(str(npz["meta"]))
        if meta.get("format") != FORMAT_VERSION or tuple(meta.get("channels", ())) != SEQ_CHANNELS:
            raise ValueError(f"{path}: format or channels differ from this module's")
        return SeqTensor(
            tickers=npz["tickers"].astype(str),
            sessions=npz["sessions"].astype("datetime64[D]"),
            seq=npz["seq"],
            valid=npz["valid"].astype(bool),
            meta=meta,
        )


@dataclass(frozen=True)
class DailyOHLCV:
    """The dividend-adjusted daily bars the chart images are drawn from."""

    tickers: np.ndarray  # (N,) str
    dates: np.ndarray  # (T,) datetime64[D]
    open: np.ndarray  # (T, N) float32, NaN where missing
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    meta: dict[str, Any] = field(default_factory=dict)


# Write the daily bars (.npz) with their meta.
def save_ohlcv(path: Path, bars: DailyOHLCV) -> Path:
    """Write `bars` to `path` and return the path."""
    shape = (len(bars.dates), len(bars.tickers))
    for name in ("open", "high", "low", "close", "volume"):
        if getattr(bars, name).shape != shape:
            raise ValueError(f"{name} is {getattr(bars, name).shape}; expected {shape}")
    meta = {**bars.meta, "plan": PLAN, "format": FORMAT_VERSION}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        np.savez(
            handle,
            tickers=np.asarray(bars.tickers, dtype=str),
            dates=np.asarray(bars.dates, dtype="datetime64[D]"),
            **{
                name: np.asarray(getattr(bars, name), dtype=np.float32)
                for name in ("open", "high", "low", "close", "volume")
            },
            meta=np.asarray(json.dumps(meta, sort_keys=True, default=str)),
        )
    return path


# Read daily bars written by `save_ohlcv`.
def load_ohlcv(path: Path) -> DailyOHLCV:
    """Return the DailyOHLCV stored at `path`."""
    with np.load(Path(path), allow_pickle=False) as npz:
        meta = json.loads(str(npz["meta"]))
        if meta.get("format") != FORMAT_VERSION:
            raise ValueError(f"{path}: format {meta.get('format')}, expected {FORMAT_VERSION}")
        return DailyOHLCV(
            tickers=npz["tickers"].astype(str),
            dates=npz["dates"].astype("datetime64[D]"),
            open=npz["open"],
            high=npz["high"],
            low=npz["low"],
            close=npz["close"],
            volume=npz["volume"],
            meta=meta,
        )
