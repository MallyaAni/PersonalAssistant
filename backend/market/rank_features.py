"""Point-in-time daily-bar features and forward labels for the ML ranker.

This is the first, foundational component of the step-2 experimental ML
ranker: it turns one as-of snapshot of daily bars
(``data/market/bars/asof=<DATE>/<TICKER>.parquet``) into a rectangular
feature matrix plus a validity mask, and pairs that snapshot with a later one
to produce the zero-cost next-open forward labels. It deliberately does no
training, ranking, exposure or evaluation - those belong to other agents.

Conventions
-----------
* Every feature at decision session D is computed strictly from rows <= D in
  that snapshot (no lookahead), using that ticker's OWN session sequence: a
  window of k sessions ending at D is the ticker's last k rows up to and
  including D. Windows are never counted across a date the ticker did not
  trade, so an equity holiday (where a futures/currency ticker like CL=F or
  DX-Y.NYB still has a bar and therefore appears in the shared grid) never
  corrupts an equity's momentum or volatility window.
* All momentum/volatility/SMA/RSI/ATR/drawdown features use ``adjusted_close``
  so a split never moves a feature; ``volume_z_21`` uses ``volume``; ``atr_21``
  additionally uses ``high`` and ``low``. Realised volatility is a population
  standard deviation (ddof=0), the same convention as the desk's fixed-level
  code.
* A row is ``valid`` only when every feature is finite. Non-positive or
  non-finite prices and volumes (for example the negative oil print in CL=F
  during 2020) are treated as missing and make the affected rows invalid.
* The forward label is the zero-cost next-open convention: for decision
  session D the label is ``close[D+horizon] / open[D+1] - 1``, buying at the
  session after D's open and selling at D+horizon's close. Decisions are the
  ticker's own sessions in ``snapshot``; both the buy open and the sell close
  are read from ``next_snapshot`` (the ticker's own later calendar) so the
  numerator and the denominator share one price basis, and a split between
  the two snapshots cannot distort the label.

Caveat - restatement and survivorship bias
------------------------------------------
Each as-of snapshot is a current re-statement of history. The bars inside it
are adjusted to that snapshot's date (splits everywhere, dividends in
``adjusted_close``), so a historical row is not the price actually published
on that day, and the snapshot's universe is what is tradeable now, not what
existed then. Features and forward labels computed from these rows are
therefore NOT the originally-published values, and any evaluation built on
them inherits this restatement and survivorship bias.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

# The feature columns, in exactly this order (semantics in parentheses; all
# computed from close/adjusted_close/volume up to and including session D).
FEATURE_COLUMNS = [
    "momentum_5",  # close[D]/close[D-5] - 1
    "momentum_10",  # close[D]/close[D-10] - 1
    "momentum_21",  # close[D]/close[D-21] - 1
    "momentum_63",  # close[D]/close[D-63] - 1
    "vol_21",  # std of daily simple returns over the 21 sessions ending D
    "vol_63",  # std over 63 sessions ending D
    "ma_dist_21",  # close[D]/SMA21[D] - 1
    "ma_dist_63",  # close[D]/SMA63[D] - 1
    "rsi_14",  # Wilder RSI-14 at D, in [0,100]
    "volume_z_21",  # (volume[D] - mean(vol, 21d ending D)) / std(vol, 21d ending D)
    "drawdown_63",  # close[D]/max(close, 63d ending D) - 1  (<= 0)
    "atr_21",  # average true range over 21 sessions ending D, divided by close[D]
]

# The as-of daily-bar store, resolved from this module's location so it works
# regardless of the working directory (repo root, or /app inside a container).
BARS_ROOT = Path(__file__).resolve().parents[2] / "data" / "market" / "bars"


@dataclass(frozen=True)
class Snapshot:
    """One aligned as-of snapshot: a shared date grid and per-ticker arrays.

    ``dates`` is the sorted unique union of session dates across the tickers
    (T,), ``tickers`` the sorted ticker names (N,), and each of
    ``open/high/low/close/adjusted_close/volume`` is a (T, N) float64 array
    with NaN where a ticker has no row that day. ``asof`` is the snapshot's
    date as an ISO string.
    """

    asof: str
    dates: np.ndarray
    tickers: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    adjusted_close: np.ndarray
    volume: np.ndarray


def _read_ticker_file(
    path: Path, asof_date: str, asof_dt: np.datetime64
) -> tuple[np.ndarray, tuple[np.ndarray, ...]]:
    """Load and validate one ticker's parquet file, returning sorted dates and bars."""
    table = pq.read_table(path)
    meta = table.schema.metadata or {}
    if meta.get(b"asof", b"").decode() != asof_date:
        raise ValueError(
            f"{path.name}: metadata asof {meta.get(b'asof', b'')!r} "
            f"does not match {asof_date}"
        )
    for col in (
        "session_date",
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
    ):
        if col not in table.column_names:
            raise ValueError(f"{path.name}: missing required column {col!r}")
    dates = np.asarray(
        table.column("session_date").to_numpy(zero_copy_only=False),
        dtype="datetime64[D]",
    )
    if dates.size == 0:
        raise ValueError(f"{path.name}: no rows")
    order = np.argsort(dates, kind="stable")
    dates = dates[order]
    if np.unique(dates).size != dates.size:
        raise ValueError(f"{path.name}: duplicate session dates")
    if dates[-1] > asof_dt:
        raise ValueError(
            f"{path.name}: session date {dates[-1]} is after the snapshot's "
            f"as-of date {asof_date}"
        )
    arrays = tuple(
        np.asarray(table.column(col).to_numpy(zero_copy_only=False)[order], dtype=float)
        for col in ("open", "high", "low", "close", "adjusted_close", "volume")
    )
    return dates, arrays


def load_snapshot(asof_date: str, root: str | Path = BARS_ROOT) -> Snapshot:
    """Load and validate one as-of snapshot into an aligned Snapshot.

    Reads every ``asof=<asof_date>/<TICKER>.parquet`` under ``root``. Each
    file's metadata ``asof`` must equal ``asof_date`` and every row's
    ``session_date`` must be at or before ``asof_date`` (no future data);
    rows are sorted within a file and duplicate dates are rejected. Each
    ticker's open/high/low/close/adjusted_close/volume is then aligned onto
    the sorted unique union of session dates with NaN where a ticker has no
    row that day. Tickers with different row sets and files in any order are
    handled; the result is deterministic.
    """
    snap_dir = Path(root) / f"asof={asof_date}"
    if not snap_dir.is_dir():
        raise FileNotFoundError(f"no as-of snapshot directory at {snap_dir}")
    files = sorted(snap_dir.glob("*.parquet"))
    if not files:
        raise ValueError(f"no parquet files in {snap_dir}")
    asof_dt = np.datetime64(asof_date, "D")
    per_ticker: dict[str, tuple[np.ndarray, ...]] = {}
    for path in files:
        dates, arrays = _read_ticker_file(path, asof_date, asof_dt)
        per_ticker[path.stem] = (dates, *arrays)
    tickers = sorted(per_ticker)
    grid = np.unique(np.concatenate([per_ticker[t][0] for t in tickers]))
    columns = ("open", "high", "low", "close", "adjusted_close", "volume")
    aligned = {name: np.full((len(grid), len(tickers)), np.nan) for name in columns}
    for j, ticker in enumerate(tickers):
        dates_i = per_ticker[ticker][0]
        pos = np.searchsorted(grid, dates_i)
        if not np.array_equal(grid[pos], dates_i):
            raise RuntimeError("internal grid alignment failure")
        for name, values in zip(columns, per_ticker[ticker][1:], strict=True):
            aligned[name][pos, j] = values
    return Snapshot(
        asof=asof_date,
        dates=grid,
        tickers=tickers,
        open=aligned["open"],
        high=aligned["high"],
        low=aligned["low"],
        close=aligned["close"],
        adjusted_close=aligned["adjusted_close"],
        volume=aligned["volume"],
    )


def feature_matrix(
    snapshot: Snapshot,
) -> tuple[np.ndarray, list[str], np.ndarray, np.ndarray]:
    """Return (dates, tickers, X, valid) for the whole cross-section.

    ``dates`` is the (T,) grid, ``tickers`` the (N,) sorted list, ``X`` is
    (T*N, len(FEATURE_COLUMNS)) in FEATURE_COLUMNS order with row ``i*N + j``
    holding (dates[i], tickers[j])'s features computed strictly from rows <=
    that date, and ``valid`` is a (T*N,) bool that is True exactly where every
    feature is finite. Invalid rows may carry NaN in ``X``.
    """
    t_count, n_count = snapshot.open.shape
    out = np.full((t_count * n_count, len(FEATURE_COLUMNS)), np.nan, dtype=float)
    for j in range(n_count):
        out[j::n_count, :] = _ticker_features(snapshot, j)
    valid = np.isfinite(out).all(axis=1)
    return snapshot.dates, list(snapshot.tickers), out, valid


def forward_labels(
    snapshot: Snapshot, horizon: int, next_snapshot: Snapshot
) -> np.ndarray:
    """Return the (T*N,) next-open forward label aligned to feature_matrix rows.

    The label for a decision session D of ``snapshot`` is
    ``close[D+horizon] / open[D+1] - 1`` (buy at the session after D's open,
    sell at D+horizon's close). Decisions are the ticker's own sessions in
    ``snapshot``; D+1 and D+horizon are counted in the ticker's own calendar
    and both prices are read from ``next_snapshot``, so the numerator and
    denominator share one price basis. The label is NaN where the next open or
    the future close is missing, where D+1 or D+horizon lies beyond
    ``next_snapshot``'s coverage for that ticker, or where the ticker is
    absent from ``next_snapshot``. ``horizon`` counts sessions and must be
    >= 1; ``next_snapshot`` must be an as-of snapshot no earlier than
    ``snapshot``.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if next_snapshot.asof < snapshot.asof:
        raise ValueError(
            "next_snapshot must be an as-of snapshot no earlier than snapshot"
        )
    t_count, n_count = snapshot.open.shape
    out = np.full(t_count * n_count, np.nan, dtype=float)
    next_tick = {t: k for k, t in enumerate(next_snapshot.tickers)}
    for j in range(n_count):
        nk = next_tick.get(snapshot.tickers[j])
        if nk is None:
            continue
        # The ticker's own decision sessions (grid positions where it has a row).
        dec_pos = np.flatnonzero(np.isfinite(snapshot.close[:, j]))
        if dec_pos.size < 1:
            continue
        # The ticker's own later calendar inside next_snapshot.
        n_own = np.flatnonzero(np.isfinite(next_snapshot.close[:, nk]))
        if n_own.size < 2:
            continue
        n_dates = next_snapshot.dates[n_own]
        # Index of each decision date in next_snapshot's own calendar.
        r = np.searchsorted(n_dates, snapshot.dates[dec_pos])
        hit = (r < n_own.size) & (
            n_dates[np.clip(r, 0, n_own.size - 1)] == snapshot.dates[dec_pos]
        )
        r = np.where(hit, r, -1)
        # Buy at the next session's open, sell at the D+horizon session's close.
        ok_next = (r >= 0) & (r + 1 < n_own.size)
        buy_open = np.where(
            ok_next,
            _masked(next_snapshot.open[n_own[np.clip(r + 1, 0, n_own.size - 1)], nk]),
            np.nan,
        )
        ok_future = (r >= 0) & (r + horizon < n_own.size)
        sell_close = np.where(
            ok_future,
            _masked(
                next_snapshot.close[n_own[np.clip(r + horizon, 0, n_own.size - 1)], nk]
            ),
            np.nan,
        )
        label = sell_close / buy_open - 1.0
        label = np.where(np.isfinite(label), label, np.nan)
        out[j::n_count][dec_pos] = label
    return out


def _masked(series: np.ndarray) -> np.ndarray:
    """Return a float copy with non-finite and non-positive values set to NaN."""
    arr = np.asarray(series, dtype=float)
    return np.where(np.isfinite(arr) & (arr > 0.0), arr, np.nan)


def _returns(p: np.ndarray) -> np.ndarray:
    """Return daily simple returns p[t]/p[t-1] - 1.

    NaN at t=0 and where p is missing.
    """
    n = len(p)
    out = np.full(n, np.nan)
    if n >= 2:
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = p[1:] / p[:-1]
        out[1:] = np.where(np.isfinite(ratio), ratio, np.nan) - 1.0
    return out


def _rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    """Return the mean of the trailing `window` values ending at each position.

    NaN where the window is incomplete or holds a missing value.
    """
    n = len(x)
    out = np.full(n, np.nan)
    if n < window:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(x, window)
    out[window - 1 :] = np.mean(windows, axis=1)
    return out


def _rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    """Return the population std of the trailing `window` values at each position.

    NaN where the window is incomplete or holds a missing value.
    """
    n = len(x)
    out = np.full(n, np.nan)
    if n < window:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(x, window)
    out[window - 1 :] = np.std(windows, axis=1)
    return out


def _momentum(p: np.ndarray, k: int) -> np.ndarray:
    """Return p[t]/p[t-k] - 1, NaN where either endpoint is missing."""
    n = len(p)
    out = np.full(n, np.nan)
    if n <= k:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = p[k:] / p[:-k]
    out[k:] = np.where(np.isfinite(ratio), ratio, np.nan) - 1.0
    return out


def _ma_dist(p: np.ndarray, k: int) -> np.ndarray:
    """Return p[t]/SMA_k[t] - 1 with SMA over the trailing k prices ending at t."""
    sma = _rolling_mean(p, k)
    with np.errstate(divide="ignore", invalid="ignore"):
        dist = p / sma - 1.0
    return np.where(np.isfinite(dist), dist, np.nan)


def _volume_z(vol: np.ndarray, k: int) -> np.ndarray:
    """Return the trailing-k volume z-score (v - mean) / std.

    NaN where the window is incomplete or std is zero.
    """
    mean = _rolling_mean(vol, k)
    std = _rolling_std(vol, k)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (vol - mean) / std
    return np.where(np.isfinite(z), z, np.nan)


def _drawdown(p: np.ndarray, k: int) -> np.ndarray:
    """Return p[t]/max(p over the trailing k sessions ending at t) - 1, always <= 0."""
    n = len(p)
    out = np.full(n, np.nan)
    if n < k:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(p, k)
    peak = np.max(windows, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[k - 1 :] = p[k - 1 :] / peak - 1.0
    return np.where(np.isfinite(out), out, np.nan)


def _true_range(
    high: np.ndarray, low: np.ndarray, prior_close: np.ndarray
) -> np.ndarray:
    """Return the true range max(high-low, |high-prior|, |low-prior|) per session.

    NaN where any input is missing.
    """
    n = len(high)
    tr = np.full(n, np.nan)
    if n >= 2:
        tr = np.maximum(
            np.maximum(high - low, np.abs(high - prior_close)),
            np.abs(low - prior_close),
        )
        tr = np.where(np.isfinite(tr), tr, np.nan)
    return tr


def _atr(high: np.ndarray, low: np.ndarray, p: np.ndarray, k: int) -> np.ndarray:
    """Return the average true range over the trailing k sessions, over the close."""
    prior_close = np.empty_like(p)
    prior_close[0] = np.nan
    prior_close[1:] = p[:-1]
    atr = _rolling_mean(_true_range(high, low, prior_close), k)
    with np.errstate(divide="ignore", invalid="ignore"):
        norm = atr / p
    return np.where(np.isfinite(norm), norm, np.nan)


def _wilder_ema(values: np.ndarray, period: int) -> np.ndarray:
    """Return the Wilder-smoothed average of `values`.

    Seed = mean of the first `period`, then (prev*(period-1)+value)/period.
    """
    m = len(values)
    out = np.full(m, np.nan)
    if m < period:
        return out
    acc = float(np.mean(values[:period]))
    out[period - 1] = acc
    for t in range(period, m):
        acc = (acc * (period - 1) + float(values[t])) / period
        out[t] = acc
    return out


def _rsi_from_averages(avg_gain: np.ndarray, avg_loss: np.ndarray) -> np.ndarray:
    """Return RSI = 100*avg_gain/(avg_gain+avg_loss) in [0,100].

    A zero-loss average reads 100, an invalid one stays NaN.
    """
    valid = np.isfinite(avg_gain) & np.isfinite(avg_loss)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.where(valid, 100.0 * avg_gain / (avg_gain + avg_loss), np.nan)
    rsi = np.where(valid & (avg_loss == 0.0), 100.0, rsi)
    return np.clip(rsi, 0.0, 100.0)


def _rsi(p: np.ndarray, period: int = 14) -> np.ndarray:
    """Return Wilder RSI-`period` in [0,100] at each grid position.

    Computed per contiguous finite run so a gap cannot poison later values.
    """
    n = len(p)
    out = np.full(n, np.nan)
    finite = np.isfinite(p)
    if not finite.any():
        return out
    starts = np.flatnonzero(finite & ~np.r_[False, finite[:-1]])
    ends = np.flatnonzero(finite & ~np.r_[finite[1:], False])
    for start, end in zip(starts, ends, strict=True):
        run = np.arange(start, end + 1)
        sub = p[run]
        delta = sub[1:] - sub[:-1]
        avg_gain = _wilder_ema(np.maximum(delta, 0.0), period)
        avg_loss = _wilder_ema(np.maximum(-delta, 0.0), period)
        out[run[1:]] = _rsi_from_averages(avg_gain, avg_loss)
    return out


def _ticker_features(snapshot: Snapshot, j: int) -> np.ndarray:
    """Return the (T, len(FEATURE_COLUMNS)) feature block for ticker column `j`.

    Features are computed on the ticker's own session sequence (its finite
    adjusted closes, in chronological order) so a date the ticker did not
    trade - an equity holiday in the shared grid - never enters a window; the
    result is placed back at the ticker's grid positions, leaving NaN where it
    has no row.
    """
    adj = _masked(snapshot.adjusted_close[:, j])
    own = np.flatnonzero(np.isfinite(adj))
    out = np.full((len(snapshot.dates), len(FEATURE_COLUMNS)), np.nan)
    if own.size < 2:
        return out
    p = adj[own]
    v = _masked(snapshot.volume[:, j])[own]
    h = _masked(snapshot.high[:, j])[own]
    low_ = _masked(snapshot.low[:, j])[own]
    out[own, :] = _features_from_series(p, v, h, low_)
    return out


def _features_from_series(
    p: np.ndarray, v: np.ndarray, h: np.ndarray, low_: np.ndarray
) -> np.ndarray:
    """Return the (m, len(FEATURE_COLUMNS)) feature block for one dense own series."""
    returns = _returns(p)
    return np.column_stack(
        [
            _momentum(p, 5),
            _momentum(p, 10),
            _momentum(p, 21),
            _momentum(p, 63),
            _rolling_std(returns, 21),
            _rolling_std(returns, 63),
            _ma_dist(p, 21),
            _ma_dist(p, 63),
            _rsi(p, 14),
            _volume_z(v, 21),
            _drawdown(p, 63),
            _atr(h, low_, p, 21),
        ]
    )
