"""The CNN's 20-session drawdown forecast as a file, and its alignment to a panel.

The deep stage-2 study (`docs/research/deep-stage2-plan-2026-09-27.md`,
`backend/market/deep_stage2.py`) found the temporal CNN forecasts the
20-session drawdown of a name with IC 0.12-0.15 (t 7-9), and that dropping
the flagged names from the book loses 2 bp a session. The profit-taking
study (`profit_taking`) prices the softer use - halving the flagged names
rather than dropping them - and this module is the seam between the two:
`export_forecasts` walks a stage-2 model forward on the ``drawdown20``
target alone and writes the out-of-sample forecast per (name, session) row
to one npz with the columns ticker / date / forecast (and the realized
target beside it), and `align` puts that file on a price panel's
(sessions, names) grid so a rule can read the forecast at its decision
session.

The forecast for dataset row (name, t) is made from bars through the close
of t (`Dataset2.x_seq` ends at t, the scalars are t's) and its target is
the drawdown over sessions t + 1 .. t + 20 (`deep_stage2.horizon_features`:
the minimum close ratio over the horizon minus one, so more negative is
worse). The simulator's hook decides at t's close, so the row it may read
is the one dated t and no other: `align` puts row (name, t) at the panel
position of date t, exactly as `vol_forecast.align` does, and the
no-lookahead test asserts that a one-session shift is a different matrix.
The walk-forward is `deep_stage2.walk_forward` unchanged (stage 1's REFIT
and MIN_TRAIN, PURGE 20); the values written are exactly `Forecast.values`,
NaN before the first fit. `deep_stage2` is imported inside
`export_forecasts` only, so this module and the profit-taking study load
without the stage-2 stack, and torch is imported only inside the CNN family,
so `export_forecasts(model="ridge")` runs where torch is absent.

Version 2 exports retain the dataset's declared row-selection convention and
separate finite predictions from predictions with observed labels. Missing old
declarations remain ``legacy-unrecorded``; this metadata does not qualify their
causality or historical provenance, and existing archives are never upgraded.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# The file's arrays, in a fixed order. `realized` is optional on load.
FIELDS = ("ticker", "date", "forecast")
OPTIONAL_FIELDS = ("realized",)
# The head this module exports by default, and the target.
MODEL = "cnn"
TARGET = "drawdown20"
# New exports declare row selection and distinguish predictions from observed labels.
VERSION = 2


@dataclass(frozen=True)
class Forecasts:
    """Per-row drawdown forecasts: one entry per (name, session t)."""

    dates: np.ndarray  # (M,) datetime64[D], the decision session t
    tickers: np.ndarray  # (M,) str
    forecast: np.ndarray  # (M,) forecast drawdown over t + 1 .. t + 20, NaN unscored
    realized: np.ndarray | None = None  # (M,) the realized drawdown, NaN unknown
    meta: dict[str, Any] | None = None

    # Rows in the file.
    def __len__(self) -> int:
        return int(len(self.dates))

    # Read declared row selection without upgrading metadata absent from old files.
    @property
    def row_selection(self) -> str:
        from backend.market import deep_intraday

        if self.meta is None or "row_selection" not in self.meta:
            return deep_intraday.LEGACY_ROW_SELECTION
        return deep_intraday.load_row_selection(
            {"row_selection": np.asarray(self.meta["row_selection"])}
        )


# Run the stage-2 walk-forward on the drawdown target only and write the
# out-of-sample forecast per row, with the realized target beside it, to
# `out_npz`. `model` is a `deep_stage2` model name (the CNN by default; the
# ridge runs without torch). Returns a summary: rows, scored rows, fits,
# seconds and the daily IC against the realized drawdown per window.
# Retain the dataset's row-selection declaration and distinct label coverage.
def export_forecasts(
    dataset_npz: Path,
    out_npz: Path,
    device: str = "auto",
    model: str = MODEL,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Walk `model` forward on the drawdown target and write the forecasts."""
    from backend.market import deep_intraday, deep_stage2

    ds = deep_stage2.load_dataset(Path(dataset_npz))
    resolved = deep_intraday.resolve_device(device, deep_intraday.cuda_available())
    if model in deep_stage2.TORCH_MODELS:
        deep_intraday.announce_device(resolved, log)
    began = time.perf_counter()
    forecast = deep_stage2.walk_forward(ds, model, (TARGET,), log=log, device=resolved)[
        TARGET
    ]
    seconds = time.perf_counter() - began
    meta = summary(ds, forecast, model, resolved, str(dataset_npz), seconds)
    save_forecasts(
        Path(out_npz),
        Forecasts(
            dates=ds.dates,
            tickers=ds.tickers,
            forecast=forecast.values,
            realized=ds.y_drawdown20,
            meta=meta,
        ),
    )
    if log is not None:
        log(
            f"wrote {out_npz}: {len(ds):,} rows,"
            f" {meta['finite_forecast_rows']:,} finite forecasts,"
            f" {meta['forecast_with_observed_label_rows']:,} with observed labels,"
            f" {len(forecast.fits)} fits, {seconds:.0f} s"
        )
    return meta


# The metadata written beside the forecasts: the run's shape and the daily
# IC of the forecast against the realized drawdown per window.
# Record row-selection provenance and separate predictions from observed labels.
def summary(
    ds, forecast, model: str, device: str, dataset: str, seconds: float
) -> dict:
    """Return the export's summary for a stage-2 dataset and its Forecast."""
    from backend.market import deep_intraday, deep_stage2

    ic: dict[str, Any] = {}
    for name, (start, end) in deep_intraday.WINDOWS.items():
        rows = deep_intraday.window_rows(ds, start, end)
        series = deep_stage2.daily_spearman(ds, forecast, ds.y_drawdown20, rows)
        ic[name] = series.summary()
    finite = np.isfinite(forecast.values)
    observed = np.isfinite(ds.y_drawdown20)
    return {
        "version": VERSION,
        "row_selection": ds.row_selection,
        "model": model,
        "target": TARGET,
        "device": device,
        "dataset": dataset,
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
        "ic": ic,
        "constants": {
            "refit": deep_intraday.REFIT,
            "min_train": deep_intraday.MIN_TRAIN,
            "purge": deep_stage2.PURGE,
            "horizon": deep_stage2.HORIZON,
        },
    }


# Write a Forecasts to one compressed npz: dates as int64 days, tickers as
# str, the metadata as one JSON string.
def save_forecasts(path: Path, forecasts: Forecasts) -> Path:
    """Write `forecasts` to `path` and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {
        "ticker": np.asarray(forecasts.tickers).astype(str),
        "date": np.asarray(forecasts.dates).astype("datetime64[D]").astype("int64"),
        "forecast": np.asarray(forecasts.forecast, dtype=float),
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
        realized = data["realized"].astype(float) if "realized" in data.files else None
        meta = json.loads(str(data["meta"])) if "meta" in data.files else None
    n = len(dates)
    if (
        len(tickers) != n
        or len(forecast) != n
        or (realized is not None and len(realized) != n)
    ):
        raise ValueError(f"{path}: forecast arrays differ in length")
    return Forecasts(dates, tickers, forecast, realized, meta)


# Put the rows on a (sessions, names) grid: row (name, t) lands at the
# panel position of date t and the column of the name; cells with no row
# are NaN; a name or a date the panel does not have is dropped. A duplicate
# (name, t) is an error rather than a silent overwrite.
def align(
    forecasts: Forecasts, dates: np.ndarray, tickers: tuple[str, ...] | list[str]
) -> np.ndarray:
    """Return the (T, N) forecast grid of `forecasts` on `dates` x `tickers`."""
    dates = np.asarray(dates).astype("datetime64[D]")
    tickers = tuple(str(t) for t in tickers)
    if len(dates) > 1 and not (dates[1:] > dates[:-1]).all():
        raise ValueError("panel dates must be strictly increasing")
    column = {t: j for j, t in enumerate(tickers)}
    grid = np.full((len(dates), len(tickers)), np.nan)
    if len(forecasts):
        own = np.asarray(forecasts.dates).astype("datetime64[D]")
        pos = np.searchsorted(dates, own)
        on_grid = (pos < len(dates)) & (dates[np.minimum(pos, len(dates) - 1)] == own)
        cols = np.array([column.get(str(t), -1) for t in forecasts.tickers])
        keep = on_grid & (cols >= 0)
        rows, cols = pos[keep], cols[keep]
        if len(np.unique(rows * len(tickers) + cols)) != len(rows):
            raise ValueError("duplicate (ticker, date) rows in the forecast file")
        grid[rows, cols] = forecasts.forecast[keep]
    return grid


# Load a file and align it to a panel (anything with `dates` and `tickers`).
def aligned_to_panel(path: Path, panel) -> np.ndarray:
    """Return the file's forecasts on the panel's grid."""
    return align(load_forecasts(path), panel.dates, tuple(panel.tickers))
