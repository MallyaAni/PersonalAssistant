"""Deep sequence models, stage 2: the same models on inputs worth learning
from, judged on targets the live policy would act on.

This module implements the pre-registration
`docs/research/deep-stage2-plan-2026-09-27.md`, written before any model of
this stage was trained. Stage 1 (`deep_intraday`) is reused by import
wherever it exists - the ridge, the Spearman and rank helpers, the daily
IC and the cost-charged top-quintile portfolio, the walk-forward
constants, the device resolution - and nothing here trades, ranks the live
book or sizes anything.

The dataset (`Dataset2`). One row per (name, session t) where the name is
a book member on t (`point_in_time.eligibility` through the anatomy's
mask), the `K_SESSIONS = 60` most recent complete sessions in the cube end
at t and span at most `K_SESSIONS + WINDOW_SLACK` exchange sessions (early
closes are excluded from the cubes, so stage 1's strictly consecutive
window would rarely exist at sixty), and the desk graded the name on t.
Version 2 retains input-eligible rows regardless of future label availability;
an absent or nonfinite next-session outcome leaves a NaN label, not a missing
decision row. Earlier exports/results are not rewritten. The sequence has six
channels: the name's bar log return, volume share and range over close
(stage 1's), and the same-session bar log returns of the benchmarks the
store holds among `BENCHMARKS` (a benchmark session the store lacks is a
zero row; `benchmark_fill` counts them). The scalars are stage 1's gap
and trailing 20-session return and volatility, the day's breadth (share
of members whose adjusted close rose), the desk's regime on t, the grade
as a one-hot, every analyst stance and the band z; `scalar_names` lists
them in column order because the stance columns follow the report.
Everything in X is known at the close of t; a row with a non-finite input
(a band z before its window, a regime the desk could not judge) is dropped.

The targets: `rank` (stage 1's, the anchor), `downgrade20` (an A/A+ name
graded below A on any of the next `HORIZON` sessions; NaN for names below
A on t), `drawdown20` (min over the next `HORIZON` sessions of adjusted
close over today's, minus one; positive when the name never dips), `vol20`
(log realized variance of the next `HORIZON` daily log returns; baseline
`trailing_vol20`, the same over the trailing window). The 20-session
targets and the decision test's `fwd20` come from the desk's daily panel;
rows whose horizon runs past it are NaN there and are neither trained nor
scored on those heads.

The walk-forward is stage 1's schedule (first fit after `MIN_TRAIN`,
refit every `REFIT`, expanding window) with `PURGE = 20`, because the
20-session targets of the last training rows would otherwise overlap the
test block; the same purge applies to every head so a network's heads
train on the same rows. The torch families live in `deep_stage2_nn` and
are imported only when asked for.

The decision test (`decision_test`) is what would change the live policy:
each day the graded book (equal weight of every A/A+ member with a
forward return) against the same book with the A/A+ names whose forecast
is in the worst `DROP_QUANTILE` that day dropped, both earning the next
`HORIZON` sessions' return; the paired difference per session (the
20-session difference over 20) net of `COST_BPS` one way on the extra
turnover the drops cause, with a Newey-West t at `HAC_LAG`. The kill
criteria: INSUFFICIENT EVIDENCE unless the net difference is at least
`DECISION_BP_FLOOR` bp per session with t at least `DECISION_T_FLOOR` on
the choosing window and not negative on the later window. AUC, IC and R²
alone never pass. Trials: `TRIALS = 16`, four models on four targets.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from backend.market import deep_intraday as stage1
from backend.market.deep_intraday import (
    BP,
    CHANNELS,
    COST_BPS,
    HAC_LAG,
    INSUFFICIENT,
    MIN_NAMES,
    MIN_TRAIN,
    REFIT,
    RIDGE_ALPHA,
    SLOTS,
    TRAILING,
    DailySeries,
    Forecast,
    _eligible_by_session,
    _trailing_sum,
    _turnover,
    rank_within,
    ridge_fit,
    ridge_predict,
    spearman,
    window_rows,
)
from backend.market.session_anatomy import (
    CHOOSING_WINDOW,
    WINDOWS,
    MaskByDate,
    _member_rows,
    bar_returns,
    json_ready,
)
from backend.market.sip_cube import SessionCube

# Study version, carried in the payload.
STUDY_VERSION = 2
# The plan this implements.
PLAN = "docs/research/deep-stage2-plan-2026-09-27.md"
# Sessions of bars in one input row, and the exchange sessions the window
# may span beyond that (early closes the cubes exclude).
K_SESSIONS = 60
WINDOW_SLACK = 6
# Sessions in the forward targets, and the walk-forward purge (equal, so
# no training row's target overlaps the test block).
HORIZON = 20
PURGE = 20
# The market channels, in preference order; the export keeps the ones the
# store holds.
BENCHMARKS = ("SPY", "QQQ", "SMH")
# The name's own channels (stage 1's), then one bar-return channel per
# benchmark found.
NAME_CHANNELS = CHANNELS
# The scalars every row carries, in column order; the analyst stances
# (`stance_<analyst>`) follow, in the report's sorted analyst order.
FIXED_SCALARS = (
    "gap",
    "trailing_return_20",
    "trailing_vol_20",
    "breadth",
    "regime_exposure",
    "regime_confidence",
    "regime_participation_pct",
    "regime_ai_drawdown",
    "regime_leader_ai",
    "regime_tightening",
    "grade_a_plus",
    "grade_a",
    "grade_b",
    "grade_c",
    "band_z",
)
# Grade ordinals as the desk writes them (grading.ORDINAL: A+ 3, A 2, B 1,
# C 0); the A/A+ floor; the value of a row the desk did not grade.
GRADE_ORDINALS = (3, 2, 1, 0)
A_MIN_GRADE = 2
NO_GRADE = -1
# The models and the targets, and which targets have a decision test.
MODELS = ("ridge", "cnn", "patchtst", "patchtst-pretrained")
TORCH_MODELS = ("cnn", "patchtst", "patchtst-pretrained")
TARGETS = ("rank", "downgrade20", "drawdown20", "vol20")
DECISION_TARGETS = ("downgrade20", "drawdown20")
# The loss each head trains with in the torch families.
TARGET_KIND = {"rank": "mse", "downgrade20": "bce", "drawdown20": "mse", "vol20": "mse"}
# Trials counted: four models on four targets, the pretraining variant
# one of the four.
TRIALS = len(MODELS) * len(TARGETS)
# The decision test: the worst share of A/A+ names by forecast dropped
# each day, and the kill floors on the choosing window.
DROP_QUANTILE = 0.1
DECISION_BP_FLOOR = 2.0
DECISION_T_FLOOR = 2.0
# Rows widened to float64 at a time in the ridge (9.4k features a row).
RIDGE_CHUNK = 4096
# The masked-patch pretraining: epochs and the share of patches masked.
PRETRAIN_CONFIG: dict[str, Any] = {"epochs": 5, "mask_ratio": 0.4, "seed": 0}
# The pretrained arm's ridge, on [embedding, scalars]: stage 1's alpha.
PROBE_ALPHA = RIDGE_ALPHA
# Verdict strings.
PASSED = "PASSED stage 2 kill criteria"
# A device name for the payload when no torch model ran.
NO_DEVICE = "-"


@dataclass(frozen=True)
class Dataset2:
    """One row per (name, session t); rows sorted by session, then ticker."""

    dates: np.ndarray  # (M,) datetime64[D], the session t
    tickers: np.ndarray  # (M,) str
    x_seq: np.ndarray  # (M, k * SLOTS, 3 + benchmarks) float32, oldest step first
    x_scalar: np.ndarray  # (M, S) float64
    scalar_names: tuple[str, ...]  # (S,) column names of x_scalar
    y_return: np.ndarray  # (M,) next session's open-to-close log return
    y_rank: np.ndarray  # (M,) its rank in [0, 1] within the date's rows
    y_downgrade20: np.ndarray  # (M,) 0/1 for A/A+ rows, NaN otherwise
    y_drawdown20: np.ndarray  # (M,) min close ratio over the horizon minus one
    y_vol20: np.ndarray  # (M,) log realized variance over the horizon
    trailing_vol20: np.ndarray  # (M,) the same over the trailing window
    fwd20: np.ndarray  # (M,) log adjusted-close return over the horizon
    grade: np.ndarray  # (M,) grade ordinal on t
    sessions: np.ndarray  # (S,) distinct dates, ascending
    session_index: np.ndarray  # (M,) index into `sessions`
    k: int  # sessions of bars per row
    benchmarks: tuple[str, ...]  # the market channels, in channel order
    benchmark_fill: int  # benchmark (session, bar-row) pairs zero-filled
    row_selection: str = stage1.LEGACY_ROW_SELECTION

    # Rows in the dataset.
    def __len__(self) -> int:
        return int(len(self.dates))

    # Steps in the sequence.
    @property
    def seq_len(self) -> int:
        return int(self.x_seq.shape[1])

    # The channel names, in array order.
    @property
    def channels(self) -> tuple[str, ...]:
        return (*NAME_CHANNELS, *(f"{b}_bar_return" for b in self.benchmarks))

    # The rows the desk graded A or better on t.
    @property
    def keep_a(self) -> np.ndarray:
        return self.grade >= A_MIN_GRADE

    # The flattened inputs of `rows` (every row when None) for the ridge:
    # the sequence step by step, then the scalars, float32. Built per
    # fold rather than for the whole dataset because at sixty sessions
    # the full matrix is another three gigabytes.
    def flat(self, rows: np.ndarray | None = None) -> np.ndarray:
        """Return the (n, seq_len * channels + S) feature matrix."""
        seq = self.x_seq if rows is None else self.x_seq[rows]
        scalar = self.x_scalar if rows is None else self.x_scalar[rows]
        n = len(seq)
        return np.hstack([seq.reshape(n, -1), scalar.astype(np.float32)])

    # Row slices per session, in session order: the rows of session s are
    # rows[bounds[s]:bounds[s + 1]].
    def bounds(self) -> np.ndarray:
        """Return the (S + 1,) row boundaries of the sessions."""
        return np.searchsorted(
            self.session_index, np.arange(len(self.sessions) + 1), side="left"
        )


# The arrays a dataset is made of, for the export file (the scalars
# after them are written as metadata).
DATASET_ARRAYS = (
    "dates",
    "tickers",
    "x_seq",
    "x_scalar",
    "y_return",
    "y_rank",
    "y_downgrade20",
    "y_drawdown20",
    "y_vol20",
    "trailing_vol20",
    "fwd20",
    "grade",
    "sessions",
    "session_index",
)


# Write a dataset to one compressed npz so the desktop GPU can train on
# exactly the rows the Spark assembled. The sequence is written as float16
# (half the bytes; bar returns below 6e-5 lose relative precision, which
# the standardization the models apply does not care about) and widened
# back to float32 by `load_dataset`.
def save_dataset(path: Path, ds: Dataset2) -> Path:
    """Write `ds` to `path` (npz) and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {name: getattr(ds, name) for name in DATASET_ARRAYS}
    arrays["dates"] = arrays["dates"].astype("datetime64[D]").astype("int64")
    arrays["sessions"] = arrays["sessions"].astype("datetime64[D]").astype("int64")
    arrays["tickers"] = arrays["tickers"].astype(str)
    arrays["x_seq"] = arrays["x_seq"].astype(np.float16)
    arrays["scalar_names"] = np.asarray(ds.scalar_names, dtype=str)
    arrays["benchmarks"] = np.asarray(ds.benchmarks, dtype=str)
    arrays["row_selection"] = np.asarray(ds.row_selection, dtype=str)
    arrays["meta"] = np.asarray(
        [ds.k, ds.benchmark_fill, STUDY_VERSION], dtype=np.int64
    )
    np.savez_compressed(path, **arrays)
    return path


# Read a dataset written by `save_dataset`.
def load_dataset(path: Path) -> Dataset2:
    """Return the Dataset2 from an export file."""
    with np.load(Path(path), allow_pickle=False) as data:
        fields: dict[str, Any] = {name: data[name] for name in DATASET_ARRAYS}
        fields["dates"] = fields["dates"].astype("datetime64[D]")
        fields["sessions"] = fields["sessions"].astype("datetime64[D]")
        fields["tickers"] = fields["tickers"].astype(str)
        fields["x_seq"] = fields["x_seq"].astype(np.float32)
        fields["scalar_names"] = tuple(str(s) for s in data["scalar_names"])
        fields["benchmarks"] = tuple(str(b) for b in data["benchmarks"])
        fields["row_selection"] = stage1.load_row_selection(data)
        meta = data["meta"]
    return Dataset2(**fields, k=int(meta[0]), benchmark_fill=int(meta[1]))


# The exchange session calendar (stage 1's).
def default_calendar() -> np.busdaycalendar:
    """Return the reviewed exchange calendar as a numpy business-day calendar."""
    return stage1.default_calendar()


# Build member input windows before joining the desk; future labels never select rows.
def cube_rows(
    cube: SessionCube, member: np.ndarray, calendar: np.busdaycalendar, k: int
) -> dict[str, np.ndarray] | None:
    """Return the name's rows keyed by array name, or None."""
    n = len(cube)
    if n < max(k, TRAILING):
        return None
    returns = bar_returns(cube)
    total_volume = cube.volume.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        share = cube.volume / total_volume[:, None]
        span = (cube.high - cube.low) / cube.close
        close_to_close = np.log(cube.close[:, -1] / cube.prior_close)
        gap = np.log(cube.open[:, 0] / cube.prior_close)
        session_return = np.log(cube.close[:, -1] / cube.open[:, 0])
    channels = np.stack([returns, share, span], axis=-1)  # (n, SLOTS, 3)
    realized = (returns**2).sum(axis=1)
    trailing_return = _trailing_sum(close_to_close, TRAILING)
    with np.errstate(invalid="ignore", divide="ignore"):
        trailing_vol = np.log(_trailing_sum(realized, TRAILING) / TRAILING)
    days = cube.dates.astype("datetime64[D]")
    # next_ok[i]: row i + 1 is the exchange session after row i.
    next_ok = np.zeros(n, dtype=bool)
    next_ok[:-1] = np.busday_count(days[:-1], days[1:], busdaycal=calendar) == 1
    # window_ok[i]: rows i - k + 1 .. i span at most k - 1 + slack sessions.
    window_ok = np.zeros(n, dtype=bool)
    if n >= k:
        spans = np.busday_count(days[: n - k + 1], days[k - 1 :], busdaycal=calendar)
        window_ok[k - 1 :] = spans <= k - 1 + WINDOW_SLACK
    keep = np.asarray(member, dtype=bool) & window_ok
    keep[: TRAILING - 1] = False
    idx = np.nonzero(keep)[0]
    if len(idx) == 0:
        return None
    window = idx[:, None] + np.arange(-k + 1, 1)[None, :]  # (M, k)
    return {
        "idx": idx,
        "window": window,
        "dates": days[idx],
        "x_name": channels[window].reshape(len(idx), k * SLOTS, len(NAME_CHANNELS)),
        "gap": gap[idx],
        "trailing_return_20": trailing_return[idx],
        "trailing_vol_20": trailing_vol[idx],
        "y_return": stage1.next_session_labels(session_return, next_ok)[idx],
    }


# One benchmark's bar returns on each of a cube's sessions: (n, SLOTS),
# zero where the benchmark has no complete session that day, and the
# count of such rows.
def aligned_benchmark(bench: SessionCube, dates: np.ndarray) -> tuple[np.ndarray, int]:
    """Return (the (n, SLOTS) aligned bar returns, rows zero-filled)."""
    days = np.asarray(dates, dtype="datetime64[D]")
    bench_days = bench.dates.astype("datetime64[D]")
    out = np.zeros((len(days), SLOTS))
    if len(bench) == 0:
        return out, len(days)
    position = np.searchsorted(bench_days, days)
    inside = position < len(bench_days)
    found = np.zeros(len(days), dtype=bool)
    found[inside] = bench_days[position[inside]] == days[inside]
    returns = bar_returns(bench)
    out[found] = returns[position[found]]
    return out, int((~found).sum())


# Bollinger position of each close in its own 20-session band, as the
# live entry rule reads it (`entry.bollinger_z`): -1 at the lower band,
# +1 at the upper. Written here in numpy so the module imports no desk
# code; the test asserts it equals the desk's.
def band_z(close: np.ndarray, window: int = TRAILING) -> np.ndarray:
    """Return the (T, N) band position, NaN before the window is full."""
    out = np.full(close.shape, np.nan)
    for t in range(window - 1, close.shape[0]):
        piece = close[t - window + 1 : t + 1]
        with np.errstate(all="ignore"):
            mean = np.nanmean(piece, axis=0)
            std = np.nanstd(piece, axis=0)
            out[t] = (close[t] - mean) / (2 * std)
    return out


# The share of the day's members whose adjusted close rose on the day:
# (T,) over the panel's dates, NaN where no member has a return.
def breadth(
    panel: Any, mask_by_date: MaskByDate, book: tuple[str, ...] | None = None
) -> np.ndarray:
    """Return the (T,) breadth series."""
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    tickers = tuple(panel.tickers) if book is None else tuple(book)
    up = np.zeros(len(days))
    counted = np.zeros(len(days))
    close = np.asarray(panel.adj_close, dtype=float)
    for ticker in tickers:
        if ticker not in panel.tickers or ticker == panel.benchmark:
            continue
        j = panel.index(ticker)
        member = _member_rows(mask_by_date, ticker, days)
        change = np.full(len(days), np.nan)
        with np.errstate(invalid="ignore"):
            change[1:] = close[1:, j] - close[:-1, j]
        ok = member & np.isfinite(change)
        up[ok] += change[ok] > 0
        counted[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(counted > 0, up / counted, np.nan)


# Forward and trailing statistics over `horizon` sessions from a (T, N)
# adjusted-close panel: fwd (log return to t + h), drawdown (min ratio over
# t + 1 .. t + h minus one), vol (log sum of squared daily log returns over
# the next h) and trailing_vol (the same over t - h + 1 .. t). NaN where
# the horizon runs past the panel or a price is missing.
def horizon_features(
    adj_close: np.ndarray, horizon: int = HORIZON
) -> dict[str, np.ndarray]:
    """Return {fwd, drawdown, vol, trailing_vol}, each (T, N)."""
    close = np.asarray(adj_close, dtype=float)
    t, n = close.shape
    fwd, drawdown, vol, trailing = (np.full((t, n), np.nan) for _ in range(4))
    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = np.full((t, n), np.nan)
        r2[1:] = np.log(close[1:] / close[:-1]) ** 2
        # Sums of squared returns over any span, and how many were missing.
        cumulative = np.concatenate([np.zeros((1, n)), np.nancumsum(r2, axis=0)])
        missing = np.concatenate(
            [np.zeros((1, n), dtype=int), np.cumsum(~np.isfinite(r2), axis=0)]
        )
        if t > horizon:
            fwd[:-horizon] = np.log(close[horizon:] / close[:-horizon])
            ratio_min = np.full((t - horizon, n), np.inf)
            for j in range(1, horizon + 1):
                ratio_min = np.minimum(
                    ratio_min, close[j : t - horizon + j] / close[: t - horizon]
                )
            drawdown[:-horizon] = ratio_min - 1.0
            # Squared returns of sessions t + 1 .. t + horizon.
            forward_sum = cumulative[horizon + 1 :] - cumulative[1 : t - horizon + 1]
            forward_missing = missing[horizon + 1 :] - missing[1 : t - horizon + 1]
            vol[:-horizon] = np.where(forward_missing == 0, np.log(forward_sum), np.nan)
        if t >= horizon:
            # Squared returns of sessions t - horizon + 1 .. t.
            back_sum = cumulative[horizon:] - cumulative[:-horizon]
            back_missing = missing[horizon:] - missing[:-horizon]
            trailing[horizon - 1 :] = np.where(
                back_missing == 0, np.log(back_sum), np.nan
            )
    return {"fwd": fwd, "drawdown": drawdown, "vol": vol, "trailing_vol": trailing}


# The downgrade target from a (T, N) grade panel: for a row graded A or
# better, 1.0 when any of the next `horizon` grades is below A, else 0.0;
# NaN below A on t or where the horizon runs past the panel.
def downgrade_target(grades: np.ndarray, horizon: int = HORIZON) -> np.ndarray:
    """Return the (T, N) downgrade target."""
    g = np.asarray(grades)
    t, n = g.shape
    out = np.full((t, n), np.nan)
    if t <= horizon:
        return out
    below = (g < A_MIN_GRADE).astype(int)
    cumulative = np.concatenate([np.zeros((1, n), dtype=int), np.cumsum(below, axis=0)])
    ahead = cumulative[horizon + 1 :] - cumulative[1 : t - horizon + 1]
    eligible = g[:-horizon] >= A_MIN_GRADE
    out[:-horizon] = np.where(eligible, (ahead > 0).astype(float), np.nan)
    return out


# The desk's regime on each panel session as six numbers, (T, 6) in the
# order of the `regime_*` scalars.
def regime_scalars(report: Any) -> np.ndarray:
    """Return the (T, 6) regime scalars."""
    states = list(report.regime.states)
    out = np.full((len(states), 6), np.nan)
    for t, state in enumerate(states):
        out[t] = (
            float(state.exposure),
            float(state.selection_confidence),
            float(state.participation_percentile),
            float(state.ai_drawdown),
            1.0 if str(state.rotation_leader) == "ai" else 0.0,
            1.0 if bool(getattr(state, "tightening", False)) else 0.0,
        )
    return out


# Everything the desk report contributes, per (panel session, panel name):
# the grade panel, the stance panels, the band z, the regime scalars, the
# breadth and the horizon features of the adjusted close.
def panel_features(report: Any, mask_by_date: MaskByDate) -> dict[str, Any]:
    """Return the panel-level inputs and targets keyed by name."""
    panel = report.panel
    grades = np.asarray(report.graded.grades, dtype=int)
    stances = {
        name: np.asarray(values, dtype=float)
        for name, values in sorted(report.graded.stances.items())
    }
    return {
        "dates": np.asarray(panel.dates, dtype="datetime64[D]"),
        "tickers": tuple(panel.tickers),
        "grades": grades,
        "stances": stances,
        "band_z": band_z(np.asarray(panel.adj_close, dtype=float)),
        "regime": regime_scalars(report),
        "breadth": breadth(panel, mask_by_date),
        "downgrade": downgrade_target(grades),
        **horizon_features(np.asarray(panel.adj_close, dtype=float)),
    }


# Build the dataset from the cubes, the membership mask and the desk
# report; see the module docstring for the row rule. `k` is the sessions
# of bars per row (the plan's 60; tests use less), `benchmarks` the market
# channels wanted in order (the ones with a cube are kept).
def dataset(
    cubes: Mapping[str, SessionCube],
    mask_by_date: MaskByDate,
    report: Any,
    benchmarks: tuple[str, ...] = BENCHMARKS,
    calendar: np.busdaycalendar | None = None,
    k: int = K_SESSIONS,
) -> Dataset2:
    """Return the Dataset2 of every graded member (name, session t) row."""
    if calendar is None:
        calendar = default_calendar()
    found = tuple(b for b in benchmarks if b in cubes and len(cubes[b]) > 0)
    features = panel_features(report, mask_by_date)
    panel_days = features["dates"]
    column = {t: j for j, t in enumerate(features["tickers"])}
    stance_names = tuple(features["stances"])
    scalar_names = (*FIXED_SCALARS, *(f"stance_{s}" for s in stance_names))
    parts: list[dict[str, np.ndarray]] = []
    fill = 0
    for ticker in sorted(cubes):
        if ticker in found or ticker not in column:
            continue
        cube = cubes[ticker]
        if len(cube) == 0:
            continue
        member = _member_rows(mask_by_date, ticker, cube.dates)
        rows = cube_rows(cube, member, calendar, k)
        if rows is None:
            continue
        # Join the desk on the row's date; rows the desk has no session
        # for are dropped (the desk's evidence is an input here).
        position = np.searchsorted(panel_days, rows["dates"])
        inside = position < len(panel_days)
        graded = np.zeros(len(position), dtype=bool)
        graded[inside] = panel_days[position[inside]] == rows["dates"][inside]
        if not graded.any():
            continue
        j = column[ticker]
        p = position[graded]
        x_name = rows["x_name"][graded]
        window = rows["window"][graded]
        market = []
        for bench in found:
            aligned, missing = aligned_benchmark(cubes[bench], cube.dates)
            fill += int(missing)
            market.append(aligned[window].reshape(len(p), k * SLOTS, 1))
        x_seq = np.concatenate([x_name, *market], axis=-1).astype(np.float32)
        grade = features["grades"][p, j]
        one_hot = np.column_stack([(grade == g).astype(float) for g in GRADE_ORDINALS])
        x_scalar = np.column_stack(
            [
                rows["gap"][graded],
                rows["trailing_return_20"][graded],
                rows["trailing_vol_20"][graded],
                features["breadth"][p],
                features["regime"][p],
                one_hot,
                features["band_z"][p, j],
                *[features["stances"][s][p, j] for s in stance_names],
            ]
        )
        part = {
            "dates": rows["dates"][graded],
            "x_seq": x_seq,
            "x_scalar": x_scalar,
            "y_return": rows["y_return"][graded],
            "y_downgrade20": features["downgrade"][p, j],
            "y_drawdown20": features["drawdown"][p, j],
            "y_vol20": features["vol"][p, j],
            "trailing_vol20": features["trailing_vol"][p, j],
            "fwd20": features["fwd"][p, j],
            "grade": grade,
        }
        # Only current inputs select decision rows; each head trains and
        # scores on its own finite labels without removing inference inputs.
        finite = np.isfinite(x_seq).all(axis=(1, 2)) & np.isfinite(x_scalar).all(axis=1)
        if not finite.any():
            continue
        part = {name: values[finite] for name, values in part.items()}
        part["tickers"] = np.full(len(part["dates"]), ticker, dtype=object)
        parts.append(part)
    if not parts:
        return _empty(k, found, scalar_names, fill)
    pooled = {name: np.concatenate([p[name] for p in parts]) for name in parts[0]}
    del parts
    order = np.lexsort((pooled["tickers"].astype(str), pooled["dates"]))
    pooled = {name: values[order] for name, values in pooled.items()}
    sessions, session_index = np.unique(pooled["dates"], return_inverse=True)
    return Dataset2(
        dates=pooled["dates"],
        tickers=pooled["tickers"].astype(str),
        x_seq=pooled["x_seq"],
        x_scalar=pooled["x_scalar"],
        scalar_names=scalar_names,
        y_return=pooled["y_return"],
        y_rank=rank_within(pooled["y_return"], session_index),
        y_downgrade20=pooled["y_downgrade20"],
        y_drawdown20=pooled["y_drawdown20"],
        y_vol20=pooled["y_vol20"],
        trailing_vol20=pooled["trailing_vol20"],
        fwd20=pooled["fwd20"],
        grade=pooled["grade"].astype(int),
        sessions=sessions,
        session_index=session_index.astype(int),
        k=int(k),
        benchmarks=found,
        benchmark_fill=int(fill),
        row_selection=stage1.ROW_SELECTION,
    )


# A dataset with no rows.
def _empty(
    k: int, benchmarks: tuple[str, ...], scalar_names: tuple[str, ...], fill: int
) -> Dataset2:
    return Dataset2(
        dates=np.zeros(0, dtype="datetime64[D]"),
        tickers=np.zeros(0, dtype=str),
        x_seq=np.zeros(
            (0, k * SLOTS, len(NAME_CHANNELS) + len(benchmarks)), np.float32
        ),
        x_scalar=np.zeros((0, len(scalar_names))),
        scalar_names=scalar_names,
        y_return=np.zeros(0),
        y_rank=np.zeros(0),
        y_downgrade20=np.zeros(0),
        y_drawdown20=np.zeros(0),
        y_vol20=np.zeros(0),
        trailing_vol20=np.zeros(0),
        fwd20=np.zeros(0),
        grade=np.zeros(0, dtype=int),
        sessions=np.zeros(0, dtype="datetime64[D]"),
        session_index=np.zeros(0, dtype=int),
        k=int(k),
        benchmarks=benchmarks,
        benchmark_fill=fill,
        row_selection=stage1.ROW_SELECTION,
    )


# The target array a name refers to.
def target_array(ds: Dataset2, target: str) -> np.ndarray:
    """Return the (M,) target values, NaN where undefined."""
    if target == "rank":
        return ds.y_rank
    if target == "downgrade20":
        return ds.y_downgrade20
    if target == "drawdown20":
        return ds.y_drawdown20
    if target == "vol20":
        return ds.y_vol20
    raise ValueError(f"unknown target {target!r}; expected one of {TARGETS}")


# The fitter of one model: given the training and test row masks it
# returns the (n_test, H) predictions and the parameter count.
Fitter = Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, int | None]]


# One ridge per target column on the rows where that target is defined
# (NaN predictions for a head with too few rows).
def _ridge_heads(
    x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray
) -> np.ndarray:
    out = np.full((len(x_test), y_train.shape[1]), np.nan)
    for h in range(y_train.shape[1]):
        ok = np.isfinite(y_train[:, h])
        if ok.sum() < MIN_NAMES:
            continue
        fitted = ridge_fit(x_train[ok], y_train[ok, h], chunk=RIDGE_CHUNK)
        out[:, h] = ridge_predict(fitted, x_test, chunk=RIDGE_CHUNK)
    return out


# The fitter of one model for the targets. The ridge fits one line per
# target on the fold's flattened rows; the torch families train one
# network with a head per target (`deep_stage2_nn.fit_predict`); the
# pretrained arm pretrains the encoder on the training rows, embeds every
# row and fits the ridge on [embedding, scalars] per target.
def _fitter(
    ds: Dataset2, model: str, targets: tuple[str, ...], y: np.ndarray, device: str
) -> Fitter:
    if model == "ridge":
        # Fit one ridge per target on the fold's flattened rows.
        def fit_predict(
            train: np.ndarray, test: np.ndarray
        ) -> tuple[np.ndarray, int | None]:
            return _ridge_heads(ds.flat(train), y[train], ds.flat(test)), None

        return fit_predict
    from backend.market import deep_stage2_nn as nn2

    kinds = tuple(TARGET_KIND[t] for t in targets)
    if model == "patchtst-pretrained":
        # Pretrain on the training rows, embed, then ridge per target.
        def fit_predict(
            train: np.ndarray, test: np.ndarray
        ) -> tuple[np.ndarray, int | None]:
            emb_train, emb_test, parameters = nn2.pretrain_embed(
                ds.x_seq[train],
                ds.x_scalar[train],
                ds.x_seq[test],
                ds.x_scalar[test],
                stage1.PATCHTST_CONFIG,
                PRETRAIN_CONFIG,
                device=device,
            )
            x_train = np.hstack([emb_train, ds.x_scalar[train].astype(np.float32)])
            x_test = np.hstack([emb_test, ds.x_scalar[test].astype(np.float32)])
            return _ridge_heads(x_train, y[train], x_test), parameters

        return fit_predict
    config = stage1.CNN_CONFIG if model == "cnn" else stage1.PATCHTST_CONFIG

    # Train the multi-head network on the training rows, predict the test rows.
    def fit_predict(
        train: np.ndarray, test: np.ndarray
    ) -> tuple[np.ndarray, int | None]:
        return nn2.fit_predict(
            model,
            ds.x_seq[train],
            ds.x_scalar[train],
            y[train],
            kinds,
            ds.x_seq[test],
            ds.x_scalar[test],
            config,
            device=device,
        )

    return fit_predict


# Walk-forward predictions of one model for every target at once: the
# first fit once `MIN_TRAIN` sessions exist, a refit every `REFIT`
# sessions on every row whose session is more than `PURGE` sessions
# before the test block's first session, predictions on the block only.
# Returns {target: Forecast}; `log` receives one line per fit.
def walk_forward(
    ds: Dataset2,
    model: str = "ridge",
    targets: tuple[str, ...] = TARGETS,
    log: Callable[[str], None] | None = None,
    device: str = "auto",
) -> dict[str, Forecast]:
    """Return the Forecast of `model` for each target over the dataset."""
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; expected one of {MODELS}")
    for target in targets:
        if target not in TARGETS:
            raise ValueError(f"unknown target {target!r}; expected one of {TARGETS}")
    y = (
        np.column_stack([target_array(ds, t) for t in targets])
        if len(ds)
        else np.zeros((0, len(targets)))
    )
    s = ds.session_index
    values = np.full((len(ds), len(targets)), np.nan)
    fits: list[dict[str, Any]] = []
    parameters: int | None = None
    fit_predict = _fitter(ds, model, targets, y, device)
    for start in range(MIN_TRAIN, len(ds.sessions), REFIT):
        end = min(start + REFIT, len(ds.sessions))
        train = (s < start - PURGE) & np.isfinite(y).any(axis=1)
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
                f"  {model} fit {len(fits)}: train through {record['train_through']}"
                f" ({record['n_train']:,} rows), test {record['test_start']}.."
                f"{record['test_end']} ({record['n_test']:,} rows), {seconds:.1f} s"
            )
    return {
        target: Forecast(model, target, values[:, h].copy(), list(fits), parameters)
        for h, target in enumerate(targets)
    }


# The daily cross-sectional Spearman of a forecast against a realized
# array (the IC), as a daily series with its HAC t.
def daily_spearman(
    ds: Dataset2,
    forecast: Forecast | np.ndarray,
    realized: np.ndarray,
    window: np.ndarray | None = None,
) -> DailySeries:
    """Return the per-date Spearman(forecast, realized) series."""
    values = forecast.values if isinstance(forecast, Forecast) else np.asarray(forecast)
    dates, ics = [], []
    for session, rows in _eligible_by_session(ds, [values, realized], window):
        ic = spearman(values[rows], realized[rows])
        if math.isfinite(ic):
            dates.append(ds.sessions[session])
            ics.append(ic)
    return DailySeries(np.asarray(dates, dtype="datetime64[D]"), np.asarray(ics))


# The area under the ROC curve of a score against a 0/1 label, by the
# Mann-Whitney statistic on average ranks (ties split); NaN unless both
# classes are present.
def auc(label: np.ndarray, score: np.ndarray) -> float:
    """Return the AUC of `score` for `label`."""
    label = np.asarray(label, dtype=float)
    score = np.asarray(score, dtype=float)
    ok = np.isfinite(label) & np.isfinite(score)
    label, score = label[ok], score[ok]
    positives = int((label > 0.5).sum())
    negatives = int(len(label) - positives)
    if positives == 0 or negatives == 0:
        return math.nan
    ranks = stage1._ranks(score)
    rank_sum = float(ranks[label > 0.5].sum())
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


# Out-of-sample AUC of a downgrade forecast over the window's rows.
def downgrade_auc(
    ds: Dataset2, forecast: Forecast | np.ndarray, window: np.ndarray | None = None
) -> dict[str, Any]:
    """Return {auc, n, positives}."""
    values = forecast.values if isinstance(forecast, Forecast) else np.asarray(forecast)
    ok = np.isfinite(values) & np.isfinite(ds.y_downgrade20)
    if window is not None:
        ok &= window
    return {
        "auc": auc(ds.y_downgrade20[ok], values[ok]),
        "n": int(ok.sum()),
        "positives": int((ds.y_downgrade20[ok] > 0.5).sum()),
    }


# Out-of-sample R² of the volatility forecast against the trailing
# realized-variance baseline over the window's rows (stage 1's form).
def vol_r2(
    ds: Dataset2, forecast: Forecast | np.ndarray, window: np.ndarray | None = None
) -> dict[str, Any]:
    """Return {r2, n, mse_model, mse_baseline}."""
    values = forecast.values if isinstance(forecast, Forecast) else np.asarray(forecast)
    ok = np.isfinite(values) & np.isfinite(ds.y_vol20) & np.isfinite(ds.trailing_vol20)
    if window is not None:
        ok &= window
    n = int(ok.sum())
    if n < 2:
        return {"r2": math.nan, "n": n, "mse_model": math.nan, "mse_baseline": math.nan}
    model_error = ds.y_vol20[ok] - values[ok]
    baseline_error = ds.y_vol20[ok] - ds.trailing_vol20[ok]
    sse_model = float(model_error @ model_error)
    sse_baseline = float(baseline_error @ baseline_error)
    return {
        "r2": 1.0 - sse_model / sse_baseline if sse_baseline > 0 else math.nan,
        "n": n,
        "mse_model": sse_model / n,
        "mse_baseline": sse_baseline / n,
    }


@dataclass(frozen=True)
class Decision:
    """The graded book with its worst-forecast names dropped, against itself, daily."""

    dates: np.ndarray
    book: np.ndarray  # the unmodified A/A+ book's horizon return per date
    modified: np.ndarray  # the same with the drops
    extra_turnover: np.ndarray  # turnover the drops added, in weight units
    names: np.ndarray  # A/A+ names per date
    dropped: np.ndarray  # names dropped per date
    cost_bps: float

    # The paired difference per session, gross of the drops' cost.
    def gross(self) -> DailySeries:
        """Return (modified - book) / HORIZON per date."""
        return DailySeries(self.dates, (self.modified - self.book) / HORIZON)

    # The paired difference per session net of the cost on the extra turnover.
    def net(self) -> DailySeries:
        """Return the gross difference minus cost x extra turnover per date."""
        cost = self.cost_bps / BP
        return DailySeries(self.dates, self.gross().values - cost * self.extra_turnover)

    # The JSON summary, in basis points per session.
    def summary(self) -> dict[str, Any]:
        """Return {mean_bp, t, gross_bp, gross_t, dates, book_bp, modified_bp, ...}."""
        net, gross = self.net(), self.gross()
        n = len(self.dates)
        return {
            "mean_bp": net.mean * BP if n else math.nan,
            "t": net.t,
            "gross_bp": gross.mean * BP if n else math.nan,
            "gross_t": gross.t,
            "dates": n,
            "book_bp": float(self.book.mean()) / HORIZON * BP if n else math.nan,
            "modified_bp": float(self.modified.mean()) / HORIZON * BP
            if n
            else math.nan,
            "extra_turnover": float(self.extra_turnover.mean()) if n else math.nan,
            "names": float(self.names.mean()) if n else math.nan,
            "dropped": float(self.dropped.mean()) if n else math.nan,
        }


# The decision test. Each date: the A/A+ rows with a forward return form
# the book (equal weight); those with a forecast are ranked, and the worst
# `DROP_QUANTILE` (at least one) are dropped - the largest forecasts when
# `higher_is_worse` (a downgrade probability), the smallest otherwise (a
# drawdown) - to form the modified book, equal weight of the rest. Both
# earn `fwd20`; the extra turnover is the modified book's minus the
# unmodified book's, date to date. Dates with fewer than MIN_NAMES A/A+
# rows, no forecast, or nothing left after the drops are skipped.
def decision_test(
    ds: Dataset2,
    forecast: Forecast | np.ndarray,
    window: np.ndarray | None = None,
    higher_is_worse: bool = True,
    cost_bps: float = COST_BPS,
) -> Decision:
    """Return the daily Decision of the drop rule against the graded book."""
    values = forecast.values if isinstance(forecast, Forecast) else np.asarray(forecast)
    ok = ds.keep_a & np.isfinite(ds.fwd20)
    if window is not None:
        ok &= window
    bounds = ds.bounds()
    held_book: dict[str, float] = {}
    held_modified: dict[str, float] = {}
    dates: list[np.datetime64] = []
    series: dict[str, list[float]] = {
        k: [] for k in ("book", "modified", "turnover", "names", "dropped")
    }
    for session in range(len(ds.sessions)):
        rows = np.arange(bounds[session], bounds[session + 1])
        rows = rows[ok[rows]]
        if len(rows) < MIN_NAMES:
            continue
        scored = rows[np.isfinite(values[rows])]
        if len(scored) == 0:
            continue
        k = max(1, int(math.ceil(DROP_QUANTILE * len(scored))))
        key = -values[scored] if higher_is_worse else values[scored]
        order = np.lexsort((ds.tickers[scored], key))
        dropped = set(scored[order[:k]].tolist())
        kept = np.array([r for r in rows if r not in dropped], dtype=int)
        if len(kept) == 0:
            continue
        book = {ds.tickers[r]: 1.0 / len(rows) for r in rows}
        modified = {ds.tickers[r]: 1.0 / len(kept) for r in kept}
        extra = _turnover(held_modified, modified) - _turnover(held_book, book)
        dates.append(ds.sessions[session])
        series["book"].append(float(ds.fwd20[rows].mean()))
        series["modified"].append(float(ds.fwd20[kept].mean()))
        series["turnover"].append(extra)
        series["names"].append(float(len(rows)))
        series["dropped"].append(float(k))
        held_book, held_modified = book, modified
    return Decision(
        dates=np.asarray(dates, dtype="datetime64[D]"),
        book=np.asarray(series["book"]),
        modified=np.asarray(series["modified"]),
        extra_turnover=np.asarray(series["turnover"]),
        names=np.asarray(series["names"]),
        dropped=np.asarray(series["dropped"]),
        cost_bps=cost_bps,
    )


# Every metric of one (model, target) forecast on one window: stage 1's
# for `rank`; AUC and the decision test for `downgrade20`; the daily IC
# against realized drawdown and the decision test for `drawdown20`; R²
# against trailing variance for `vol20`.
def evaluate(
    ds: Dataset2,
    forecast: Forecast,
    window: np.ndarray | None,
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
        "auc": None,
        "decision": None,
        "vol_r2": None,
    }
    if forecast.target == "rank":
        record["ic"] = stage1.daily_ic(ds, forecast, window).summary()
        record["portfolio"] = stage1.top_quantile_portfolio(
            ds, forecast, cost_bps, window
        ).summary()
        record["portfolio_a"] = stage1.top_quantile_portfolio(
            ds, forecast, cost_bps, window, keep=ds.keep_a
        ).summary()
    elif forecast.target == "downgrade20":
        record["auc"] = downgrade_auc(ds, forecast, window)
        record["decision"] = decision_test(
            ds, forecast, window, True, cost_bps
        ).summary()
    elif forecast.target == "drawdown20":
        record["ic"] = daily_spearman(ds, forecast, ds.y_drawdown20, window).summary()
        record["decision"] = decision_test(
            ds, forecast, window, False, cost_bps
        ).summary()
    else:
        record["vol_r2"] = vol_r2(ds, forecast, window)
    return record


# The study payload: every forecast on every window, the dataset's counts,
# the fits and the verdict. `forecasts` maps (model, target) to the
# walk-forward Forecast.
def study(
    ds: Dataset2,
    forecasts: Mapping[tuple[str, str], Forecast],
    windows: Mapping[str, tuple[date | None, date | None]] = WINDOWS,
    choosing: str = CHOOSING_WINDOW,
    cost_bps: float = COST_BPS,
) -> dict[str, Any]:
    """Return the JSON-serialisable stage-2 payload with its verdict."""
    if choosing not in windows:
        raise ValueError(f"choosing window {choosing!r} is not one of {list(windows)}")
    later = [name for name in windows if name != choosing]
    results = []
    for name, (start, end) in windows.items():
        window = window_rows(ds, start, end)
        for forecast in forecasts.values():
            record = evaluate(ds, forecast, window, cost_bps)
            record["window"] = name
            results.append(record)
    rows_per_window = {
        name: int(window_rows(ds, start, end).sum())
        for name, (start, end) in windows.items()
    }
    payload: dict[str, Any] = {
        "study": "deep_stage2",
        "stage": 2,
        "version": STUDY_VERSION,
        "plan": PLAN,
        "choosing_window": choosing,
        "later_window": later[0] if later else None,
        "windows": {
            name: {"start": _iso(start), "end": _iso(end)}
            for name, (start, end) in windows.items()
        },
        "constants": {
            "k_sessions": ds.k,
            "window_slack": WINDOW_SLACK,
            "slots": SLOTS,
            "channels": list(ds.channels),
            "scalars": list(ds.scalar_names),
            "horizon": HORIZON,
            "trailing": TRAILING,
            "refit": REFIT,
            "min_train": MIN_TRAIN,
            "purge": PURGE,
            "top_quantile": stage1.TOP_QUANTILE,
            "drop_quantile": DROP_QUANTILE,
            "cost_bps": cost_bps,
            "hac_lag": HAC_LAG,
            "decision_bp_floor": DECISION_BP_FLOOR,
            "decision_t_floor": DECISION_T_FLOOR,
            "min_names": MIN_NAMES,
            "ridge_alpha": RIDGE_ALPHA,
            "cnn": {
                k: (list(v) if isinstance(v, tuple) else v)
                for k, v in stage1.CNN_CONFIG.items()
            },
            "patchtst": dict(stage1.PATCHTST_CONFIG),
            "pretrain": dict(PRETRAIN_CONFIG),
        },
        "trials": len(forecasts),
        "trials_total": TRIALS,
        "models": sorted({m for m, _ in forecasts}, key=MODELS.index),
        "targets": sorted({t for _, t in forecasts}, key=TARGETS.index),
        "dataset": {
            "rows": len(ds),
            "row_selection": ds.row_selection,
            "observed_return_rows": int(np.isfinite(ds.y_return).sum()),
            "names": int(len(np.unique(ds.tickers))) if len(ds) else 0,
            "sessions": int(len(ds.sessions)),
            "first": str(ds.sessions[0]) if len(ds.sessions) else None,
            "last": str(ds.sessions[-1]) if len(ds.sessions) else None,
            "rows_per_window": rows_per_window,
            "graded_rows": int(ds.keep_a.sum()),
            "downgrade_rows": int(np.isfinite(ds.y_downgrade20).sum()),
            "downgrade_positives": int((ds.y_downgrade20 > 0.5).sum()),
            "horizon_rows": int(np.isfinite(ds.fwd20).sum()),
            "benchmarks": list(ds.benchmarks),
            "benchmark_fill": ds.benchmark_fill,
            "seq_len": ds.seq_len,
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


# Whether one (model, target) decision test passes the kill criteria:
# net mean >= the bp floor and t >= the t floor on the choosing window,
# and a non-negative net mean on the later window (which must have dates).
def _passes(
    choosing: Mapping[str, Any] | None, later: Mapping[str, Any] | None
) -> bool:
    if not choosing or not later:
        return False
    mean, t = _num(choosing.get("mean_bp")), _num(choosing.get("t"))
    later_mean = _num(later.get("mean_bp"))
    return (
        mean >= DECISION_BP_FLOOR
        and t >= DECISION_T_FLOOR
        and int(later.get("dates") or 0) > 0
        and later_mean >= 0.0
    )


# The kill criteria model by model and target by target, one line each:
# the decision tests against the floors on both windows, the record-only
# numbers (rank's IC and portfolio, vol20's R²) named as such.
def verdict_detail(payload: Mapping[str, Any]) -> list[str]:
    """Return the per-(model, target) findings behind the verdict."""
    choosing, later = payload["choosing_window"], payload.get("later_window")
    lines = []

    # The result record for (model, target) on a window, or None.
    def record(model: str, target: str, window: str | None) -> dict[str, Any] | None:
        return next(
            (
                r
                for r in payload["results"]
                if r["model"] == model
                and r["target"] == target
                and r["window"] == window
            ),
            None,
        )

    for model in MODELS:
        for target in TARGETS:
            first = record(model, target, choosing)
            if first is None:
                continue
            second = record(model, target, later) if later else None
            if target in DECISION_TARGETS:
                d1 = first.get("decision") or {}
                d2 = (second or {}).get("decision") or {}
                skill = (
                    f"AUC {_num((first.get('auc') or {}).get('auc')):.3f}"
                    if target == "downgrade20"
                    else f"IC {_num((first.get('ic') or {}).get('mean')):.4f}"
                    f" t {_num((first.get('ic') or {}).get('t')):.2f}"
                )
                passes = _passes(d1, d2)
                lines.append(
                    f"{model}/{target} on {choosing}: {skill}; decision test"
                    f" {_num(d1.get('mean_bp')):+.1f} bp/session"
                    f" t {_num(d1.get('t')):.2f}"
                    f" (floors {DECISION_BP_FLOOR:+.0f} bp, t {DECISION_T_FLOOR});"
                    f" {later or 'later window'}:"
                    f" {_num(d2.get('mean_bp')):+.1f} bp/session"
                    f" over {int(d2.get('dates') or 0)} dates:"
                    f" {'passes' if passes else 'fails'} the kill criteria"
                )
            elif target == "rank":
                ic = first.get("ic") or {}
                portfolio = first.get("portfolio") or {}
                lines.append(
                    f"{model}/rank on {choosing}: IC mean {_num(ic.get('mean')):.4f}"
                    f" t {_num(ic.get('t')):.2f}; top-quintile minus hurdle"
                    f" {_num(portfolio.get('mean_bp')):+.1f} bp/d t"
                    f" {_num(portfolio.get('t')):.2f} (stage 1's floors 2.0/2.0;"
                    " recorded, no decision test)"
                )
            else:
                r2 = _num((first.get("vol_r2") or {}).get("r2"))
                lines.append(
                    f"{model}/vol20 on {choosing}: R2 {r2:.4f} against trailing"
                    " variance (recorded, no decision test)"
                )
    lines.append(
        f"trials counted: {payload.get('trials', TRIALS)} run of"
        f" {payload.get('trials_total', TRIALS)} pre-registered"
        " (four models on four targets, the pretraining variant one of the four)"
    )
    return lines


# The verdict the plan fixes: INSUFFICIENT EVIDENCE unless a decision
# test clears both floors on the choosing window and is not negative on
# the later window; PASSED names the (model, target) pairs and is never a
# trading verdict.
def verdict(payload: Mapping[str, Any]) -> str:
    """Return the verdict string for the payload."""
    choosing, later = payload["choosing_window"], payload.get("later_window")
    passed = []
    for r in payload["results"]:
        if r["window"] != choosing or r["target"] not in DECISION_TARGETS:
            continue
        second = next(
            (
                s
                for s in payload["results"]
                if s["model"] == r["model"]
                and s["target"] == r["target"]
                and s["window"] == later
            ),
            None,
        )
        if _passes(r.get("decision"), (second or {}).get("decision")):
            passed.append(f"{r['model']}/{r['target']}")
    if passed:
        return f"{PASSED} ({', '.join(passed)}); not a trading verdict"
    return INSUFFICIENT


# A date as ISO text, or None.
def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
