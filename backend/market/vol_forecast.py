"""The CNN's next-session volatility forecast as a file, and its alignment to a panel.

Stage 1 of the deep-intraday plan (`docs/research/deep-intraday-stage1-2026-09-27.md`)
found one result a deep model earns: the temporal CNN's volatility head
forecasts the next session's realized variance with out-of-sample R² 0.27
against the trailing 20-session baseline. The registered next trial sizes
the graded equal-weight book with it (`vol_sizing`). This module is the
seam between the two: it runs the stage-1 walk-forward on the volatility
target alone and writes the out-of-sample forecast per (name, session) row
to one npz, and it aligns that file to a price panel so an allocator can
read the forecast at its decision session.

The forecast for dataset row (name, t) is made from bars through the close
of t (`deep_intraday.Dataset`: `x_seq` ends at t, the scalars are t's) and
its target is the realized variance of session t + 1 (`y_vol =
log_realized[idx + 1]` in `deep_intraday._cube_rows`). The simulator's
allocator decides at t's close and its book holds session t + 1, so the
row it may read is the one dated t and no other: `align` puts row (name, t)
at the panel position of date t, and the no-lookahead test asserts that a
one-session shift of the matrix is a different matrix. The baseline column
is the row's `trailing_vol` - the log of the mean realized variance over
the 20 sessions through t - and the optional `realized` column is the
target itself, carried so the sizing trial can measure the control's
realized book volatility on the forecast's own scale once, before the run.
Both forecast and baseline are log realized *variance* (the sum of squared
fifteen-minute bar returns over a session); `sigma` turns either into a
per-session volatility, exp(x / 2).

The walk-forward is `deep_intraday.walk_forward` unchanged (REFIT 63,
MIN_TRAIN 500, PURGE 5, one fixed CNN configuration); nothing is
duplicated here, and the values written are exactly `Forecast.values`, NaN
before the first fit. torch is imported only inside the CNN family, so
this module loads where it is absent and `export_forecasts(model="ridge")`
runs there.

Version 2 exports retain the dataset's declared row-selection convention and
separate finite predictions from predictions with observed labels. Missing old
declarations remain ``legacy-unrecorded``; a declaration is not causal or
historical-provenance qualification, and no saved forecast file is upgraded.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.market import deep_intraday

# The file's arrays, in a fixed order. `realized` is optional on load.
FIELDS = ("ticker", "date", "forecast", "baseline")
OPTIONAL_FIELDS = ("realized",)
# The forecast head this module exports by default.
MODEL = "cnn"
TARGET = "vol"
# New exports declare row selection and distinguish predictions from observed labels.
VERSION = 2


@dataclass(frozen=True)
class Forecasts:
    """Per-row volatility forecasts: one entry per (name, session t)."""

    dates: np.ndarray  # (M,) datetime64[D], the decision session t
    tickers: np.ndarray  # (M,) str
    forecast: np.ndarray  # (M,) log realized variance forecast for t + 1, NaN unscored
    baseline: np.ndarray  # (M,) log trailing mean realized variance through t
    realized: np.ndarray | None = None  # (M,) log realized variance of t + 1
    meta: dict[str, Any] | None = None

    # Rows in the file.
    def __len__(self) -> int:
        return int(len(self.dates))

    # Read declared row selection without upgrading metadata absent from old files.
    @property
    def row_selection(self) -> str:
        if self.meta is None or "row_selection" not in self.meta:
            return deep_intraday.LEGACY_ROW_SELECTION
        return deep_intraday.load_row_selection(
            {"row_selection": np.asarray(self.meta["row_selection"])}
        )


@dataclass(frozen=True)
class Aligned:
    """The forecasts on a panel's (sessions, names) grid; NaN where missing."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    forecast: np.ndarray  # (T, N)
    baseline: np.ndarray  # (T, N)
    realized: np.ndarray | None  # (T, N) or None when the file had none

    # The share of grid cells with a forecast, over the rows given (all when
    # `rows` is None); a coverage number for the payload.
    def coverage(self, rows: np.ndarray | None = None) -> float:
        """Return the fraction of (session, name) cells holding a forecast."""
        f = self.forecast if rows is None else self.forecast[rows]
        return float(np.isfinite(f).mean()) if f.size else float("nan")


# Per-session volatility from a log realized variance: exp(x / 2). NaN
# stays NaN.
def sigma(log_variance: np.ndarray | float) -> np.ndarray:
    """Return exp(log_variance / 2), the volatility the log variance implies."""
    return np.exp(np.asarray(log_variance, dtype=float) / 2.0)


# Run the stage-1 walk-forward on the volatility target only and write the
# out-of-sample forecast per row, with the trailing baseline and the
# realized target beside it, to `out_npz`. `model` is a `deep_intraday`
# model name (the CNN by default; the ridge runs without torch). Returns a
# summary: the rows, the scored rows, the fits and the out-of-sample R²
# against the baseline per window.
# Retain the dataset's row-selection declaration and distinct label coverage.
def export_forecasts(
    dataset_npz: Path,
    out_npz: Path,
    device: str = "auto",
    model: str = MODEL,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Walk `model` forward on the volatility target and write the forecasts."""
    ds, _keep_a = deep_intraday.load_dataset(Path(dataset_npz))
    resolved = deep_intraday.resolve_device(device, deep_intraday.cuda_available())
    if model in deep_intraday.TORCH_MODELS:
        deep_intraday.announce_device(resolved, log)
    began = time.perf_counter()
    forecast = deep_intraday.walk_forward(
        ds, model, TARGET, log=log, device=resolved
    )
    seconds = time.perf_counter() - began
    r2 = {
        name: deep_intraday.vol_r2(
            ds, forecast, deep_intraday.window_rows(ds, start, end)
        )
        for name, (start, end) in deep_intraday.WINDOWS.items()
    }
    finite = np.isfinite(forecast.values)
    observed = np.isfinite(ds.y_vol)
    meta = {
        "version": VERSION,
        "row_selection": ds.row_selection,
        "model": model,
        "target": TARGET,
        "device": resolved,
        "dataset": str(dataset_npz),
        "rows": len(ds),
        # Retain the legacy alias; observed-label counts below are distinct.
        "scored_rows": int(finite.sum()),
        "finite_forecast_rows": int(finite.sum()),
        "observed_label_rows": int(observed.sum()),
        "forecast_with_observed_label_rows": int((finite & observed).sum()),
        "forecast_without_observed_label_rows": int((finite & ~observed).sum()),
        "fits": forecast.fits,
        "parameters": forecast.parameters,
        "seconds": seconds,
        "vol_r2": r2,
        "constants": {
            "refit": deep_intraday.REFIT,
            "min_train": deep_intraday.MIN_TRAIN,
            "purge": deep_intraday.PURGE,
            "trailing": deep_intraday.TRAILING,
        },
    }
    save_forecasts(
        Path(out_npz),
        Forecasts(
            dates=ds.dates,
            tickers=ds.tickers,
            forecast=forecast.values,
            baseline=ds.trailing_vol,
            realized=ds.y_vol,
            meta=meta,
        ),
    )
    if log is not None:
        scored = meta["scored_rows"]
        log(
            f"wrote {out_npz}: {len(ds):,} rows, {scored:,} finite forecasts,"
            f" {meta['forecast_with_observed_label_rows']:,} with observed labels,"
            f" {len(forecast.fits)} fits, {seconds:.0f} s"
        )
    return meta


# Write a Forecasts to one compressed npz: dates as int64 days, tickers as
# str, the metadata as one JSON string.
def save_forecasts(path: Path, forecasts: Forecasts) -> Path:
    """Write `forecasts` to `path` and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {
        "ticker": np.asarray(forecasts.tickers).astype(str),
        "date": np.asarray(forecasts.dates)
        .astype("datetime64[D]")
        .astype("int64"),
        "forecast": np.asarray(forecasts.forecast, dtype=float),
        "baseline": np.asarray(forecasts.baseline, dtype=float),
    }
    if forecasts.realized is not None:
        arrays["realized"] = np.asarray(forecasts.realized, dtype=float)
    arrays["meta"] = np.array(json.dumps(forecasts.meta or {}, default=str))
    lengths = {len(v) for k, v in arrays.items() if k != "meta"}
    if len(lengths) != 1:
        raise ValueError("forecast arrays must have one common length")
    np.savez_compressed(path, **arrays)
    return path


# Read a file written by `save_forecasts` (or any npz carrying the FIELDS).
def load_forecasts(path: Path) -> Forecasts:
    """Return the Forecasts stored at `path`."""
    with np.load(Path(path), allow_pickle=False) as data:
        missing = [name for name in FIELDS if name not in data.files]
        if missing:
            raise ValueError(f"{path} lacks forecast arrays {missing}")
        tickers = data["ticker"].astype(str)
        dates = data["date"].astype("int64").astype("datetime64[D]")
        forecast = data["forecast"].astype(float)
        baseline = data["baseline"].astype(float)
        realized = data["realized"].astype(float) if "realized" in data.files else None
        meta = json.loads(str(data["meta"])) if "meta" in data.files else None
    n = len(dates)
    if not (len(tickers) == len(forecast) == len(baseline) == n) or (
        realized is not None and len(realized) != n
    ):
        raise ValueError(f"{path}: forecast arrays differ in length")
    return Forecasts(dates, tickers, forecast, baseline, realized, meta)


# Put the rows on a (sessions, names) grid: row (name, t) lands at the
# panel position of date t and the column of the name; cells with no row
# are NaN; a name or a date the panel does not have is dropped. A duplicate
# (name, t) is an error rather than a silent overwrite.
def align(
    forecasts: Forecasts, dates: np.ndarray, tickers: tuple[str, ...] | list[str]
) -> Aligned:
    """Return the Aligned grid of `forecasts` on `dates` x `tickers`."""
    dates = np.asarray(dates).astype("datetime64[D]")
    tickers = tuple(str(t) for t in tickers)
    if len(dates) > 1 and not (dates[1:] > dates[:-1]).all():
        raise ValueError("panel dates must be strictly increasing")
    column = {t: j for j, t in enumerate(tickers)}
    shape = (len(dates), len(tickers))
    forecast = np.full(shape, np.nan)
    baseline = np.full(shape, np.nan)
    realized = np.full(shape, np.nan) if forecasts.realized is not None else None
    if len(forecasts):
        own = np.asarray(forecasts.dates).astype("datetime64[D]")
        pos = np.searchsorted(dates, own)
        on_grid = (pos < len(dates)) & (dates[np.minimum(pos, len(dates) - 1)] == own)
        cols = np.array([column.get(str(t), -1) for t in forecasts.tickers])
        keep = on_grid & (cols >= 0)
        rows, cols = pos[keep], cols[keep]
        if len(np.unique(rows * len(tickers) + cols)) != len(rows):
            raise ValueError("duplicate (ticker, date) rows in the forecast file")
        forecast[rows, cols] = forecasts.forecast[keep]
        baseline[rows, cols] = forecasts.baseline[keep]
        if realized is not None and forecasts.realized is not None:
            realized[rows, cols] = forecasts.realized[keep]
    return Aligned(dates, tickers, forecast, baseline, realized)


# Load a file and align it to a panel (anything with `dates` and `tickers`).
def aligned_to_panel(path: Path, panel) -> Aligned:
    """Return the file's forecasts on the panel's grid."""
    return align(load_forecasts(path), panel.dates, tuple(panel.tickers))
