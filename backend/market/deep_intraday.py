"""Deep intraday, stage 1: does a small sequence model on the last five
sessions of fifteen-minute bars carry out-of-sample information about the
next session that the grade does not already have?

This module implements exactly the stage-1 protocol of the pre-registration
`docs/research/deep-intraday-plan-2026-09-27.md`, written before any model
was trained. Nothing here trades, ranks the live book or sizes anything.

The dataset. One row per (name, session t) where the name is a book member
on t (`point_in_time.eligibility`, passed in as the anatomy's mask), the
`K_SESSIONS` sessions ending at t are consecutive complete 26-slot sessions
in the cube, and t+1 is the next exchange session and is complete. The
inputs are the K sessions' bars as a `K * 26`-step sequence with three
channels (bar log return, bar volume share of the session, bar range over
close) and three scalars (the session's gap, the name's trailing 20-session
close-to-close return and its trailing 20-session realized volatility).
Everything in X is known at the close of t; the causality test tampers the
future and asserts X unchanged. The targets are the next session's
open-to-close log return (rank-normalized within the date's eligible names
for the ranking question) and the log of the next session's realized
variance (the volatility question, kept apart so the ranking result cannot
be credited with it).

The models. Ridge on the flattened inputs (numpy closed form with an L2
term on standardized features), a temporal CNN (`deep_intraday_cnn`), a
PatchTST encoder (`deep_intraday_patchtst`) and a frozen pretrained
Chronos-Bolt encoder whose mean-pooled embedding feeds the same ridge
(`deep_intraday_pretrained`). The torch and chronos modules are imported
only when asked for, so this module runs where they are absent. Every
model walks forward the same way: the first fit after `MIN_TRAIN`
sessions, a refit every `REFIT` sessions on an expanding window, `PURGE`
sessions between the last training session and the first test session,
predictions only out of sample. One fixed configuration per model, no
search. The torch models train on the device `walk_forward(device=)`
names ("auto" is cuda when available, else cpu); the ridge ignores it.

The metrics. Return head: the daily cross-sectional Spearman IC, its mean
and Newey-West t at `HAC_LAG` over dates; the equal-weight top-quintile
portfolio by forecast (next-session open to close, one-way cost when a name
enters or leaves) against equal weight of every eligible name that date,
paired daily difference with the same HAC t; the same restricted to names
the desk graded A or better. Volatility head: out-of-sample R² against the
trailing 20-session realized volatility, per window. The control: the IC
of the return forecast after regressing it on the volatility forecast
within each date - a return result that vanishes here is a volatility
result and is reported as such.

The kill criteria, as the plan fixes them. On the choosing window, mean IC
t < 2.0 or top-quintile-minus-hurdle t < 2.0 at 10 bp is INSUFFICIENT
EVIDENCE. Volatility R² <= 0 against trailing volatility is a failure of
the model, not a finding. Trials counted: the plan's two models on two
targets, one configuration - four - plus the two model families added on
2026-09-27 (PatchTST; the Chronos-Bolt frozen encoder with a ridge on
top) on the same two targets: eight in all. A payload counts the (model,
target) pairs it actually ran against that total.
"""

from __future__ import annotations

import math
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from backend.market.candidate_stats import hac_t
from backend.market.session_anatomy import (
    CHOOSING_WINDOW,
    WINDOWS,
    MaskByDate,
    _member_rows,
    bar_returns,
    json_ready,
)
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

# Study version, carried in the payload.
STUDY_VERSION = 1
# The plan this implements.
PLAN = "docs/research/deep-intraday-plan-2026-09-27.md"
# Sessions of bars in one input row, and the slots per session.
K_SESSIONS = 5
SLOTS = FULL_SESSION_SLOTS
SEQ_LEN = K_SESSIONS * SLOTS
# The sequence channels and the scalars, in array order.
CHANNELS = ("bar_return", "volume_share", "range")
SCALARS = ("gap", "trailing_return_20", "trailing_vol_20")
# Sessions in the trailing return and volatility scalars (and the
# volatility head's baseline).
TRAILING = 20
# Walk-forward schedule: refit cadence, sessions before the first fit,
# sessions purged between the last training session and the first test one.
REFIT = 63
MIN_TRAIN = 500
PURGE = 5
# The portfolio test: the top share of names by forecast, the one-way
# cost in basis points charged when a name enters or leaves.
TOP_QUANTILE = 0.2
COST_BPS = 10.0
# Newey-West lag for every t on a daily series.
HAC_LAG = 20
# The kill floors on the choosing window (the plan: 2.0 for both).
IC_T_FLOOR = 2.0
PORTFOLIO_T_FLOOR = 2.0
# The plan's "what would make me wrong about the ceiling".
CEILING_IC = 0.05
CEILING_T = 4.0
# Trials counted by the plan as written: two models, two targets, one
# configuration - four; and the total once the two families added on
# 2026-09-27 (patchtst, chronos) are counted on both targets - eight. A
# payload's `trials` is the number of (model, target) pairs it ran,
# against `trials_total`.
PLAN_TRIALS = 4
TRIALS = 8
MODELS = ("ridge", "cnn", "patchtst", "chronos")
# The models that train with torch and take the device option.
TORCH_MODELS = ("cnn", "patchtst")
TARGETS = ("rank", "vol")
# Device names `walk_forward` accepts; "auto" resolves to cuda or cpu.
DEVICES = ("auto", "cpu", "cuda")
# A date needs this many eligible names for a cross-sectional statistic
# (a Spearman on two names is always +-1).
MIN_NAMES = 3
# Ridge: the L2 weight on standardized features, one fixed value.
RIDGE_ALPHA = 10.0
# Rows per chunk when accumulating the ridge's Gram matrix.
RIDGE_CHUNK = 50_000
# The CNN configuration the plan fixes; `deep_intraday_cnn` reads it.
CNN_CONFIG: dict[str, Any] = {
    "lr": 1e-3,
    "epochs": 20,
    "batch": 512,
    "dropout": 0.1,
    "weight_decay": 1e-4,
    "channels": 32,
    "kernel": 5,
    "dilations": (1, 2, 4),
    "hidden": 32,
    "seed": 0,
}
# The PatchTST configuration, fixed on 2026-09-27 before it was run; the
# training constants are the CNN's. `deep_intraday_patchtst` reads it.
PATCHTST_CONFIG: dict[str, Any] = {
    "lr": 1e-3,
    "epochs": 20,
    "batch": 512,
    "dropout": 0.1,
    "weight_decay": 1e-4,
    "patch": 13,
    "d_model": 64,
    "heads": 4,
    "layers": 2,
    "ff": 128,
    "hidden": 32,
    "seed": 0,
}
# The pretrained encoder: which Hugging Face checkpoint, the rows per
# embedding batch, and the sequence channel it reads (the bar return).
CHRONOS_CONFIG: dict[str, Any] = {
    "model_id": "amazon/chronos-bolt-small",
    "batch_size": 256,
    "channel": "bar_return",
}
# Basis points per unit log return.
BP = 1e4
# Verdict strings.
INSUFFICIENT = "INSUFFICIENT EVIDENCE"
VOLATILITY_RESULT = (
    "VOLATILITY RESULT: the return head passes the kill criteria only before"
    " the volatility control"
)
PASSED = "PASSED stage 1 kill criteria"


@dataclass(frozen=True)
class Dataset:
    """One row per (name, session t); rows sorted by session, then ticker."""

    dates: np.ndarray  # (M,) datetime64[D], the session t
    tickers: np.ndarray  # (M,) str
    x_seq: np.ndarray  # (M, SEQ_LEN, len(CHANNELS)) float32, oldest step first
    x_scalar: np.ndarray  # (M, len(SCALARS))
    y_return: np.ndarray  # (M,) next session's open-to-close log return
    y_rank: np.ndarray  # (M,) its rank in [0, 1] within the date's rows
    y_vol: np.ndarray  # (M,) log realized variance of the next session
    trailing_vol: np.ndarray  # (M,) log trailing mean realized variance
    sessions: np.ndarray  # (S,) distinct dates, ascending
    session_index: np.ndarray  # (M,) index into `sessions`

    # Rows in the dataset.
    def __len__(self) -> int:
        return int(len(self.dates))

    # The flattened inputs for the ridge: the sequence step by step, then
    # the scalars: (M, SEQ_LEN * channels + scalars).
    def flat(self) -> np.ndarray:
        """Return the (M, F) feature matrix, float32."""
        m = len(self)
        seq = self.x_seq.reshape(m, SEQ_LEN * len(CHANNELS))
        return np.hstack([seq, self.x_scalar.astype(np.float32)])

    # Row slices per session, in session order: the rows of session s are
    # rows[bounds[s]:bounds[s + 1]].
    def bounds(self) -> np.ndarray:
        """Return the (S + 1,) row boundaries of the sessions."""
        return np.searchsorted(
            self.session_index, np.arange(len(self.sessions) + 1), side="left"
        )


# The exchange session calendar the dataset checks adjacency against:
# the reviewed historical closures plus the current ones.
def default_calendar() -> np.busdaycalendar:
    """Return the reviewed exchange calendar as a numpy business-day calendar."""
    from backend.market.calendar import reviewed_sessions

    return reviewed_sessions()[1]


# Trailing sum over the last `n` rows including the current one; NaN
# until the window is full.
def _trailing_sum(values: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) >= n:
        cumulative = np.concatenate([[0.0], np.cumsum(values)])
        out[n - 1 :] = cumulative[n:] - cumulative[:-n]
    return out


# Everything one cube contributes: the rows on which the name is a member,
# the K-session window is consecutive and complete, the trailing scalars
# are full and t+1 is the next exchange session in the cube. Returns None
# when the cube is too short to hold a row.
def _cube_rows(
    cube: SessionCube, member: np.ndarray, calendar: np.busdaycalendar
) -> dict[str, np.ndarray] | None:
    n = len(cube)
    if n < max(K_SESSIONS, TRAILING) + 1:
        return None
    returns = bar_returns(cube)
    total_volume = cube.volume.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        share = cube.volume / total_volume[:, None]
        span = (cube.high - cube.low) / cube.close
        close_to_close = np.log(cube.close[:, -1] / cube.prior_close)
        gap = np.log(cube.open[:, 0] / cube.prior_close)
        session_return = np.log(cube.close[:, -1] / cube.open[:, 0])
    channels = np.stack([returns, share, span], axis=-1)  # (n, 26, 3)
    realized = (returns**2).sum(axis=1)  # (n,)
    trailing_return = _trailing_sum(close_to_close, TRAILING)
    with np.errstate(invalid="ignore", divide="ignore"):
        trailing_vol = np.log(_trailing_sum(realized, TRAILING) / TRAILING)
        log_realized = np.log(realized)
    # next_ok[i]: row i + 1 is the exchange session after row i.
    days = cube.dates.astype("datetime64[D]")
    next_ok = np.zeros(n, dtype=bool)
    next_ok[:-1] = np.busday_count(days[:-1], days[1:], busdaycal=calendar) == 1
    # window_ok[i]: rows i - K + 1 .. i are consecutive sessions.
    window_ok = np.ones(n, dtype=bool)
    for j in range(1, K_SESSIONS):
        window_ok[j:] &= next_ok[:-j]
    window_ok[: K_SESSIONS - 1] = False
    keep = np.asarray(member, dtype=bool) & next_ok & window_ok
    keep[: TRAILING - 1] = False
    idx = np.nonzero(keep)[0]
    if len(idx) == 0:
        return None
    window = idx[:, None] + np.arange(-K_SESSIONS + 1, 1)[None, :]  # (M, K)
    x_seq = channels[window].reshape(len(idx), SEQ_LEN, len(CHANNELS))
    x_scalar = np.column_stack([gap[idx], trailing_return[idx], trailing_vol[idx]])
    rows = {
        "dates": days[idx],
        "x_seq": x_seq.astype(np.float32),
        "x_scalar": x_scalar,
        "y_return": session_return[idx + 1],
        "y_vol": log_realized[idx + 1],
        "trailing_vol": trailing_vol[idx],
    }
    finite = (
        np.isfinite(rows["x_seq"]).all(axis=(1, 2))
        & np.isfinite(x_scalar).all(axis=1)
        & np.isfinite(rows["y_return"])
        & np.isfinite(rows["y_vol"])
        & np.isfinite(rows["trailing_vol"])
    )
    if not finite.any():
        return None
    return {k: v[finite] for k, v in rows.items()}


# Average ranks (1..n) of `values`, ties averaged.
def _ranks(values: np.ndarray) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    order = np.argsort(v, kind="stable")
    ranks = np.empty(len(v), dtype=float)
    ranks[order] = np.arange(1, len(v) + 1, dtype=float)
    # Average within ties.
    sorted_values = v[order]
    boundaries = np.concatenate(
        [[True], sorted_values[1:] != sorted_values[:-1], [True]]
    )
    starts = np.nonzero(boundaries)[0]
    for lo, hi in zip(starts[:-1], starts[1:], strict=True):
        if hi - lo > 1:
            ranks[order[lo:hi]] = (lo + 1 + hi) / 2.0
    return ranks


# The rank of each value in [0, 1] within its group (0 the lowest, 1 the
# highest, ties averaged; a group of one gets 0.5).
def rank_within(values: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Return the (M,) within-group rank of `values`, scaled to [0, 1]."""
    values = np.asarray(values, dtype=float)
    groups = np.asarray(groups)
    out = np.full(len(values), np.nan)
    order = np.argsort(groups, kind="stable")
    sorted_groups = groups[order]
    edges = np.concatenate(
        [[0], np.nonzero(sorted_groups[1:] != sorted_groups[:-1])[0] + 1, [len(order)]]
    )
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        rows = order[lo:hi]
        if len(rows) == 1:
            out[rows] = 0.5
            continue
        out[rows] = (_ranks(values[rows]) - 1.0) / (len(rows) - 1.0)
    return out


# Build the dataset from the cubes and the membership mask; see the module
# docstring for the row rule. `calendar` decides which session follows
# which; the default is the reviewed exchange calendar.
def dataset(
    cubes: Mapping[str, SessionCube],
    mask_by_date: MaskByDate,
    calendar: np.busdaycalendar | None = None,
) -> Dataset:
    """Return the Dataset of every member (name, session t) row."""
    if calendar is None:
        calendar = default_calendar()
    parts: list[dict[str, np.ndarray]] = []
    for ticker in sorted(cubes):
        cube = cubes[ticker]
        if len(cube) == 0:
            continue
        member = _member_rows(mask_by_date, ticker, cube.dates)
        rows = _cube_rows(cube, member, calendar)
        if rows is None:
            continue
        rows["tickers"] = np.full(len(rows["dates"]), ticker, dtype=object)
        parts.append(rows)
    if not parts:
        return _empty_dataset()
    pooled = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    order = np.lexsort((pooled["tickers"].astype(str), pooled["dates"]))
    pooled = {k: v[order] for k, v in pooled.items()}
    sessions, session_index = np.unique(pooled["dates"], return_inverse=True)
    y_rank = rank_within(pooled["y_return"], session_index)
    return Dataset(
        dates=pooled["dates"],
        tickers=pooled["tickers"].astype(str),
        x_seq=pooled["x_seq"],
        x_scalar=pooled["x_scalar"],
        y_return=pooled["y_return"],
        y_rank=y_rank,
        y_vol=pooled["y_vol"],
        trailing_vol=pooled["trailing_vol"],
        sessions=sessions,
        session_index=session_index.astype(int),
    )


# A dataset with no rows.
def _empty_dataset() -> Dataset:
    return Dataset(
        dates=np.zeros(0, dtype="datetime64[D]"),
        tickers=np.zeros(0, dtype=str),
        x_seq=np.zeros((0, SEQ_LEN, len(CHANNELS)), dtype=np.float32),
        x_scalar=np.zeros((0, len(SCALARS))),
        y_return=np.zeros(0),
        y_rank=np.zeros(0),
        y_vol=np.zeros(0),
        trailing_vol=np.zeros(0),
        sessions=np.zeros(0, dtype="datetime64[D]"),
        session_index=np.zeros(0, dtype=int),
    )


# The (M,) mask of rows whose session t lies in [start, end).
def window_rows(ds: Dataset, start: date | None, end: date | None) -> np.ndarray:
    """Return the Boolean row mask of sessions inside the window."""
    out = np.ones(len(ds), dtype=bool)
    if start is not None:
        out &= ds.dates >= np.datetime64(start, "D")
    if end is not None:
        out &= ds.dates < np.datetime64(end, "D")
    return out


@dataclass(frozen=True)
class Ridge:
    """A fitted ridge: standardization from the training rows, then a line."""

    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float


# Closed-form ridge on standardized features: (Xs'Xs + alpha I) b = Xs'(y -
# mean y), the intercept unpenalized, the Gram matrix accumulated in
# chunks so a float32 feature matrix is never copied whole to float64.
def ridge_fit(x: np.ndarray, y: np.ndarray, alpha: float = RIDGE_ALPHA) -> Ridge:
    """Return the ridge fitted on rows `x` (n, p) to `y` (n,)."""
    x = np.asarray(x)
    y = np.asarray(y, dtype=float)
    if x.ndim != 2 or len(x) != len(y) or len(y) == 0:
        raise ValueError("ridge_fit needs x (n, p) and y (n,) with n > 0")
    mean = x.mean(axis=0, dtype=np.float64)
    scale = x.std(axis=0, dtype=np.float64)
    scale[~(scale > 0)] = 1.0
    y_mean = float(y.mean())
    p = x.shape[1]
    gram = np.zeros((p, p))
    moment = np.zeros(p)
    for lo in range(0, len(y), RIDGE_CHUNK):
        block = (x[lo : lo + RIDGE_CHUNK].astype(np.float64) - mean) / scale
        gram += block.T @ block
        moment += block.T @ (y[lo : lo + RIDGE_CHUNK] - y_mean)
    coef = np.linalg.solve(gram + alpha * np.eye(p), moment)
    return Ridge(mean=mean, scale=scale, coef=coef, intercept=y_mean)


# Predictions of a fitted ridge on rows `x`.
def ridge_predict(model: Ridge, x: np.ndarray) -> np.ndarray:
    """Return the (n,) predictions."""
    x = np.asarray(x)
    out = np.empty(len(x))
    for lo in range(0, len(x), RIDGE_CHUNK):
        block = (x[lo : lo + RIDGE_CHUNK].astype(np.float64) - model.mean) / model.scale
        out[lo : lo + RIDGE_CHUNK] = block @ model.coef + model.intercept
    return out


# The device a name resolves to: "auto" is cuda when it is available and
# cpu otherwise; "cpu" is itself; "cuda" is itself only when available.
# Pure, so it is testable where torch is absent - the callers pass
# `torch.cuda.is_available()`.
def resolve_device(name: str, cuda_available: bool) -> str:
    """Return "cpu" or "cuda" for the device name."""
    name = (name or "auto").strip().lower()
    if name not in DEVICES:
        raise ValueError(f"unknown device {name!r}; expected one of {DEVICES}")
    if name == "auto":
        return "cuda" if cuda_available else "cpu"
    if name == "cuda" and not cuda_available:
        raise ValueError("device 'cuda' requested but torch reports no CUDA device")
    return name


# Whether torch can see a CUDA device here; False where torch is absent.
def cuda_available() -> bool:
    """Return True when torch is importable and reports a CUDA device."""
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


# Devices already announced in this process.
_ANNOUNCED: set[str] = set()


# Say which device the models run on, once per process per device (the
# CLI and every torch model call this; only the first one prints). The
# default sink is stderr so a `--json` run's stdout stays JSON.
def announce_device(device: str, say: Callable[[str], None] | None = None) -> bool:
    """Print the device once; return True when this call printed it."""
    if device in _ANNOUNCED:
        return False
    _ANNOUNCED.add(device)
    line = f"device: {device}"
    if say is None:
        print(line, file=sys.stderr)
    else:
        say(line)
    return True


@dataclass(frozen=True)
class Forecast:
    """Out-of-sample predictions of one model for one target."""

    model: str
    target: str
    values: np.ndarray  # (M,) NaN before the first fit
    fits: list[dict[str, Any]] = field(default_factory=list)
    parameters: int | None = None


# The target array a name refers to.
def _target(ds: Dataset, target: str) -> np.ndarray:
    if target == "rank":
        return ds.y_rank
    if target == "vol":
        return ds.y_vol
    raise ValueError(f"unknown target {target!r}; expected one of {TARGETS}")


# The per-block fitter of one model for one target, and the parameter
# count known before any fit (the frozen chronos encoder's; None
# otherwise). The ridge fits `flat` rows; chronos fits the same ridge on
# [embedding, scalars], the embedding computed once for the whole dataset
# here (a frozen encoder fits nothing, so a row's embedding depends on
# that row alone and cannot carry anything across the purge); the torch
# families train on `device`.
def _fitter(
    ds: Dataset,
    model: str,
    target: str,
    y: np.ndarray,
    device: str,
    cache_dir: Path | None,
    log: Callable[[str], None] | None,
) -> tuple[
    Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, int | None]], int | None
]:
    parameters: int | None = None
    if model in ("ridge", "chronos"):
        if model == "ridge":
            flat = ds.flat()
        else:
            from backend.market import deep_intraday_pretrained as pretrained

            embedding, info = pretrained.dataset_embedding(
                ds,
                device=device,
                cache_dir=cache_dir,
                model_id=str(CHRONOS_CONFIG["model_id"]),
                batch_size=int(CHRONOS_CONFIG["batch_size"]),
                log=log,
            )
            flat = pretrained.features(embedding, ds.x_scalar)
            parameters = info.get("parameters")

        # Fit the ridge on the training rows and predict the test rows.
        def fit_predict(
            train: np.ndarray, test: np.ndarray
        ) -> tuple[np.ndarray, int | None]:
            fitted = ridge_fit(flat[train], y[train])
            return ridge_predict(fitted, flat[test]), parameters

        return fit_predict, parameters
    if model == "cnn":
        from backend.market import deep_intraday_cnn as family

        config = CNN_CONFIG
    else:
        from backend.market import deep_intraday_patchtst as family

        config = PATCHTST_CONFIG

    # Train the network on the training rows and predict the test rows.
    def fit_predict(
        train: np.ndarray, test: np.ndarray
    ) -> tuple[np.ndarray, int | None]:
        return family.fit_predict(
            ds.x_seq[train],
            ds.x_scalar[train],
            y[train],
            ds.x_seq[test],
            ds.x_scalar[test],
            target,
            config,
            device=device,
        )

    return fit_predict, parameters


# Walk-forward predictions: the first fit once `MIN_TRAIN` sessions exist,
# a refit every `REFIT` sessions on every row whose session is more than
# `PURGE` sessions before the test block's first session, predictions on
# the block only. `log` receives one line per fit with its timing.
# `device` is where the torch models train (the ridge ignores it);
# `cache_dir` is where the chronos embedding is cached between runs (None:
# recomputed every call).
def walk_forward(
    ds: Dataset,
    model: str = "ridge",
    target: str = "rank",
    log: Callable[[str], None] | None = None,
    device: str = "auto",
    cache_dir: Path | None = None,
) -> Forecast:
    """Return the Forecast of `model` for `target` over the dataset."""
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; expected one of {MODELS}")
    y = _target(ds, target)
    s = ds.session_index
    values = np.full(len(ds), np.nan)
    fits: list[dict[str, Any]] = []
    fit_predict, parameters = _fitter(ds, model, target, y, device, cache_dir, log)
    for start in range(MIN_TRAIN, len(ds.sessions), REFIT):
        end = min(start + REFIT, len(ds.sessions))
        train = (s < start - PURGE) & np.isfinite(y)
        test = (s >= start) & (s < end)
        if train.sum() < MIN_NAMES or not test.any():
            continue
        began = time.perf_counter()
        values[test], parameters = fit_predict(train, test)
        seconds = time.perf_counter() - began
        record = {
            "train_through": str(ds.sessions[start - PURGE - 1]),
            "test_start": str(ds.sessions[start]),
            "test_end": str(ds.sessions[end - 1]),
            "n_train": int(train.sum()),
            "n_test": int(test.sum()),
            "seconds": seconds,
        }
        fits.append(record)
        if log is not None:
            log(
                f"  {model}/{target} fit {len(fits)}: train through"
                f" {record['train_through']} ({record['n_train']:,} rows), test"
                f" {record['test_start']}..{record['test_end']}"
                f" ({record['n_test']:,} rows), {seconds:.1f} s"
            )
    return Forecast(model, target, values, fits, parameters)


@dataclass(frozen=True)
class DailySeries:
    """One number per date and its mean and Newey-West t at HAC_LAG."""

    dates: np.ndarray
    values: np.ndarray

    # Dates contributing.
    @property
    def n(self) -> int:
        return int(len(self.values))

    # The mean over dates, NaN when empty.
    @property
    def mean(self) -> float:
        return float(self.values.mean()) if len(self.values) else math.nan

    # The Newey-West t of the mean at HAC_LAG.
    @property
    def t(self) -> float:
        return hac_t(self.values, HAC_LAG) if len(self.values) >= 2 else math.nan

    # The JSON summary.
    def summary(self) -> dict[str, Any]:
        """Return {mean, t, dates}."""
        return {"mean": self.mean, "t": self.t, "dates": self.n}


# Spearman correlation of two vectors; NaN when either is constant.
def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Return the Spearman rank correlation of `a` and `b`."""
    if len(a) < 2:
        return math.nan
    ra, rb = _ranks(a), _ranks(b)
    ra -= ra.mean()
    rb -= rb.mean()
    denominator = math.sqrt(float(ra @ ra) * float(rb @ rb))
    if denominator <= 0:
        return math.nan
    return float(ra @ rb) / denominator


# Per-session row indices with a finite value of every array given and
# inside `window`, for sessions with at least MIN_NAMES such rows.
def _eligible_by_session(
    ds: Dataset, arrays: list[np.ndarray], window: np.ndarray | None
) -> list[tuple[int, np.ndarray]]:
    ok = np.ones(len(ds), dtype=bool)
    for a in arrays:
        ok &= np.isfinite(a)
    if window is not None:
        ok &= window
    bounds = ds.bounds()
    out = []
    for session in range(len(ds.sessions)):
        rows = np.arange(bounds[session], bounds[session + 1])
        rows = rows[ok[rows]]
        if len(rows) >= MIN_NAMES:
            out.append((session, rows))
    return out


# The daily cross-sectional Spearman IC of a forecast against the next
# session's return, as a daily series (mean and HAC t on it).
def daily_ic(
    ds: Dataset, forecast: Forecast | np.ndarray, window: np.ndarray | None = None
) -> DailySeries:
    """Return the per-date Spearman(forecast, y_return) series."""
    values = forecast.values if isinstance(forecast, Forecast) else np.asarray(forecast)
    dates, ics = [], []
    for session, rows in _eligible_by_session(ds, [values, ds.y_return], window):
        ic = spearman(values[rows], ds.y_return[rows])
        if math.isfinite(ic):
            dates.append(ds.sessions[session])
            ics.append(ic)
    return DailySeries(np.asarray(dates, dtype="datetime64[D]"), np.asarray(ics))


@dataclass(frozen=True)
class Portfolio:
    """The top-quantile portfolio against the equal-weight hurdle, daily."""

    dates: np.ndarray
    portfolio: np.ndarray  # net of cost
    hurdle: np.ndarray  # net of its own (rare) cost
    portfolio_gross: np.ndarray
    hurdle_gross: np.ndarray
    turnover: np.ndarray  # sum |dw| of the portfolio per date
    names: np.ndarray  # eligible names per date

    # The paired daily difference, net.
    def difference(self) -> DailySeries:
        """Return portfolio minus hurdle per date."""
        return DailySeries(self.dates, self.portfolio - self.hurdle)

    # The JSON summary, in basis points per day.
    def summary(self) -> dict[str, Any]:
        """Return the bp/day means, the paired t and the counts."""
        diff = self.difference()
        n = len(self.dates)
        return {
            "mean_bp": diff.mean * BP if n else math.nan,
            "t": diff.t,
            "dates": n,
            "portfolio_bp": float(self.portfolio.mean()) * BP if n else math.nan,
            "hurdle_bp": float(self.hurdle.mean()) * BP if n else math.nan,
            "portfolio_gross_bp": float(self.portfolio_gross.mean()) * BP
            if n
            else math.nan,
            "hurdle_gross_bp": float(self.hurdle_gross.mean()) * BP if n else math.nan,
            "turnover": float(self.turnover.mean()) if n else math.nan,
            "names": float(self.names.mean()) if n else math.nan,
        }


# Sum of absolute weight changes between two weight maps (entries and exits
# both count once, one way).
def _turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    names = set(previous) | set(current)
    return float(sum(abs(current.get(k, 0.0) - previous.get(k, 0.0)) for k in names))


# Equal weight of the top `TOP_QUANTILE` of eligible names by forecast on
# each date, earning the next session's open-to-close, charged `cost_bps`
# one way on every weight change, against equal weight of every eligible
# name that date charged the same way. `keep` restricts the eligible rows
# (the A/A+ variant); the hurdle is restricted with them.
def top_quantile_portfolio(
    ds: Dataset,
    forecast: Forecast | np.ndarray,
    cost_bps: float = COST_BPS,
    window: np.ndarray | None = None,
    keep: np.ndarray | None = None,
) -> Portfolio:
    """Return the daily Portfolio of the top quantile against the hurdle."""
    values = forecast.values if isinstance(forecast, Forecast) else np.asarray(forecast)
    cost = cost_bps / BP
    restrict = window if keep is None else (keep if window is None else window & keep)
    held_top: dict[str, float] = {}
    held_all: dict[str, float] = {}
    series: dict[str, list[float]] = {
        k: []
        for k in ("top_net", "all_net", "top_gross", "all_gross", "turnover", "names")
    }
    dates: list[np.datetime64] = []
    for session, rows in _eligible_by_session(ds, [values, ds.y_return], restrict):
        n = len(rows)
        k = max(1, int(math.ceil(TOP_QUANTILE * n)))
        order = np.lexsort((ds.tickers[rows], -values[rows]))
        chosen = rows[order[:k]]
        top = {ds.tickers[r]: 1.0 / k for r in chosen}
        everyone = {ds.tickers[r]: 1.0 / n for r in rows}
        turnover_top = _turnover(held_top, top)
        turnover_all = _turnover(held_all, everyone)
        gross_top = float(ds.y_return[chosen].mean())
        gross_all = float(ds.y_return[rows].mean())
        dates.append(ds.sessions[session])
        series["top_gross"].append(gross_top)
        series["all_gross"].append(gross_all)
        series["top_net"].append(gross_top - cost * turnover_top)
        series["all_net"].append(gross_all - cost * turnover_all)
        series["turnover"].append(turnover_top)
        series["names"].append(float(n))
        held_top, held_all = top, everyone
    return Portfolio(
        dates=np.asarray(dates, dtype="datetime64[D]"),
        portfolio=np.asarray(series["top_net"]),
        hurdle=np.asarray(series["all_net"]),
        portfolio_gross=np.asarray(series["top_gross"]),
        hurdle_gross=np.asarray(series["all_gross"]),
        turnover=np.asarray(series["turnover"]),
        names=np.asarray(series["names"]),
    )


# Out-of-sample R² of the volatility forecast against the trailing
# realized-volatility baseline: 1 - SSE(model) / SSE(baseline) over the
# rows with a forecast. Zero or below means the model did not beat the
# baseline.
def vol_r2(
    ds: Dataset, forecast: Forecast | np.ndarray, window: np.ndarray | None = None
) -> dict[str, Any]:
    """Return {r2, n, mse_model, mse_baseline}."""
    values = forecast.values if isinstance(forecast, Forecast) else np.asarray(forecast)
    ok = np.isfinite(values) & np.isfinite(ds.y_vol) & np.isfinite(ds.trailing_vol)
    if window is not None:
        ok &= window
    n = int(ok.sum())
    if n < 2:
        return {"r2": math.nan, "n": n, "mse_model": math.nan, "mse_baseline": math.nan}
    model_error = ds.y_vol[ok] - values[ok]
    baseline_error = ds.y_vol[ok] - ds.trailing_vol[ok]
    sse_model = float(model_error @ model_error)
    sse_baseline = float(baseline_error @ baseline_error)
    r2 = 1.0 - sse_model / sse_baseline if sse_baseline > 0 else math.nan
    return {
        "r2": r2,
        "n": n,
        "mse_model": sse_model / n,
        "mse_baseline": sse_baseline / n,
    }


# The plan's control: within each date, regress the return forecast on the
# volatility forecast (with a constant) and take the residual's Spearman IC
# against the next session's return. A return IC that survives here is not
# a volatility result.
def volatility_control(
    ds: Dataset,
    ret_forecast: Forecast | np.ndarray,
    vol_forecast: Forecast | np.ndarray,
    window: np.ndarray | None = None,
) -> DailySeries:
    """Return the per-date residual IC series."""
    ret = (
        ret_forecast.values
        if isinstance(ret_forecast, Forecast)
        else np.asarray(ret_forecast)
    )
    vol = (
        vol_forecast.values
        if isinstance(vol_forecast, Forecast)
        else np.asarray(vol_forecast)
    )
    dates, ics = [], []
    for session, rows in _eligible_by_session(ds, [ret, vol, ds.y_return], window):
        design = np.column_stack([np.ones(len(rows)), vol[rows]])
        coef = np.linalg.lstsq(design, ret[rows], rcond=None)[0]
        residual = ret[rows] - design @ coef
        ic = spearman(residual, ds.y_return[rows])
        if math.isfinite(ic):
            dates.append(ds.sessions[session])
            ics.append(ic)
    return DailySeries(np.asarray(dates, dtype="datetime64[D]"), np.asarray(ics))


# Every metric of one (model, target) forecast on one window. `keep_a` is
# the (M,) mask of rows the desk graded A or better, or None when unknown;
# `vol` is the same model's volatility forecast for the control, or None.
def evaluate(
    ds: Dataset,
    forecast: Forecast,
    window: np.ndarray | None,
    keep_a: np.ndarray | None = None,
    vol: Forecast | None = None,
    cost_bps: float = COST_BPS,
) -> dict[str, Any]:
    """Return the JSON-ready metrics record for one window."""
    scored = np.isfinite(forecast.values)
    if window is not None:
        scored &= window
    record: dict[str, Any] = {
        "model": forecast.model,
        "target": forecast.target,
        "rows": int(scored.sum()),
        "dates": int(len(np.unique(ds.session_index[scored]))),
        "ic": None,
        "portfolio": None,
        "portfolio_a": None,
        "control": None,
        "vol_r2": None,
    }
    if forecast.target == "rank":
        record["ic"] = daily_ic(ds, forecast, window).summary()
        record["portfolio"] = top_quantile_portfolio(
            ds, forecast, cost_bps, window
        ).summary()
        if keep_a is not None:
            record["portfolio_a"] = top_quantile_portfolio(
                ds, forecast, cost_bps, window, keep=keep_a
            ).summary()
        if vol is not None:
            record["control"] = volatility_control(ds, forecast, vol, window).summary()
    else:
        record["vol_r2"] = vol_r2(ds, forecast, window)
    return record


# The study payload: every forecast on every window, the dataset's
# counts, the fits and the verdict. `forecasts` maps (model, target) to
# the walk-forward Forecast; a model's rank forecast is controlled with
# that model's vol forecast when both are present.
def study(
    ds: Dataset,
    forecasts: Mapping[tuple[str, str], Forecast],
    keep_a: np.ndarray | None = None,
    windows: Mapping[str, tuple[date | None, date | None]] = WINDOWS,
    choosing: str = CHOOSING_WINDOW,
    cost_bps: float = COST_BPS,
) -> dict[str, Any]:
    """Return the JSON-serialisable stage-1 payload with its verdict."""
    if choosing not in windows:
        raise ValueError(f"choosing window {choosing!r} is not one of {list(windows)}")
    results = []
    for name, (start, end) in windows.items():
        window = window_rows(ds, start, end)
        for (model, target), forecast in forecasts.items():
            vol = forecasts.get((model, "vol")) if target == "rank" else None
            record = evaluate(ds, forecast, window, keep_a, vol, cost_bps)
            record["window"] = name
            results.append(record)
    rows_per_window = {
        name: int(window_rows(ds, start, end).sum())
        for name, (start, end) in windows.items()
    }
    payload: dict[str, Any] = {
        "study": "deep_intraday",
        "stage": 1,
        "version": STUDY_VERSION,
        "plan": PLAN,
        "choosing_window": choosing,
        "windows": {
            name: {"start": _iso(start), "end": _iso(end)}
            for name, (start, end) in windows.items()
        },
        "constants": {
            "k_sessions": K_SESSIONS,
            "slots": SLOTS,
            "channels": list(CHANNELS),
            "scalars": list(SCALARS),
            "trailing": TRAILING,
            "refit": REFIT,
            "min_train": MIN_TRAIN,
            "purge": PURGE,
            "top_quantile": TOP_QUANTILE,
            "cost_bps": cost_bps,
            "hac_lag": HAC_LAG,
            "ic_t_floor": IC_T_FLOOR,
            "portfolio_t_floor": PORTFOLIO_T_FLOOR,
            "min_names": MIN_NAMES,
            "ridge_alpha": RIDGE_ALPHA,
            "cnn": {
                k: (list(v) if isinstance(v, tuple) else v)
                for k, v in CNN_CONFIG.items()
            },
            "patchtst": dict(PATCHTST_CONFIG),
            "chronos": dict(CHRONOS_CONFIG),
        },
        # The (model, target) pairs this payload ran, against the family
        # total: the plan's four plus the two families added on 2026-09-27.
        "trials": len(forecasts),
        "trials_total": TRIALS,
        "plan_trials": PLAN_TRIALS,
        "models": sorted({m for m, _ in forecasts}, key=MODELS.index),
        "targets": sorted({t for _, t in forecasts}, key=TARGETS.index),
        "dataset": {
            "rows": len(ds),
            "names": int(len(np.unique(ds.tickers))) if len(ds) else 0,
            "sessions": int(len(ds.sessions)),
            "first": str(ds.sessions[0]) if len(ds.sessions) else None,
            "last": str(ds.sessions[-1]) if len(ds.sessions) else None,
            "rows_per_window": rows_per_window,
            "graded_rows": int(keep_a.sum()) if keep_a is not None else None,
        },
        "fits": {f"{m}/{t}": f.fits for (m, t), f in forecasts.items()},
        "parameters": {
            m: f.parameters for (m, t), f in forecasts.items() if f.parameters
        },
        "results": results,
    }
    payload["verdict_detail"] = verdict_detail(payload)
    payload["verdict"] = verdict(payload)
    ready: dict[str, Any] = json_ready(payload)
    return ready


# A finite float or NaN from a JSON-ready leaf.
def _num(value: Any) -> float:
    return (
        float(value)
        if isinstance(value, (int, float)) and math.isfinite(value)
        else math.nan
    )


# The kill criteria, model by model, on the choosing window: what each
# return head did against both floors and the control, and whether each
# volatility head beat its baseline. One line per finding.
def verdict_detail(payload: Mapping[str, Any]) -> list[str]:
    """Return the per-model findings behind the verdict."""
    choosing = payload["choosing_window"]
    rows = [r for r in payload["results"] if r["window"] == choosing]
    lines = []
    for model in MODELS:
        rank = next(
            (r for r in rows if r["model"] == model and r["target"] == "rank"), None
        )
        vol = next(
            (r for r in rows if r["model"] == model and r["target"] == "vol"), None
        )
        if rank is not None:
            ic = rank["ic"] or {}
            portfolio = rank["portfolio"] or {}
            ic_t, ic_mean = _num(ic.get("t")), _num(ic.get("mean"))
            port_t = _num(portfolio.get("t"))
            passes = ic_t >= IC_T_FLOOR and port_t >= PORTFOLIO_T_FLOOR
            lines.append(
                f"{model}/rank on {choosing}: IC mean {ic_mean:.4f} t {ic_t:.2f}"
                f" (floor {IC_T_FLOOR}); top-quintile minus hurdle"
                f" {_num(portfolio.get('mean_bp')):+.1f} bp/d t {port_t:.2f}"
                f" (floor {PORTFOLIO_T_FLOOR}): {'passes' if passes else 'fails'}"
                " the kill criteria"
            )
            control = rank["control"]
            if passes and control is not None:
                control_t = _num(control.get("t"))
                survives = control_t >= IC_T_FLOOR
                lines.append(
                    f"{model}/rank volatility control: residual IC mean"
                    f" {_num(control.get('mean')):.4f} t {control_t:.2f}:"
                    f" {'survives' if survives else 'vanishes - a volatility result'}"
                )
            elif passes:
                lines.append(
                    f"{model}/rank volatility control: no volatility forecast"
                    " to control with"
                )
            if ic_mean > CEILING_IC and ic_t > CEILING_T:
                lines.append(
                    f"{model}/rank exceeds the plan's ceiling"
                    f" (IC > {CEILING_IC}, t > {CEILING_T})"
                    " - check for leakage before believing it"
                )
        if vol is not None and vol["vol_r2"] is not None:
            r2 = _num(vol["vol_r2"].get("r2"))
            lines.append(
                f"{model}/vol on {choosing}: R2 {r2:.4f} against trailing volatility:"
                + (
                    " beats the baseline"
                    if r2 > 0
                    else " fails (a failure of the model, not a finding)"
                )
            )
    lines.append(
        f"trials counted: {payload.get('trials', TRIALS)} run of"
        f" {payload.get('trials_total', TRIALS)} pre-registered"
        f" (the plan's {payload.get('plan_trials', PLAN_TRIALS)} plus the two"
        " families added on 2026-09-27, patchtst and chronos, on both targets)"
    )
    return lines


# The verdict the plan fixes: INSUFFICIENT EVIDENCE unless a return head
# clears both floors on the choosing window; a head that clears them but
# not the volatility control is a volatility result; otherwise PASSED,
# naming the models, and never a trading verdict.
def verdict(payload: Mapping[str, Any]) -> str:
    """Return the verdict string for the payload."""
    choosing = payload["choosing_window"]
    rows = [
        r
        for r in payload["results"]
        if r["window"] == choosing and r["target"] == "rank"
    ]
    passed, volatility = [], []
    for r in rows:
        ic_t = _num((r["ic"] or {}).get("t"))
        port_t = _num((r["portfolio"] or {}).get("t"))
        if not (ic_t >= IC_T_FLOOR and port_t >= PORTFOLIO_T_FLOOR):
            continue
        control = r["control"]
        if control is not None and not (_num(control.get("t")) >= IC_T_FLOOR):
            volatility.append(r["model"])
        else:
            passed.append(r["model"])
    if passed:
        return f"{PASSED} ({', '.join(passed)}); not a trading verdict"
    if volatility:
        return f"{VOLATILITY_RESULT} ({', '.join(volatility)})"
    return INSUFFICIENT


# A date as ISO text, or None.
def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
