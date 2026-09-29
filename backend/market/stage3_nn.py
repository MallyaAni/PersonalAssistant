"""Stage 3's networks: the level-aware sequence model (M3) and the
Jiang-Kelly-Xiu chart CNN (M2), walked forward as the pre-registration fixes.

`docs/research/stage3-plan-2026-09-29.md` (sections "M2", "M3", "The
walk-forward", "Normalization") decides these models, and every number it
fixes is read from `stage3_io`; nothing registered is restated here. What
the plan leaves open is decided once, below, and written into every
forecast's meta (`architecture`, `settings`).

**M3, the sequence model** (family ``seq``; questions ``ti`` and ``s1``).
The input is the exporter's `SeqTensor`: per name and cube session one
overnight-gap step and the 26 fifteen-minute bars, twelve channels in
`SEQ_CHANNELS` order, already in the plan's units with the one-bar volume
lag applied. The only transformation added is the plan's robust z per
channel (median and IQR over the fold's fit part, clipped to +-NET_CLIP).
A row (ticker, date d) reads the `SEQ_SESSIONS[kind]` sessions ending at d;
d must be a tensor session, and a row whose date or ticker the tensor lacks
is never trained on, gets no forecast and is counted (`meta["inputs"]`).
Sessions before the tensor's first, and sessions where `valid` is false,
are zeros.

* T-I: the dataset's rows of one (ticker, session s) are one unit. One
  forward pass over s-5..s (162 steps) emits an output at every step; slot
  k's forecast is the output at step 5*27 + 1 + k, session s's bar k. The
  TCN is causal (left padding only), so it never reads a bar after k
  (`test_stage3_nn` perturbs them). Loss: MSE over the unit's finite
  labels, winsorized at the fit rows' `WINSOR` quantiles and divided by
  the fit rows' standard deviation; forecasts are scaled back to bp.
* T-S1: one row is one unit, sixty sessions (1,620 steps). Attention pooling
  with a learned query over the window's steps, joined with the last step
  and the daily branch, then the head. Loss: MSE on the rank-Gauss label.
* Network (width W from the grid): Linear(12 -> W) plus a learned embedding
  of the 27 step types and a learned session-position embedding (K, W),
  K = SEQ_SESSIONS[kind] (6 for T-I, 60 for T-S1), whose row p is added to
  every step of the window's session p (0 the oldest, K - 1 the row's own
  session; padded and invalid sessions get theirs too); five residual causal
  convolutions (kernel 3, dilations 1, 2, 4, 8, 16: receptive field 63
  steps), one per dilation; a daily branch, a 2-layer MLP of width W over
  the daily columns (`daily_columns`: robust z from the fit rows, clipped to
  +-NET_CLIP, NaN as 0) and their missing indicators; a 2-layer head. The
  session-position embedding is a registered pre-run amendment (2026-09-29):
  the research proposal's M3 had "learned slot and session embeddings" and
  the plan's first draft omitted the second. Without it the T-S1 pooling
  could not tell which of its sixty sessions a pattern came from.

**M2, the chart CNN** (``cnn_i5``, ``cnn_i20``; T-S1 only), as JKX publish
it. Images of the 5 or 20 sessions ending at t, 3 pixels a day (open tick
left, high-low bar middle, close tick right), the moving average of the
image length as one pixel in each day's middle column, volume bars in the
bottom rows, every image scaled to its own window. Blocks of (5x3
convolution, batch norm, leaky ReLU 0.01, 2x1 max-pool): 64-128 for I5,
64-128-256 for I20, whose first convolution alone strides (3, 1) and dilates
(2, 1); 50% dropout, a fully connected layer to two classes (15,360 and
46,080 inputs, pinned by a test), Xavier initialization. Cross-entropy on
whether the row's `extra["r"]` is above its date's median, Adam at 1e-5,
batch 128, stop after 2 epochs without a better validation loss (at most
100), best weights kept; the forecast is the mean over the seeds of
P(class 1).

**Training, both families** (plan, "The walk-forward"). Folds are
`io.folds` over the dataset's sessions with `REFIT[(family, kind)]` and
`GAP[kind]`. In each fold every grid configuration is trained with the
first seed on the fit part, early-stopped on the validation block and
scored there with `io.selection_score` on raw labels; the best is trained
with the remaining seeds. There is no refit on the whole window: each
network keeps its early-stopped weights and predicts the test block.
`yhat` is the mean of the seeds, `yhat_seeds` keeps each, and (M3 only)
`yhat_configs` holds each configuration's first-seed test forecast for the
PBO diagnostic. Runs are deterministic: seeds for python, numpy and torch,
`torch.use_deterministic_algorithms(True)`, cuDNN benchmarking off, and
`CUBLAS_WORKSPACE_CONFIG` set before torch loads. Training is fp32.

**Decisions the plan leaves open** (also in `meta["architecture"]`):

* activation GELU (TCN blocks, daily branch, head); each residual block is
  pre-normed, x + dropout(GELU(conv(LayerNorm(x)))), with a LayerNorm
  after the fifth block - LayerNorm works per step, so the model stays
  causal (batch norm would mix steps);
* the step-type and session-position embeddings are initialized
  N(0, 0.02^2) and added to the input projection (the position table is
  broadcast over each session's steps rather than looked up by index: the
  same values, with a plain sum in the backward); the TCN's padding is zeros
  on the left only;
* the daily branch is Linear(2F -> W), GELU, dropout, Linear(W -> W), GELU;
  the head is Linear(in -> W), GELU, dropout, Linear(W -> 1), in = 2W for
  T-I ([step, daily]) and 3W for T-S1 ([pooled, last step, daily]);
* attention pooling scores each step as (K h_t) . q / sqrt(W), K a W x W
  linear map, q a learned query (N(0, 0.02^2)); steps of padded or invalid
  sessions are masked out of the softmax (a row with none valid pools
  uniformly), values are the step representations h_t;
* robust z: the scale is the IQR itself, not IQR/1.349; an IQR that is not
  positive (a flag channel, a constant column) keeps scale 1; channel
  statistics come from every step of every valid (name, session) cell
  dated on or before the fold's last fit session; daily statistics from
  the fit units (T-I: one per name-session); non-finite channel values
  become 0 after the z, like padded sessions;
* T-I targets are divided by the standard deviation of the winsorized fit
  labels (no centering); the validation loss uses the same transform, the
  selection score raw labels;
* warm-up: 5% of the planned optimizer steps (planned = max epochs x
  batches per epoch, rounded up), rising linearly from lr/warm-up to lr,
  then a cosine to 0 at the planned last step; the rate is set before
  every step, so early stopping ends the schedule where it stands;
* AdamW's weight decay applies to every parameter; betas and epsilon are
  torch's defaults; the last short batch of an epoch is kept; the shuffle
  is a torch generator seeded with the seed;
* "improved" means a strictly lower validation loss; a configuration whose
  validation score is NaN is chosen only if every one is (then the first),
  and ties go to the earlier configuration in grid order;
* M2 initializes biases to zero (Xavier-uniform weights), feeds pixels as
  0/1, draws no moving-average pixel on a day whose `days`-close average
  has a close missing (the image is kept and counted), scales prices over
  the open, high, low, close and moving average, and pads I20's first
  convolution (7, 1): every vertical padding from 7 to 18 gives the
  published 46,080 inputs, and 7 is the one at which its 24 strided windows
  tile the padded image exactly, with none reading padding only;
* a CPU run never touches a GPU: torch's Adam probes the current CUDA stream
  on every step whenever a GPU exists, which creates a CUDA context, so the
  probe is skipped when training on the CPU (graph capture cannot occur
  there).
"""

from __future__ import annotations

import math
import os
import random
import time
import warnings
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

# cuBLAS reads this when its first handle is created, and deterministic
# matrix products on CUDA need it; it is set before torch loads, the one
# moment certainly early enough.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np  # noqa: E402

from backend.market import stage3_io as io  # noqa: E402

try:  # torch trains the networks; images, windows and scaling need numpy only
    import torch
    from torch import nn
except ImportError:  # pragma: no cover - a box without torch renders and indexes
    torch = None
    nn = None

# The torch module base class, or a stand-in so the numpy half imports anywhere.
_Module: Any = nn.Module if nn is not None else object

MODULE = "backend.market.stage3_nn"
# The questions each family answers.
QUESTIONS = {io.SEQ: io.KINDS, io.CNN_I5: (io.S1,), io.CNN_I20: (io.S1,)}

# M3's open choices (module docstring).
ACTIVATION = "gelu"
EMBED_STD = 0.02
# T-I: the first forecast step of a window, session s's bar 0 (5 * 27 + 1).
TI_FIRST_OUTPUT = (io.SEQ_SESSIONS[io.TI] - 1) * io.STEPS_PER_SESSION + 1

# M2: the image's rows (price area, gap, volume) per family.
CHART_ROWS = {io.CNN_I5: (25, 1, 6), io.CNN_I20: (51, 1, 12)}
# M2: the blocks' channels, the kernel, and each block's convolution shape.
JKX_CHANNELS = {io.CNN_I5: (64, 128), io.CNN_I20: (64, 128, 256)}
JKX_KERNEL = (5, 3)
JKX_SAME: dict[str, tuple[int, int]] = {
    "stride": (1, 1),
    "dilation": (1, 1),
    "padding": (2, 1),
}
JKX_FIRST: dict[str, dict[str, tuple[int, int]]] = {
    io.CNN_I5: JKX_SAME,
    io.CNN_I20: {"stride": (3, 1), "dilation": (2, 1), "padding": (7, 1)},
}
# The fully connected layer's inputs as JKX publish them.
JKX_FLATTENED = {io.CNN_I5: 15_360, io.CNN_I20: 46_080}
# An "on" pixel of a stored image; the network reads pixel / PIXEL.
PIXEL = 255
# Images per prediction batch (batch norm is in eval mode, so size is free).
CNN_EVAL_BATCH = 1024
# Images rendered at once, which bounds the renderer's scratch arrays.
RENDER_CHUNK = 4096


@dataclass(frozen=True)
class Settings:
    """A run's knobs; every default is the registration.

    Tests and smoke runs shrink them. A forecast records every value, and
    `meta["registered"]` is false when anything but the device differed.
    `grid` replaces the configuration grid: for ``seq`` dicts of lr,
    dropout and width; for the CNN one dict whose lr replaces Adam's 1e-5.
    """

    grid: tuple[Mapping[str, Any], ...] | None = None
    seeds: tuple[int, ...] = io.SEEDS
    min_train: int = io.MIN_TRAIN
    validation: int = io.VALIDATION
    refit: int | None = None
    gap: int | None = None
    max_epochs: int | None = None
    patience: int | None = None
    batch: int | None = None
    max_folds: int | None = None
    device: str = "auto"

    # True when nothing but the device differs from the registration.
    def registered(self) -> bool:
        """Return whether these settings are the registered protocol."""
        optional = (
            self.refit,
            self.gap,
            self.max_epochs,
            self.patience,
            self.batch,
            self.max_folds,
        )
        return (
            self.grid is None
            and tuple(self.seeds) == io.SEEDS
            and self.min_train == io.MIN_TRAIN
            and self.validation == io.VALIDATION
            and all(value is None for value in optional)
        )


# ---------------------------------------------------------------------------
# Scaling, windows and units (numpy only)
# ---------------------------------------------------------------------------


# The robust z's centre and scale for every column of an (n, F) array: the
# median and the interquartile range of its finite values. A column with no
# finite value centres on 0; one whose IQR is not positive (a flag, a
# constant) keeps scale 1 rather than being blown up.
def robust_stats(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return ((F,) medians, (F,) IQR scales) of the columns of `x`."""
    x = np.asarray(x, dtype=np.float64)
    columns = x.shape[1]
    if not len(x):
        return np.zeros(columns), np.ones(columns)
    x = np.where(np.isfinite(x), x, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        q25, q50, q75 = np.nanpercentile(x, [25.0, 50.0, 75.0], axis=0)
    iqr = q75 - q25
    median = np.where(np.isfinite(q50), q50, 0.0)
    scale = np.where(np.isfinite(iqr) & (iqr > 0), iqr, 1.0)
    return median, scale


# The daily branch's input: each column's robust z, clipped to +-NET_CLIP,
# a missing value as 0, then one 0/1 missing indicator per column.
def daily_inputs(x: np.ndarray, median: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Return the (n, 2F) float32 daily-branch input for the (n, F) columns."""
    x = np.asarray(x, dtype=np.float64)
    finite = np.isfinite(x)
    z = (np.where(finite, x, 0.0) - median) / scale
    z = np.where(finite, np.clip(z, -io.NET_CLIP, io.NET_CLIP), 0.0)
    return np.concatenate([z, (~finite).astype(np.float64)], axis=1).astype(np.float32)


# The sequence channels' robust z: each channel's median and IQR over every
# step of every valid (name, session) cell of the tensor dated on or before
# `cutoff`, the fold's last fit session. An IQR that is not positive (the
# gap-step flag) keeps scale 1.
def channel_stats(
    seq: np.ndarray, valid: np.ndarray, sessions: np.ndarray, cutoff: np.datetime64
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((C,) medians, (C,) IQR scales) of the tensor's channels."""
    channels = seq.shape[-1]
    median = np.zeros(channels)
    scale = np.ones(channels)
    dates = np.asarray(sessions, dtype="datetime64[D]")
    cells = np.asarray(valid, dtype=bool) & (dates <= cutoff)[None, :]
    for c in range(channels):
        values = np.asarray(seq[..., c][cells], dtype=np.float32).ravel()
        values = values[np.isfinite(values)]
        if not len(values):
            continue
        q25, q50, q75 = np.percentile(values, [25.0, 50.0, 75.0])
        median[c] = q50
        scale[c] = q75 - q25 if q75 - q25 > 0 else 1.0
    return median, scale


# Each key's index in `reference` (a set of unique values), -1 where absent.
def positions(reference: np.ndarray, keys: np.ndarray) -> np.ndarray:
    """Return the (len(keys),) int64 positions of `keys` in `reference`."""
    reference = np.asarray(reference)
    keys = np.asarray(keys)
    out = np.full(len(keys), -1, dtype=np.int64)
    if not len(reference) or not len(keys):
        return out
    order = np.argsort(reference, kind="stable")
    ordered = reference[order]
    at = np.clip(np.searchsorted(ordered, keys), 0, len(ordered) - 1)
    hit = ordered[at] == keys
    out[hit] = order[at[hit]]
    return out


# The windows of a batch of units: for each (tensor name, tensor session
# the window ends at), the `sessions` sessions ending there, earliest
# first, as a (B, sessions, 27, C) copy of the tensor, and which of them are
# real - a session before the tensor's first, or one the name has no
# complete cube session for, is not (the caller zeroes it after scaling).
def window_arrays(
    seq: np.ndarray,
    valid: np.ndarray,
    name: np.ndarray,
    end: np.ndarray,
    sessions: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((B, sessions, 27, C) windows, (B, sessions) validity)."""
    span = np.asarray(end, dtype=np.int64)[:, None] - (sessions - 1)
    span = span + np.arange(sessions, dtype=np.int64)[None, :]
    inside = span >= 0
    span = np.maximum(span, 0)
    rows = np.asarray(name, dtype=np.int64)[:, None]
    return seq[rows, span], inside & np.asarray(valid, dtype=bool)[rows, span]


@dataclass(frozen=True)
class Units:
    """The training examples of a dataset and where their outputs land.

    T-I: a (ticker, session) with one output per slot 0..23; T-S1: a row.
    """

    first: np.ndarray  # (U,) the unit's first dataset row: key and daily block
    rows: np.ndarray  # (U, K) the dataset row of each output, -1 where none
    targets: np.ndarray  # (U, K) float64 raw labels, NaN where unknown
    of_row: np.ndarray  # (R,) each dataset row's unit, -1 when it has none


# Group T-I rows into (ticker, session) units. Rows are sorted by (date,
# ticker, slot), so a unit is a run of equal (date, ticker) and its outputs
# are its slots; a row whose slot is outside 0..23 belongs to no unit, and
# a repeated (ticker, session, slot) is refused.
def ti_units(data: io.Stage3Data) -> Units:
    """Return the name-session units of a T-I dataset."""
    count = len(data)
    new = np.ones(count, dtype=bool)
    new[1:] = (data.dates[1:] != data.dates[:-1]) | (
        data.tickers[1:] != data.tickers[:-1]
    )
    unit = np.cumsum(new) - 1
    first = np.flatnonzero(new)
    slot = np.asarray(data.slot, dtype=np.int64)
    inside = np.flatnonzero((slot >= 0) & (slot < io.TI_SLOTS))
    keys = unit[inside] * io.TI_SLOTS + slot[inside]
    if len(np.unique(keys)) != len(keys):
        raise ValueError("T-I rows repeat a (ticker, session, slot)")
    rows = np.full((len(first), io.TI_SLOTS), -1, dtype=np.int64)
    targets = np.full((len(first), io.TI_SLOTS), np.nan)
    rows[unit[inside], slot[inside]] = inside
    targets[unit[inside], slot[inside]] = data.y[inside]
    of_row = np.full(count, -1, dtype=np.int64)
    of_row[inside] = unit[inside]
    return Units(first, rows, targets, of_row)


# One unit per T-S1 row, its one output the row itself.
def s1_units(data: io.Stage3Data) -> Units:
    """Return the row units of a T-S1 dataset."""
    rows = np.arange(len(data), dtype=np.int64)
    targets = np.asarray(data.y, dtype=np.float64)[:, None]
    return Units(rows, rows[:, None], targets, rows)


# ---------------------------------------------------------------------------
# Chart images (numpy only)
# ---------------------------------------------------------------------------


# The moving average of the `days` closes ending at each date, per name;
# NaN where any of those closes is missing or the panel is too short.
def moving_average(close: np.ndarray, days: int) -> np.ndarray:
    """Return the (T, N) trailing `days`-session mean of the (T, N) closes."""
    close = np.asarray(close, dtype=np.float64)
    out = np.full(close.shape, np.nan)
    if len(close) >= days:
        windows = np.lib.stride_tricks.sliding_window_view(close, days, axis=0)
        out[days - 1 :] = windows.mean(axis=-1)
    return out


# Draw JKX images, one per row of the (M, days) arrays. Each day is three
# pixels wide: the open a tick in its left column, the high-low bar in the
# middle column, the close a tick in the right column; the moving average is
# one pixel in the middle column where it is defined. Prices are scaled so
# the window's extremes (moving average included) touch the top and the
# bottom of the price area; volume bars fill the bottom rows, scaled to the
# window's largest volume, under one empty gap row. An image with any OHLC
# missing, or with no price range, is left blank and not kept.
def render_charts(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    average: np.ndarray,
    family: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((M, H, W) uint8 images of 0 and PIXEL, (M,) kept)."""
    days, height, width = io.CNN_IMAGES[family]
    price_rows, _, volume_rows = CHART_ROWS[family]
    o, h, lo, c, v, ma = (
        np.asarray(a, dtype=np.float64).reshape(-1, days)
        for a in (opens, highs, lows, closes, volumes, average)
    )
    count = len(o)
    ohlc = np.stack([o, h, lo, c], axis=1)  # (M, 4, days)
    complete = np.isfinite(ohlc).all(axis=(1, 2))
    ma_ok = np.isfinite(ma)
    prices = np.concatenate([ohlc.reshape(count, -1), np.where(ma_ok, ma, np.nan)], 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        highest = np.nanmax(prices, axis=1) if count else np.zeros(0)
        lowest = np.nanmin(prices, axis=1) if count else np.zeros(0)
    keep = complete & np.isfinite(highest - lowest) & (highest - lowest > 0)
    top = np.where(keep, highest, 1.0)[:, None]
    span = np.where(keep, highest - lowest, 1.0)[:, None]

    # The price row of each price: 0 at the window's top, price_rows - 1 at
    # its bottom (a missing price is put at the top and never drawn).
    def row(price: np.ndarray) -> np.ndarray:
        price = np.where(np.isfinite(price), price, top)
        at = np.rint((top - price) * (price_rows - 1) / span)
        return np.clip(at, 0, price_rows - 1).astype(np.int64)

    images = np.zeros((count, height, width), dtype=np.uint8)
    each = np.arange(count)[:, None]
    left = 3 * np.arange(days)[None, :]
    images[each, row(o), left] = PIXEL
    images[each, row(c), left + 2] = PIXEL
    r_high, r_low = row(h), row(lo)
    grid = np.arange(price_rows)[None, None, :]
    bar = (grid >= np.minimum(r_high, r_low)[..., None]) & (
        grid <= np.maximum(r_high, r_low)[..., None]
    )
    images[:, :price_rows, 1::3] |= (
        np.where(bar, PIXEL, 0).astype(np.uint8).transpose(0, 2, 1)
    )
    m_at, d_at = np.nonzero(ma_ok)
    images[m_at, row(ma)[m_at, d_at], 3 * d_at + 1] = PIXEL
    volume = np.where(np.isfinite(v) & (v > 0), v, 0.0)
    peak = volume.max(axis=1, keepdims=True) if count else np.ones((0, 1))
    tall = np.rint(volume * volume_rows / np.where(peak > 0, peak, 1.0))
    tall = np.clip(tall, 0, volume_rows).astype(np.int64)
    levels = np.arange(volume_rows)[None, None, :]
    column = levels >= (volume_rows - tall)[..., None]
    images[:, height - volume_rows :, 1::3] = (
        np.where(column, PIXEL, 0).astype(np.uint8).transpose(0, 2, 1)
    )
    images[~keep] = 0
    return images, keep


# Every dataset row's chart: the `days` bars ending at the row's date for
# its ticker, with the moving average of the `days` closes ending at each
# day. Returns the (R, H, W) uint8 images, whether each row has one, and
# the count of rows without one by reason.
def chart_images(
    bars: io.DailyOHLCV, dates: np.ndarray, tickers: np.ndarray, family: str
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """Return (images, (R,) has image, counts) for the rows (dates, tickers)."""
    days, height, width = io.CNN_IMAGES[family]
    bar_dates = np.asarray(bars.dates, dtype="datetime64[D]")
    names = np.asarray(bars.tickers).astype(str)
    _check_keys(bar_dates, names, "daily bars")
    column = positions(names, np.asarray(tickers).astype(str))
    at = positions(bar_dates, np.asarray(dates, dtype="datetime64[D]"))
    average = moving_average(bars.close, days)
    rows_n = len(dates)
    images = np.zeros((rows_n, height, width), dtype=np.uint8)
    keep = np.zeros(rows_n, dtype=bool)
    complete = np.zeros(rows_n, dtype=bool)
    partial = np.zeros(rows_n, dtype=bool)
    wanted = np.flatnonzero((column >= 0) & (at >= days - 1))
    for start in range(0, len(wanted), RENDER_CHUNK):
        rows = wanted[start : start + RENDER_CHUNK]
        span = at[rows, None] - (days - 1) + np.arange(days)[None, :]
        col = column[rows, None]
        o, h, low, c, v = (
            np.asarray(getattr(bars, name))[span, col]
            for name in ("open", "high", "low", "close", "volume")
        )
        ma = average[span, col]
        drawn, kept = render_charts(o, h, low, c, v, ma, family)
        images[rows] = drawn
        keep[rows] = kept
        complete[rows] = np.isfinite(np.stack([o, h, low, c])).all(axis=(0, 2))
        partial[rows] = kept & ~np.isfinite(ma).all(axis=1)
    listed = column >= 0
    located = listed & (at >= 0)
    counts = {
        "rows": rows_n,
        "images": int(keep.sum()),
        "no_ticker": int((~listed).sum()),
        "no_date": int((listed & (at < 0)).sum()),
        "short_history": int((located & (at < days - 1)).sum()),
        "missing_ohlc": int((located & (at >= days - 1) & ~complete).sum()),
        "flat_window": int((complete & ~keep).sum()),
        "partial_moving_average": int(partial.sum()),
    }
    return images, keep, counts


# The chart CNN's label: 1 where the row's relative return is above its
# date's median (over the date's finite returns), 0 where not, NaN where the
# return is unknown (those rows are predicted but never trained on).
def above_median(r: np.ndarray, dates: np.ndarray) -> np.ndarray:
    """Return (R,) float labels 1.0 / 0.0 / NaN."""
    r = np.asarray(r, dtype=np.float64)
    out = np.full(r.shape, np.nan)
    if not len(r):
        return out
    _, index = io.session_index(dates)
    order = np.argsort(index, kind="stable")
    bounds = np.searchsorted(index[order], np.arange(int(index.max()) + 2))
    for g in range(len(bounds) - 1):
        rows = order[bounds[g] : bounds[g + 1]]
        rows = rows[np.isfinite(r[rows])]
        if len(rows):
            out[rows] = (r[rows] > np.median(r[rows])).astype(np.float64)
    return out


# Refuse reference keys that are not strictly ascending dates or unique names.
def _check_keys(dates: np.ndarray, names: np.ndarray, what: str) -> None:
    if len(dates) > 1 and not (np.diff(dates.astype(np.int64)) > 0).all():
        raise ValueError(f"the {what}' dates must be strictly ascending")
    if len(np.unique(names)) != len(names):
        raise ValueError(f"the {what} list a ticker twice")


# ---------------------------------------------------------------------------
# Torch: determinism, the networks, the training loop
# ---------------------------------------------------------------------------


# Fail with a clear message where torch is missing.
def _require_torch() -> None:
    if torch is None:
        raise RuntimeError("stage3_nn trains with torch, which is not installed here")


# "cpu" or "cuda" for a requested device; "auto" is cuda when torch sees one.
def resolve_device(name: str) -> str:
    """Return the device a run trains on."""
    _require_torch()
    name = (name or "auto").strip().lower()
    if name not in ("auto", "cpu", "cuda"):
        raise ValueError(f"unknown device {name!r}; expected auto, cpu or cuda")
    if name == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if name == "cuda" and not torch.cuda.is_available():
        raise ValueError("device 'cuda' requested but torch reports no CUDA device")
    return name


# Run the block with torch's deterministic algorithms on and cuDNN's
# autotuner off, restoring whatever was set before.
@contextmanager
def deterministic_torch() -> Iterator[None]:
    """Make torch deterministic for the duration of the block."""
    _require_torch()
    before = (
        torch.are_deterministic_algorithms_enabled(),
        torch.backends.cudnn.benchmark,
        torch.backends.cudnn.deterministic,
    )
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(before[0])
        torch.backends.cudnn.benchmark = before[1]
        torch.backends.cudnn.deterministic = before[2]


# Seed python, numpy and torch (every device) with one seed.
def seed_everything(seed: int) -> None:
    """Seed every random generator a training run touches."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# The number of trainable parameters of a network.
def parameter_count(model: Any) -> int:
    """Return how many parameters `model` trains."""
    return int(sum(p.numel() for p in model.parameters() if p.requires_grad))


# The learning-rate multiplier at optimizer step `step` of `total` planned
# steps: linear warm-up over the first `warmup` steps (1/warmup up to 1),
# then a cosine from 1 down to 0 at the planned last step.
def lr_factor(step: int, warmup: int, total: int) -> float:
    """Return the multiplier of the base learning rate at `step`."""
    if step < warmup:
        return (step + 1) / warmup
    progress = min(1.0, (step - warmup) / max(1, total - warmup))
    return 0.5 * (1.0 + math.cos(math.pi * progress))


class CausalConvBlock(_Module):  # type: ignore[misc]  # torch is untyped here
    """One residual causal convolution: x + dropout(GELU(conv(LayerNorm(x))))."""

    # Build the block for `width` channels at one dilation, padded on the left.
    def __init__(self, width: int, kernel: int, dilation: int, dropout: float) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(width)
        self.conv = nn.Conv1d(width, width, kernel, dilation=dilation)
        self.left = (kernel - 1) * dilation
        self.dropout = nn.Dropout(dropout)

    # (B, L, W) -> (B, L, W): step t reads steps t - left .. t and nothing later.
    def forward(self, h: Any) -> Any:
        """Return the block's output for the (B, L, W) steps `h`."""
        z = self.norm(h).transpose(1, 2)
        z = self.conv(nn.functional.pad(z, (self.left, 0)))
        return h + self.dropout(nn.functional.gelu(z.transpose(1, 2)))


class SeqNet(_Module):  # type: ignore[misc]  # torch is untyped here
    """M3: step-type and session-position embeddings, causal TCN, daily
    branch, the question's head."""

    # Build the network for one question with `channels` sequence channels,
    # `daily` daily-branch inputs, width `width` and dropout `dropout`; its
    # windows are the question's SEQ_SESSIONS sessions.
    def __init__(
        self, kind: str, channels: int, daily: int, width: int, dropout: float
    ) -> None:
        super().__init__()
        if kind not in io.KINDS:
            raise ValueError(f"kind must be one of {io.KINDS}, not {kind!r}")
        self.kind = kind
        self.width = width
        self.sessions = io.SEQ_SESSIONS[kind]
        self.project = nn.Linear(channels, width)
        self.step_type = nn.Parameter(torch.empty(io.STEPS_PER_SESSION, width))
        nn.init.normal_(self.step_type, std=EMBED_STD)
        # Which session of the window a step is in: row p for position p, 0
        # the oldest, K - 1 the row's own session (pre-run amendment).
        self.session_position = nn.Embedding(self.sessions, width)
        nn.init.normal_(self.session_position.weight, std=EMBED_STD)
        self.blocks = nn.ModuleList(
            CausalConvBlock(width, int(io.SEQ_FIXED["kernel"]), int(d), dropout)
            for d in io.SEQ_FIXED["dilations"]
        )
        self.norm = nn.LayerNorm(width)
        self.daily = nn.Sequential(
            nn.Linear(daily, width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width, width),
            nn.GELU(),
        )
        joined = 2 * width
        if kind == io.S1:
            self.query = nn.Parameter(torch.empty(width))
            nn.init.normal_(self.query, std=EMBED_STD)
            self.key = nn.Linear(width, width, bias=False)
            joined = 3 * width
        self.head = nn.Sequential(
            nn.Linear(joined, width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width, 1),
        )

    # The (B, L, W) representation of every step of (B, L, C) windows of
    # exactly the question's sessions. Each step's input projection gets its
    # step type's embedding and its session's position embedding; the
    # position table is broadcast over each session's 27 steps (the values an
    # index lookup gives, with a plain sum in the backward).
    def encode(self, seq: Any) -> Any:
        """Return the TCN's per-step output."""
        sessions, extra = divmod(seq.shape[1], io.STEPS_PER_SESSION)
        if extra or sessions != self.sessions:
            raise ValueError(f"{seq.shape[1]} steps are not {self.sessions} sessions")
        position = self.session_position.weight[:, None, :].expand(
            -1, io.STEPS_PER_SESSION, -1
        )
        h = (
            self.project(seq)
            + self.step_type.repeat(sessions, 1)
            + position.reshape(-1, self.width)
        )
        for block in self.blocks:
            h = block(h)
        return self.norm(h)

    # T-I: (B, 24) outputs at the last session's bars 0..23; T-S1: (B, 1)
    # from the attention-pooled steps, the last step and the daily branch.
    # `step_valid` (B, L) marks the steps attention may read (T-S1).
    def forward(self, seq: Any, daily: Any, step_valid: Any = None) -> Any:
        """Return the outputs for (B, L, C) windows and (B, D) daily inputs."""
        h = self.encode(seq)
        d = self.daily(daily)
        if self.kind == io.TI:
            first = seq.shape[1] - io.STEPS_PER_SESSION + 1
            at = h[:, first : first + io.TI_SLOTS]
            daily_each = d[:, None, :].expand(-1, at.shape[1], -1)
            return self.head(torch.cat([at, daily_each], dim=-1)).squeeze(-1)
        scores = self.key(h) @ self.query / math.sqrt(self.width)
        if step_valid is not None:
            readable = step_valid | ~step_valid.any(dim=1, keepdim=True)
            scores = scores.masked_fill(~readable, float("-inf"))
        weights = torch.softmax(scores, dim=1)
        pooled = (weights[:, :, None] * h).sum(dim=1)
        return self.head(torch.cat([pooled, h[:, -1], d], dim=-1))


# The size of one convolution's output along one axis.
def _conv_out(size: int, kernel: int, stride: int, dilation: int, padding: int) -> int:
    return (size + 2 * padding - dilation * (kernel - 1) - 1) // stride + 1


# The JKX network's fully connected input for `family`, from its
# convolution and 2x1 pooling arithmetic (JKX publish 15,360 and 46,080).
def jkx_flattened_size(family: str) -> int:
    """Return the flattened feature size of the chart CNN for `family`."""
    _, height, width = io.CNN_IMAGES[family]
    for block in range(len(JKX_CHANNELS[family])):
        shape = JKX_FIRST[family] if block == 0 else JKX_SAME
        height = _conv_out(
            height,
            JKX_KERNEL[0],
            shape["stride"][0],
            shape["dilation"][0],
            shape["padding"][0],
        )
        width = _conv_out(
            width,
            JKX_KERNEL[1],
            shape["stride"][1],
            shape["dilation"][1],
            shape["padding"][1],
        )
        height //= 2
    return JKX_CHANNELS[family][-1] * height * width


class JKXNet(_Module):  # type: ignore[misc]  # torch is untyped here
    """The JKX (2023) chart CNN for one image size: conv blocks, dropout, 2 classes."""

    # Build the published network for `family` (cnn_i5 or cnn_i20), with
    # Xavier-uniform weights and zero biases in the convolutions and the
    # fully connected layer.
    def __init__(self, family: str) -> None:
        super().__init__()
        layers: list[Any] = []
        channels_in = 1
        for block, channels in enumerate(JKX_CHANNELS[family]):
            shape = JKX_FIRST[family] if block == 0 else JKX_SAME
            layers += [
                nn.Conv2d(channels_in, channels, JKX_KERNEL, **shape),
                nn.BatchNorm2d(channels),
                nn.LeakyReLU(float(io.CNN_FIXED["leaky_slope"])),
                nn.MaxPool2d((2, 1)),
            ]
            channels_in = channels
        self.features = nn.Sequential(*layers)
        self.flattened = jkx_flattened_size(family)
        self.classify = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(float(io.CNN_FIXED["dropout"])),
            nn.Linear(self.flattened, 2),
        )
        for module in self.modules():
            if isinstance(module, nn.Conv2d | nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                nn.init.zeros_(module.bias)

    # (B, 1, H, W) images with pixels in [0, 1] -> (B, 2) class logits.
    def forward(self, images: Any) -> Any:
        """Return the two class logits of each image."""
        return self.classify(self.features(images))


@dataclass(frozen=True)
class TrainPlan:
    """How one network is optimized and when it stops."""

    optimizer: str  # "AdamW" or "Adam"
    lr: float
    weight_decay: float
    clip: float | None  # gradient-norm clip, or None
    warmup_share: float | None  # cosine schedule with this warm-up, or constant
    max_epochs: int
    patience: int
    batch: int
    eval_batch: int


# A copy of a network's weights, kept while later epochs overwrite them.
def _snapshot(model: Any) -> dict[str, Any]:
    return {key: value.detach().clone() for key, value in model.state_dict().items()}


# Names torch has given the optimizer's per-step graph-capture probe.
_CAPTURE_PROBES = (
    "_accelerator_graph_capture_health_check",
    "_cuda_graph_capture_health_check",
)


# Do nothing: stands in for the graph-capture probe on a CPU run.
def _no_capture_probe() -> None:
    return None


# The optimizer a plan names, over every parameter of the network. On the
# CPU its graph-capture probe is switched off: torch's Adam asks for the
# current CUDA stream on every step whenever a GPU exists, which creates a
# CUDA context on a GPU the run never uses (a shared one, on the Spark).
# Capture cannot happen on the CPU, so the probe has nothing to find there.
def _optimizer(model: Any, plan: TrainPlan, device: Any) -> Any:
    kind = torch.optim.AdamW if plan.optimizer == "AdamW" else torch.optim.Adam
    optimizer = kind(model.parameters(), lr=plan.lr, weight_decay=plan.weight_decay)
    if torch.device(device).type == "cpu":
        for probe in _CAPTURE_PROBES:
            if hasattr(optimizer, probe):
                setattr(optimizer, probe, _no_capture_probe)
    return optimizer


# One pass over the fit units in a seeded random order (the last batch may be
# short); with a schedule the learning rate is set before every step.
# Returns the optimizer steps taken so far.
def _run_epoch(
    task: Any,
    state: Any,
    model: Any,
    optimizer: Any,
    plan: TrainPlan,
    fit: np.ndarray,
    generator: Any,
    schedule: tuple[int, int, int],
    device: Any,
) -> int:
    step, warmup, total = schedule
    model.train()
    order = fit[torch.randperm(len(fit), generator=generator).numpy()]
    for lo in range(0, len(order), plan.batch):
        if plan.warmup_share is not None:
            for group in optimizer.param_groups:
                group["lr"] = plan.lr * lr_factor(step, warmup, total)
        inputs, targets = task.batch(state, order[lo : lo + plan.batch], device)
        total_loss, count = task.loss(task.forward(model, inputs), targets)
        optimizer.zero_grad(set_to_none=True)
        (total_loss / count.clamp(min=1)).backward()
        if plan.clip is not None:
            nn.utils.clip_grad_norm_(model.parameters(), plan.clip)
        optimizer.step()
        step += 1
    return step


# The mean training loss of a network over some units (validation), in eval
# mode, summed over every labelled output before dividing.
def _mean_loss(
    task: Any, state: Any, model: Any, units: np.ndarray, batch: int, device: Any
) -> float:
    model.eval()
    total, count = 0.0, 0.0
    with torch.no_grad():
        for lo in range(0, len(units), batch):
            inputs, targets = task.batch(state, units[lo : lo + batch], device)
            part, n = task.loss(task.forward(model, inputs), targets)
            total += float(part)
            count += float(n)
    return total / count if count > 0 else math.nan


# A network's forecasts for some units, (n, K) in the question's units.
def _predict(
    task: Any, state: Any, model: Any, units: np.ndarray, batch: int, device: Any
) -> np.ndarray:
    model.eval()
    out = np.full((len(units), task.units.rows.shape[1]), np.nan)
    with torch.no_grad():
        for lo in range(0, len(units), batch):
            inputs, _ = task.batch(state, units[lo : lo + batch], device)
            raw = task.forward(model, inputs)
            out[lo : lo + batch] = task.forecast(state, raw).double().cpu().numpy()
    return out


# Train one network from `seed`: the seed sets the initialization, the
# shuffle and dropout; after every epoch the validation loss is measured,
# training stops after `patience` epochs without a strictly lower one, and
# the best epoch's weights are restored. Returns the network (eval mode) and
# a record of the run.
def _train(
    task: Any,
    state: Any,
    config: Mapping[str, Any],
    seed: int,
    fit: np.ndarray,
    val: np.ndarray,
    device: Any,
) -> tuple[Any, dict[str, Any]]:
    started = time.perf_counter()
    seed_everything(seed)
    model = task.build(config).to(device)
    plan = task.plan(config)
    optimizer = _optimizer(model, plan, device)
    generator = torch.Generator().manual_seed(seed)
    per_epoch = math.ceil(len(fit) / plan.batch)
    total = plan.max_epochs * per_epoch
    warmup = math.ceil(plan.warmup_share * total) if plan.warmup_share else 0
    best, best_epoch, stale, step, epoch = math.inf, 0, 0, 0, 0
    best_state = _snapshot(model)
    history: list[float] = []
    for epoch in range(1, plan.max_epochs + 1):
        step = _run_epoch(
            task,
            state,
            model,
            optimizer,
            plan,
            fit,
            generator,
            (step, warmup, total),
            device,
        )
        loss = _mean_loss(task, state, model, val, plan.eval_batch, device)
        history.append(loss)
        if loss < best:
            best, best_epoch, stale = loss, epoch, 0
            best_state = _snapshot(model)
        else:
            stale += 1
            if stale >= plan.patience:
                break
    model.load_state_dict(best_state)
    model.eval()
    seconds = time.perf_counter() - started
    return model, {
        "seed": seed,
        "epochs": epoch,
        "best_epoch": best_epoch,
        "val_loss": best,
        "val_loss_history": history,
        "steps": step,
        "warmup_steps": warmup,
        "planned_steps": total,
        "seconds": seconds,
        "seconds_per_epoch": seconds / max(epoch, 1),
        "parameters": parameter_count(model),
    }


# ---------------------------------------------------------------------------
# The two families as walk-forward tasks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SeqState:
    """One fold's scaling for M3, all from its fit part."""

    median: Any  # (C,) channel medians, on the device
    scale: Any  # (C,) channel IQRs, on the device
    daily: np.ndarray  # (U, 2F) float32 daily-branch inputs of every unit
    targets: np.ndarray  # (U, K) float32 training targets, NaN unknown
    y_scale: float  # T-I: the bp per training unit; T-S1: 1
    record: dict[str, Any]


# The training targets: T-I labels winsorized at the fit rows' WINSOR
# quantiles and divided by the standard deviation of those winsorized fit
# labels; T-S1 labels as they are (already rank-Gauss).
def scaled_targets(
    kind: str, targets: np.ndarray, fit: np.ndarray
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return ((U, K) training targets, a record of the transform)."""
    if kind != io.TI:
        return targets, {"y_scale": 1.0}
    values = targets[fit][np.isfinite(targets[fit])]
    low, high = (float(q) for q in np.quantile(values, io.WINSOR))
    scale = float(np.clip(values, low, high).std())
    scale = scale if scale > 0 else 1.0
    return np.clip(targets, low, high) / scale, {
        "winsor_bp": [low, high],
        "y_scale": scale,
    }


class _SeqTask:
    """M3 on one question: its units, windows, fold scaling and loss."""

    family = io.SEQ
    keeps_configs = True

    # Index the dataset's units and locate each one's window in the tensor.
    def __init__(
        self, data: io.Stage3Data, tensor: io.SeqTensor, settings: Settings
    ) -> None:
        self.kind = data.kind
        self.settings = settings
        self.units = ti_units(data) if data.kind == io.TI else s1_units(data)
        self.seq = np.asarray(tensor.seq)
        self.valid = np.asarray(tensor.valid, dtype=bool)
        self.sessions = np.asarray(tensor.sessions, dtype="datetime64[D]")
        names = np.asarray(tensor.tickers).astype(str)
        _check_keys(self.sessions, names, "sequence tensor")
        expected = (len(names), len(self.sessions), io.STEPS_PER_SESSION)
        if self.seq.shape != (*expected, len(io.SEQ_CHANNELS)):
            raise ValueError(f"the tensor is {self.seq.shape}; expected {expected} x C")
        if self.valid.shape != expected[:2]:
            raise ValueError(f"valid is {self.valid.shape}; expected {expected[:2]}")
        first = self.units.first
        self.name = positions(names, np.asarray(data.tickers[first]).astype(str))
        self.end = positions(self.sessions, data.dates[first].astype("datetime64[D]"))
        self.usable = (self.name >= 0) & (self.end >= 0)
        self.labelled = np.isfinite(self.units.targets).any(axis=1)
        self.columns = io.daily_columns(data.feature_names)
        if not len(self.columns):
            raise ValueError(f"the data has no {io.DAILY_PREFIX!r} daily column")
        self.daily = np.asarray(data.x[np.ix_(first, self.columns)], dtype=np.float32)
        self.window = io.SEQ_SESSIONS[self.kind]
        self.counts = self._counts(data)

    # How many rows cannot be forecast and why, the rows whose own session
    # the name has no complete cube session for (they are forecast from
    # zeros for that session), non-finite tensor values, and for T-I the
    # name-sessions whose daily columns differ across their slots.
    def _counts(self, data: io.Stage3Data) -> dict[str, int]:
        of_row = self.units.of_row
        has_unit = of_row >= 0
        unit = np.where(has_unit, of_row, 0)
        name_ok = has_unit & (self.name[unit] >= 0)
        usable = has_unit & self.usable[unit]
        own = np.zeros(len(self.usable), dtype=bool)
        where = np.flatnonzero(self.usable)
        own[where] = ~self.valid[self.name[where], self.end[where]]
        nonfinite = sum(int((~np.isfinite(block)).sum()) for block in self.seq)
        return {
            "rows": len(data),
            "units": len(self.units.first),
            "rows_without_window": int((~usable).sum()),
            "rows_bad_slot": int((~has_unit).sum()),
            "rows_no_ticker": int((has_unit & ~name_ok).sum()),
            "rows_no_session": int((name_ok & (self.end[unit] < 0)).sum()),
            "rows_own_session_invalid": int((usable & own[unit]).sum()),
            "tensor_nonfinite_values": nonfinite,
            "daily_columns": len(self.columns),
            "ti_units_daily_varies": self._daily_varies(data),
        }

    # T-I: how many name-sessions carry daily columns that differ across
    # their slots (the daily block at s-1 is one value per name-session).
    def _daily_varies(self, data: io.Stage3Data) -> int:
        if self.kind != io.TI or not len(data):
            return 0
        of_row = self.units.of_row
        varies = np.zeros(len(self.units.first), dtype=bool)
        step = 200_000
        for lo in range(0, len(data), step):
            rows = np.arange(lo, min(lo + step, len(data)))
            rows = rows[of_row[rows] >= 0]
            mine = np.asarray(data.x[np.ix_(rows, self.columns)])
            theirs = self.daily[of_row[rows]]
            same = (mine == theirs) | (np.isnan(mine) & np.isnan(theirs))
            varies[of_row[rows[~same.all(axis=1)]]] = True
        return int(varies.sum())

    # The configurations this run chooses among.
    def grid(self) -> tuple[Mapping[str, Any], ...]:
        """Return the grid: the settings' or the registered SEQ_GRID."""
        grid = self.settings.grid if self.settings.grid is not None else io.SEQ_GRID
        return tuple(grid)

    # The fold's scaling, from its fit part only: channel median and IQR over
    # the tensor's valid cells up to the last fit session, the daily columns'
    # robust z, and the T-I label winsorization and scale.
    def prepare(
        self, fold: io.Fold, sessions: np.ndarray, fit: np.ndarray, device: Any
    ) -> _SeqState:
        """Return the fold's state."""
        cutoff = sessions[fold.fit_end - 1]
        median, scale = channel_stats(self.seq, self.valid, self.sessions, cutoff)
        d_median, d_scale = robust_stats(self.daily[fit])
        targets, record = scaled_targets(self.kind, self.units.targets, fit)
        return _SeqState(
            median=torch.as_tensor(median, dtype=torch.float32, device=device),
            scale=torch.as_tensor(scale, dtype=torch.float32, device=device),
            daily=daily_inputs(self.daily, d_median, d_scale),
            targets=np.asarray(targets, dtype=np.float32),
            y_scale=float(record["y_scale"]),
            record={
                **record,
                "channel_cutoff": str(cutoff),
                "channel_median": median.tolist(),
                "channel_iqr": scale.tolist(),
            },
        )

    # A batch of units on the device: the robust-z windows (padded and
    # invalid sessions zero) as (B, L, C), the daily inputs, the step
    # validity attention reads, and the training targets.
    def batch(
        self, state: _SeqState, idx: np.ndarray, device: Any
    ) -> tuple[tuple[Any, Any, Any], Any]:
        """Return ((windows, daily, step validity), targets) for units `idx`."""
        if not self.usable[idx].all():
            raise ValueError("a batch asked for a unit with no window in the tensor")
        windows, ok = window_arrays(
            self.seq, self.valid, self.name[idx], self.end[idx], self.window
        )
        x = torch.from_numpy(windows).to(device).float()
        ok_t = torch.from_numpy(ok).to(device)
        x = torch.nan_to_num((x - state.median) / state.scale, nan=0.0)
        x = x.clamp(-io.NET_CLIP, io.NET_CLIP) * ok_t[:, :, None, None]
        count = len(idx)
        steps = ok_t[:, :, None].expand(-1, -1, io.STEPS_PER_SESSION).reshape(count, -1)
        daily = torch.from_numpy(state.daily[idx]).to(device)
        targets = torch.from_numpy(state.targets[idx]).to(device)
        return (x.reshape(count, -1, x.shape[-1]), daily, steps), targets

    # The network's raw (B, K) outputs.
    def forward(self, model: Any, inputs: tuple[Any, Any, Any]) -> Any:
        """Return the network's outputs for a batch."""
        return model(*inputs)

    # Squared error summed over the finite targets, and how many there were.
    def loss(self, raw: Any, targets: Any) -> tuple[Any, Any]:
        """Return (sum of squared errors, count of finite targets)."""
        mask = torch.isfinite(targets)
        error = raw - torch.nan_to_num(targets)
        error = torch.where(mask, error, torch.zeros_like(error))
        return (error**2).sum(), mask.sum()

    # Outputs in the question's units: bp for T-I, rank-Gauss for T-S1.
    def forecast(self, state: _SeqState, raw: Any) -> Any:
        """Return the forecasts of raw outputs."""
        return raw * state.y_scale

    # The network of one configuration.
    def build(self, config: Mapping[str, Any]) -> Any:
        """Return an untrained SeqNet for `config`."""
        return SeqNet(
            self.kind,
            len(io.SEQ_CHANNELS),
            2 * len(self.columns),
            int(config["width"]),
            float(config["dropout"]),
        )

    # AdamW at the configuration's rate under the registered fixed settings.
    def plan(self, config: Mapping[str, Any]) -> TrainPlan:
        """Return how a configuration trains."""
        batch = _pick(self.settings.batch, io.SEQ_FIXED["batch"])
        return TrainPlan(
            optimizer=str(io.SEQ_FIXED["optimizer"]),
            lr=float(config["lr"]),
            weight_decay=float(io.SEQ_FIXED["weight_decay"]),
            clip=float(io.SEQ_FIXED["clip"]),
            warmup_share=float(io.SEQ_FIXED["warmup_share"]),
            max_epochs=_pick(self.settings.max_epochs, io.SEQ_FIXED["max_epochs"]),
            patience=_pick(self.settings.patience, io.SEQ_FIXED["patience"]),
            batch=batch,
            eval_batch=batch,
        )

    # The choices the plan left open, as the forecast's meta records them.
    def architecture(self) -> dict[str, Any]:
        """Return the M3 architecture record."""
        ti = self.kind == io.TI
        return {
            "input": (
                "Linear(12 -> W) + learned step-type embedding (27 x W)"
                " + session-position embedding (K, W)"
            ),
            "session_position_embedding": {
                "shape": [self.window, "W"],
                "description": "session-position embedding (K, W): row p added to"
                " every step of the window's session p (0 oldest, K - 1 the row's"
                " own session), padded and invalid sessions included",
                "init": "N(0, 0.02^2)",
                "registered": "pre-run amendment of the plan, 2026-09-29",
            },
            "tcn": (
                "5 residual blocks x + dropout(GELU(causal conv(LayerNorm(x)))), "
                "kernel 3, dilations 1-2-4-8-16, zero left padding, then LayerNorm"
            ),
            "receptive_field": 1
            + (int(io.SEQ_FIXED["kernel"]) - 1) * sum(io.SEQ_FIXED["dilations"]),
            "activation": ACTIVATION,
            "daily_branch": "Linear(2F -> W), GELU, dropout, Linear(W -> W), GELU",
            "head": "Linear(in -> W), GELU, dropout, Linear(W -> 1)",
            "head_input": "[step, daily]" if ti else "[pooled, last, daily]",
            "pooling": None
            if ti
            else "softmax((K h_t) . q / sqrt(W)) over valid steps; values h_t",
            "window_sessions": self.window,
            "ti_first_output_step": TI_FIRST_OUTPUT if ti else None,
            "channel_scaling": "robust z (median, IQR) per channel, clip 5, NaN -> 0",
            "daily_scaling": "robust z (median, IQR), clip 5, NaN -> 0, + indicators",
            "target": "winsorized / std of winsorized fit labels"
            if ti
            else "rank-Gauss label as is",
            "loss": "masked MSE",
            "optimizer": "AdamW, torch default betas/eps, decay on every parameter",
            "schedule": "linear warm-up over 5% of planned steps, cosine to 0",
            "precision": "fp32",
            "init": "torch defaults; step, session-position and query N(0, 0.02^2)",
        }


@dataclass(frozen=True)
class _ChartState:
    """M2 needs no per-fold scaling: every image is scaled to its own window."""

    record: dict[str, Any]


class _ChartTask:
    """M2 on T-S1: pre-rendered images, the above-median label, cross-entropy."""

    kind = io.S1
    keeps_configs = False

    # Render every row's image once and label each row against its date.
    def __init__(
        self,
        data: io.Stage3Data,
        bars: io.DailyOHLCV,
        family: str,
        settings: Settings,
    ) -> None:
        if data.kind != io.S1:
            raise ValueError(f"the chart CNN answers T-S1 only, not {data.kind!r}")
        if "r" not in data.extra:
            raise ValueError("the chart CNN's label needs extra['r'] (relative return)")
        self.family = family
        self.settings = settings
        self.images, has_image, self.counts = chart_images(
            bars, data.dates, data.tickers, family
        )
        labels = above_median(data.extra["r"], data.dates)
        self.units = Units(
            first=np.arange(len(data)),
            rows=np.arange(len(data))[:, None],
            targets=labels[:, None],
            of_row=np.arange(len(data)),
        )
        self.targets = labels[:, None].astype(np.float32)
        self.usable = has_image
        self.labelled = np.isfinite(labels)
        self.counts = {
            **self.counts,
            "rows_without_window": int((~has_image).sum()),
            "rows_unlabelled": int((~self.labelled).sum()),
        }

    # The single configuration: Adam's registered rate unless a test replaces it.
    def grid(self) -> tuple[Mapping[str, Any], ...]:
        """Return the one-configuration grid."""
        if self.settings.grid is not None:
            return tuple(self.settings.grid)
        return ({"lr": float(io.CNN_FIXED["lr"])},)

    # Nothing is fitted per fold.
    def prepare(
        self, fold: io.Fold, sessions: np.ndarray, fit: np.ndarray, device: Any
    ) -> _ChartState:
        """Return the (empty) fold state."""
        return _ChartState(record={})

    # A batch of images on the device as (B, 1, H, W) pixels in [0, 1], with
    # the 0/1 labels.
    def batch(
        self, state: _ChartState, idx: np.ndarray, device: Any
    ) -> tuple[Any, Any]:
        """Return ((images,), labels) for rows `idx`."""
        images = torch.from_numpy(self.images[idx]).to(device).float() / PIXEL
        targets = torch.from_numpy(self.targets[idx]).to(device)
        return (images[:, None],), targets

    # The (B, 2) class logits.
    def forward(self, model: Any, inputs: tuple[Any]) -> Any:
        """Return the network's logits for a batch."""
        return model(inputs[0])

    # Cross-entropy summed over the labelled images, and how many there were.
    def loss(self, raw: Any, targets: Any) -> tuple[Any, Any]:
        """Return (summed cross-entropy, count of labelled images)."""
        label = targets[:, 0]
        mask = torch.isfinite(label)
        entropy = nn.functional.cross_entropy(
            raw, torch.nan_to_num(label).long(), reduction="none"
        )
        return (entropy * mask).sum(), mask.sum()

    # P(class 1): the probability the row's return is above its date's median.
    def forecast(self, state: _ChartState, raw: Any) -> Any:
        """Return (B, 1) probabilities of class 1."""
        return torch.softmax(raw, dim=1)[:, 1:2]

    # The published network for this image size.
    def build(self, config: Mapping[str, Any]) -> Any:
        """Return an untrained JKXNet."""
        return JKXNet(self.family)

    # Adam at 1e-5 (or a test's rate), batch 128, patience 2, at most 100 epochs.
    def plan(self, config: Mapping[str, Any]) -> TrainPlan:
        """Return how the CNN trains."""
        return TrainPlan(
            optimizer=str(io.CNN_FIXED["optimizer"]),
            lr=float(config.get("lr", io.CNN_FIXED["lr"])),
            weight_decay=0.0,
            clip=None,
            warmup_share=None,
            max_epochs=_pick(self.settings.max_epochs, io.CNN_FIXED["max_epochs"]),
            patience=_pick(self.settings.patience, io.CNN_FIXED["patience"]),
            batch=_pick(self.settings.batch, io.CNN_FIXED["batch"]),
            eval_batch=CNN_EVAL_BATCH,
        )

    # The published choices and the ones made here.
    def architecture(self) -> dict[str, Any]:
        """Return the M2 architecture record."""
        days, height, width = io.CNN_IMAGES[self.family]
        price, gap, volume = CHART_ROWS[self.family]
        return {
            "image": {"days": days, "height": height, "width": width},
            "rows": {"price": price, "gap": gap, "volume": volume},
            "blocks": "(5x3 conv, batch norm, LeakyReLU 0.01, 2x1 max-pool)",
            "channels": list(JKX_CHANNELS[self.family]),
            "first_conv": {k: list(v) for k, v in JKX_FIRST[self.family].items()},
            "other_convs": {k: list(v) for k, v in JKX_SAME.items()},
            "flattened": jkx_flattened_size(self.family),
            "head": "Flatten, Dropout 0.5, Linear(flattened -> 2)",
            "init": "Xavier-uniform conv and linear weights, zero biases",
            "input": "pixels 0/1",
            "moving_average": "one middle-column pixel, omitted where undefined",
            "price_scale": "window max/min of open, high, low, close and MA",
            "loss": "2-class cross-entropy",
            "optimizer": "Adam, torch default betas/eps, no decay, no clipping",
            "precision": "fp32",
        }


# A setting's value, or the registered default when the setting is None.
def _pick(value: int | None, default: Any) -> int:
    return int(default) if value is None else int(value)


# ---------------------------------------------------------------------------
# The walk-forward
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Outputs:
    """The forecast arrays a walk-forward fills, in the dataset's row order."""

    seeds: np.ndarray  # (R, seeds)
    configs: np.ndarray | None  # (R, grid) or None
    fold: np.ndarray  # (R,)

    # Write one fold's test forecasts: each seed's, and each configuration's
    # first-seed forecast when they are kept.
    def write(
        self,
        rows: np.ndarray,
        number: int,
        per_seed: list[np.ndarray],
        per_config: list[np.ndarray],
    ) -> None:
        """Store the (n, K) forecasts of the units whose outputs are `rows`."""
        keep = rows >= 0
        target = rows[keep]
        for j, forecast in enumerate(per_seed):
            self.seeds[target, j] = forecast[keep]
        if self.configs is not None:
            for c, forecast in enumerate(per_config):
                self.configs[target, c] = forecast[keep]
        self.fold[target] = number


# Call the progress callback when there is one.
def _say(log: Callable[[str], None] | None, text: str) -> None:
    if log is not None:
        log(text)


# The index of the best validation score; NaN never beats a number, ties go
# to the earlier configuration, and with no finite score the first is taken.
def _choose(scores: list[float]) -> int:
    ranked = [s if s is not None and math.isfinite(s) else -math.inf for s in scores]
    return int(np.argmax(ranked))


# The plan's selection score of forecasts for some units against the raw
# labels of their rows (pooled Spearman for T-I, mean daily IC for T-S1).
def _score(
    task: Any, data: io.Stage3Data, units: np.ndarray, forecast: np.ndarray
) -> float:
    rows = task.units.rows[units]
    keep = rows >= 0
    target = rows[keep]
    return io.selection_score(
        task.kind,
        forecast[keep],
        np.asarray(data.y, dtype=np.float64)[target],
        data.dates[target],
    )


# The fit, validation and test units of a fold: fit and validation need a
# window and a label; the test block is every unit with a window.
def _split(
    task: Any, unit_session: np.ndarray, fold: io.Fold
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    labelled = task.usable & task.labelled
    fit = np.flatnonzero(labelled & (unit_session < fold.fit_end))
    val = np.flatnonzero(
        labelled & (unit_session >= fold.val_start) & (unit_session < fold.window_end)
    )
    test = np.flatnonzero(
        task.usable & (unit_session >= fold.test_start) & (unit_session < fold.test_end)
    )
    return fit, val, test


# One configuration's line of progress.
def _config_line(prefix: str, config: Mapping[str, Any], record: dict[str, Any]) -> str:
    score = record.get("score")
    shown = f"{score:+.4f}" if score is not None and math.isfinite(score) else "nan"
    return (
        f"{prefix} {_describe(config)} seed {record['seed']}: {record['epochs']} epochs"
        f" (best {record['best_epoch']}), val loss {record['val_loss']:.5f},"
        f" score {shown}, {record['seconds']:.0f} s"
    )


# A configuration as "lr=0.001 dropout=0.1 width=64".
def _describe(config: Mapping[str, Any]) -> str:
    return " ".join(f"{key}={value}" for key, value in config.items())


# One fold: every configuration with the first seed, the best by validation
# score, the other seeds with it; each network's test forecasts go to `out`.
# Returns the fold's record.
def _fold(
    task: Any,
    data: io.Stage3Data,
    fold: io.Fold,
    position: tuple[int, int],
    sessions: np.ndarray,
    unit_session: np.ndarray,
    seeds: tuple[int, ...],
    device: Any,
    out: _Outputs,
    log: Callable[[str], None] | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    number, folds_n = position
    grid = task.grid()
    fit, val, test = _split(task, unit_session, fold)
    if not len(fit) or not len(val):
        raise ValueError(
            f"fold {number}: {len(fit)} fit and {len(val)} validation units; "
            "the walk-forward needs both"
        )
    state = task.prepare(fold, sessions, fit, device)
    eval_batch = task.plan(grid[0]).eval_batch
    tag = f"  fold {number + 1}/{folds_n}"
    configs: list[dict[str, Any]] = []
    per_config: list[np.ndarray] = []
    for c, config in enumerate(grid):
        model, record = _train(task, state, config, seeds[0], fit, val, device)
        forecast = _predict(task, state, model, val, eval_batch, device)
        record["score"] = _score(task, data, val, forecast)
        per_config.append(_predict(task, state, model, test, eval_batch, device))
        configs.append({"config": dict(config), **record})
        _say(log, _config_line(f"{tag} config {c + 1}/{len(grid)}", config, record))
    chosen = _choose([r["score"] for r in configs])
    per_seed = [per_config[chosen]]
    seed_runs = [configs[chosen]]
    for seed in seeds[1:]:
        model, record = _train(task, state, grid[chosen], seed, fit, val, device)
        per_seed.append(_predict(task, state, model, test, eval_batch, device))
        seed_runs.append({"config": dict(grid[chosen]), **record})
        _say(log, _config_line(f"{tag} chosen", grid[chosen], record))
    out.write(task.units.rows[test], number, per_seed, per_config)
    rows = task.units.rows
    record = {
        "fold": number,
        "sessions": {
            "fit": [0, fold.fit_end],
            "validation": [fold.val_start, fold.window_end],
            "test": [fold.test_start, fold.test_end],
        },
        "dates": {
            "fit_end": str(sessions[fold.fit_end - 1]),
            "validation": [
                str(sessions[fold.val_start]),
                str(sessions[fold.window_end - 1]),
            ],
            "test": [str(sessions[fold.test_start]), str(sessions[fold.test_end - 1])],
        },
        "units": {"fit": len(fit), "validation": len(val), "test": len(test)},
        "rows": {
            "fit": int(np.isfinite(task.units.targets[fit]).sum()),
            "validation": int(np.isfinite(task.units.targets[val]).sum()),
            "test": int((rows[test] >= 0).sum()),
        },
        "scaling": state.record,
        "configs": configs,
        "chosen": chosen,
        "chosen_config": dict(grid[chosen]),
        "seeds": [
            {k: r[k] for k in ("seed", "epochs", "best_epoch", "val_loss", "seconds")}
            for r in seed_runs
        ],
        "seconds": time.perf_counter() - started,
    }
    shown = configs[chosen]["score"]
    _say(
        log,
        f"fold {number + 1}/{folds_n}: test {record['dates']['test'][0]}.."
        f"{record['dates']['test'][1]} ({record['rows']['test']:,} rows), fit"
        f" {len(fit):,} / validation {len(val):,} units; chose #{chosen + 1}"
        f" {_describe(grid[chosen])} (score {shown:+.4f}), {len(seeds)} seeds,"
        f" {record['seconds']:.0f} s",
    )
    return record


# Make a meta value JSON-safe: numpy scalars and arrays to python, NaN to None.
def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, np.ndarray):
        return _json_ready(value.tolist())
    if isinstance(value, np.bool_ | bool):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


# Walk a task forward over the registered folds and assemble the forecast.
def _walk_forward(
    task: Any,
    data: io.Stage3Data,
    settings: Settings,
    log: Callable[[str], None] | None,
) -> io.Stage3Forecast:
    started = time.perf_counter()
    device = torch.device(resolve_device(settings.device))
    sessions, index = io.session_index(data.dates)
    refit = _pick(settings.refit, io.REFIT[(task.family, task.kind)])
    gap = _pick(settings.gap, io.GAP[task.kind])
    planned = io.folds(
        len(sessions), refit, gap, settings.min_train, settings.validation
    )
    walk = planned if settings.max_folds is None else planned[: settings.max_folds]
    seeds = tuple(int(s) for s in settings.seeds)
    grid = task.grid()
    rows_n = len(data)
    out = _Outputs(
        seeds=np.full((rows_n, len(seeds)), np.nan),
        configs=np.full((rows_n, len(grid)), np.nan) if task.keeps_configs else None,
        fold=np.full(rows_n, -1, dtype=np.int64),
    )
    unit_session = index[task.units.first]
    records = []
    with deterministic_torch():
        for number, fold in enumerate(walk):
            records.append(
                _fold(
                    task,
                    data,
                    fold,
                    (number, len(walk)),
                    sessions,
                    unit_session,
                    seeds,
                    device,
                    out,
                    log,
                )
            )
    yhat = out.seeds.mean(axis=1)
    plan_record = task.plan(grid[0])
    meta = {
        "module": MODULE,
        "family": task.family,
        "kind": task.kind,
        "registered": settings.registered(),
        "settings": {
            "grid": [dict(g) for g in grid],
            "seeds": list(seeds),
            "min_train": settings.min_train,
            "validation": settings.validation,
            "refit": refit,
            "gap": gap,
            "max_epochs": plan_record.max_epochs,
            "patience": plan_record.patience,
            "batch": plan_record.batch,
            "max_folds": settings.max_folds,
            "folds_planned": len(planned),
            "folds_run": len(walk),
            "device": str(device),
        },
        "architecture": task.architecture(),
        "inputs": task.counts,
        "determinism": {
            "use_deterministic_algorithms": True,
            "cudnn_benchmark": False,
            "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
            "torch": torch.__version__,
            "threads": torch.get_num_threads(),
        },
        "folds": records,
        "rows_forecast": int(np.isfinite(yhat).sum()),
        "seconds": time.perf_counter() - started,
    }
    return io.Stage3Forecast(
        kind=task.kind,
        family=task.family,
        dates=np.asarray(data.dates, dtype="datetime64[D]"),
        tickers=np.asarray(data.tickers),
        slot=np.asarray(data.slot, dtype=np.int8),
        yhat=yhat.astype(np.float32),
        yhat_seeds=out.seeds.astype(np.float32),
        yhat_configs=None if out.configs is None else out.configs.astype(np.float32),
        fold=out.fold,
        meta=_json_ready(meta),
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


# M3 on the dataset's question: the sequence model walked forward over
# `data` with windows from `tensor`; the forecast keeps the row order.
def run_seq(
    data: io.Stage3Data,
    tensor: io.SeqTensor,
    settings: Settings | None = None,
    log: Callable[[str], None] | None = None,
) -> io.Stage3Forecast:
    """Return the sequence model's out-of-sample forecast for `data`."""
    _require_torch()
    settings = settings or Settings()
    io.validate(data)
    return _walk_forward(_SeqTask(data, tensor, settings), data, settings, log)


# M2 on T-S1: the chart CNN of `family` walked forward over `data` with
# images drawn from `bars`; the forecast keeps the row order.
def run_cnn(
    data: io.Stage3Data,
    bars: io.DailyOHLCV,
    family: str,
    settings: Settings | None = None,
    log: Callable[[str], None] | None = None,
) -> io.Stage3Forecast:
    """Return the chart CNN's out-of-sample forecast for `data`."""
    _require_torch()
    if family not in (io.CNN_I5, io.CNN_I20):
        raise ValueError(f"family must be {io.CNN_I5} or {io.CNN_I20}, not {family!r}")
    settings = settings or Settings()
    io.validate(data)
    task = _ChartTask(data, bars, family, settings)
    return _walk_forward(task, data, settings, log)


# Run the family a caller names on its inputs: the command line's entry.
def run(
    family: str,
    data: io.Stage3Data,
    *,
    seq: io.SeqTensor | None = None,
    ohlcv: io.DailyOHLCV | None = None,
    settings: Settings | None = None,
    log: Callable[[str], None] | None = None,
) -> io.Stage3Forecast:
    """Return `family`'s forecast for `data` (``seq`` needs `seq`, a CNN `ohlcv`)."""
    if family not in QUESTIONS:
        raise ValueError(f"family must be one of {tuple(QUESTIONS)}, not {family!r}")
    if data.kind not in QUESTIONS[family]:
        raise ValueError(f"{family} does not answer {data.kind!r}")
    if family == io.SEQ:
        if seq is None:
            raise ValueError("the sequence model needs a SeqTensor")
        return run_seq(data, seq, settings, log)
    if ohlcv is None:
        raise ValueError(f"{family} needs the daily bars (DailyOHLCV)")
    return run_cnn(data, ohlcv, family, settings, log)
