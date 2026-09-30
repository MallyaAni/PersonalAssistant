"""Kronos export: the bars and the cells the RTX forecasts, as tables.

`docs/research/kronos-plan-2026-09-30.md` (with Addendum 1) registers the
study; this module assembles, from inputs already loaded, the four tables
`backend/research/kronos_forecast.py` reads on the RTX:

* ``daily`` - one row per (ticker, session) of the panel's *adjusted* OHLCV
  for every book name (the benchmark column left out), sessions with a
  finite close only: `stage3_features.adjusted_ohlc` (the dividend factor
  on open, high and low; the adjusted close itself), the store's volume.
  K1's context is the last `DAILY_CONTEXT` of these rows through t.
* ``bars15`` - one row per (ticker, session, slot) of the cube's 26 regular
  bars, moved onto the panel's adjusted basis by `stage4_labels.cube_scale`
  (the panel's adjusted close over the cube's official close that session,
  never `adj_close / close`), so a split inside a context is no jump.
  K2's context is the last `INTRADAY_CONTEXT` of these bars through the
  end of session t.
* ``cells`` - one row per (session t, ticker) the desk graded while the
  point-in-time membership held, from `since` on (the plan's in-window
  start, 2018-01-02): the session's index in the panel, the grade, and the
  next panel session's date (K2 forecasts t+1's bars) - NaT after the last.
* ``sessions`` - the panel's dates, so K1's y-timestamps are the next 20
  sessions where the panel has them.

`from_store` loads the inputs as the stage-3 export did; everything else is
pure and tested on synthetic inputs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.market import stage3_features
from backend.market import stage4_labels as lab
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

PLAN = "docs/research/kronos-plan-2026-09-30.md"
FORMAT_VERSION = "kronos-export/1"
# The plan's context lengths (Kronos-base's context is 512 tokens).
DAILY_CONTEXT = 512
INTRADAY_CONTEXT = 512
# The plan's horizons: 20 sessions for K1, the 26 bars of t+1 for K2.
DAILY_HORIZON = 20
INTRADAY_HORIZON = FULL_SESSION_SLOTS
# The in-window start: cells before it are not forecast.
SINCE = date(2018, 1, 2)
# The regular session's bar starts, New York time, 09:30 to 15:45.
SLOT_MINUTES = 9 * 60 + 30 + 15 * np.arange(FULL_SESSION_SLOTS)
DAILY_COLUMNS = ("ticker", "date", "open", "high", "low", "close", "volume")
BARS_COLUMNS = ("ticker", "date", "slot", "open", "high", "low", "close", "volume")
CELLS_COLUMNS = ("date", "ticker", "session", "grade", "next_date")

assert len(SLOT_MINUTES) == FULL_SESSION_SLOTS and SLOT_MINUTES[-1] == 15 * 60 + 45


@dataclass
class Inputs:
    """Everything the export reads, on the panel's grid."""

    panel: Any
    cubes: Mapping[str, SessionCube]
    grades: np.ndarray  # (T, N) int, -1 where the desk did not grade
    member: np.ndarray  # (T, N) bool point-in-time membership
    meta: dict[str, Any] = field(default_factory=dict)

    # The book's columns: every panel ticker but the benchmark.
    def book(self) -> list[int]:
        """Return the column indices of the book names."""
        return [
            j for j, t in enumerate(self.panel.tickers) if t != self.panel.benchmark
        ]


# The panel's adjusted daily bars of the book names as one long table,
# sessions with a finite adjusted close only.
def daily_table(inputs: Inputs) -> pd.DataFrame:
    """Return the ``daily`` table."""
    panel = inputs.panel
    open_, high, low, close = stage3_features.adjusted_ohlc(panel)
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    frames = []
    for j in inputs.book():
        keep = np.isfinite(close[:, j])
        if not keep.any():
            continue
        frames.append(
            pd.DataFrame(
                {
                    "ticker": str(panel.tickers[j]),
                    "date": dates[keep],
                    "open": open_[keep, j],
                    "high": high[keep, j],
                    "low": low[keep, j],
                    "close": close[keep, j],
                    "volume": np.asarray(panel.volume, dtype=float)[keep, j],
                }
            )
        )
    if not frames:
        return pd.DataFrame({c: [] for c in DAILY_COLUMNS})
    out = pd.concat(frames, ignore_index=True)
    return out[list(DAILY_COLUMNS)]


# One name's cube on the panel's adjusted basis: every complete session
# the panel also has, its 26 regular bars scaled by `cube_scale` of that
# session; a session the panel lacks (or whose scale is not finite) is left
# out. Returns the long table for the name.
def name_bars(ticker: str, series: lab.NameSeries, cube: SessionCube) -> pd.DataFrame:
    """Return the ``bars15`` rows of one name."""
    if not len(cube):
        return pd.DataFrame({c: [] for c in BARS_COLUMNS})
    rows = lab.cube_rows(series.dates, cube)
    scale = lab.cube_scale(series, cube)
    keep = np.flatnonzero((rows >= 0) & np.isfinite(scale))
    if not len(keep):
        return pd.DataFrame({c: [] for c in BARS_COLUMNS})
    r = rows[keep]
    s = scale[keep][:, None]
    n = len(keep)
    slots = np.tile(np.arange(FULL_SESSION_SLOTS), n)
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": np.repeat(np.asarray(series.dates)[keep], FULL_SESSION_SLOTS),
            "slot": slots.astype(np.int16),
            "open": (cube.open[r] * s).ravel(),
            "high": (cube.high[r] * s).ravel(),
            "low": (cube.low[r] * s).ravel(),
            "close": (cube.close[r] * s).ravel(),
            "volume": np.asarray(cube.volume[r], dtype=float).ravel(),
        }
    )[list(BARS_COLUMNS)]


# Every book name's cube bars on the adjusted basis, one long table.
def bars_table(inputs: Inputs) -> pd.DataFrame:
    """Return the ``bars15`` table."""
    panel = inputs.panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    frames = []
    for j in inputs.book():
        ticker = str(panel.tickers[j])
        cube = inputs.cubes.get(ticker)
        if cube is None or not len(cube):
            continue
        series = lab.name_series(
            dates,
            panel.close[:, j],
            panel.adj_close[:, j],
            panel.high[:, j],
            panel.low[:, j],
        )
        frame = name_bars(ticker, series, cube)
        if len(frame):
            frames.append(frame)
    if not frames:
        return pd.DataFrame({c: [] for c in BARS_COLUMNS})
    return pd.concat(frames, ignore_index=True)


# The graded, member (session, name) cells from `since` on: the session's
# panel index, the grade and the next panel session's date.
def cells_table(inputs: Inputs, since: date = SINCE) -> pd.DataFrame:
    """Return the ``cells`` table."""
    panel = inputs.panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    eligible = np.asarray(inputs.member, dtype=bool) & (np.asarray(inputs.grades) >= 0)
    eligible[:, panel.index(panel.benchmark)] = False
    eligible[dates < np.datetime64(since), :] = False
    t, j = np.nonzero(eligible)
    next_date = np.full(len(dates), np.datetime64("NaT", "D"))
    next_date[:-1] = dates[1:]
    tickers = np.asarray(panel.tickers)
    out = pd.DataFrame(
        {
            "date": dates[t],
            "ticker": tickers[j],
            "session": t.astype(np.int64),
            "grade": np.asarray(inputs.grades)[t, j].astype(np.int64),
            "next_date": next_date[t],
        }
    )
    return out[list(CELLS_COLUMNS)]


# The panel's sessions as a one-column table.
def sessions_table(inputs: Inputs) -> pd.DataFrame:
    """Return the ``sessions`` table."""
    return pd.DataFrame({"date": np.asarray(inputs.panel.dates, dtype="datetime64[D]")})


# A per-cell readiness count: how many cells have a full daily context (K1)
# and a full 15-minute context through t (K2), for the summary.
def context_coverage(
    daily: pd.DataFrame, bars: pd.DataFrame, cells: pd.DataFrame
) -> dict[str, int]:
    """Return {"cells", "k1_full_context", "k2_full_context"}."""
    out = {"cells": int(len(cells)), "k1_full_context": 0, "k2_full_context": 0}
    if not len(cells):
        return out
    daily_count = {
        ticker: (
            np.asarray(group["date"], dtype="datetime64[D]"),
            np.arange(1, len(group) + 1),
        )
        for ticker, group in daily.sort_values(["ticker", "date"]).groupby(
            "ticker", sort=False
        )
    }
    bars_count = {
        ticker: (
            np.asarray(group["date"], dtype="datetime64[D]"),
            np.arange(1, len(group) + 1) * FULL_SESSION_SLOTS,
        )
        for ticker, group in bars[bars["slot"] == FULL_SESSION_SLOTS - 1]
        .sort_values(["ticker", "date"])
        .groupby("ticker", sort=False)
    }
    for ticker, group in cells.groupby("ticker", sort=False):
        when = np.asarray(group["date"], dtype="datetime64[D]")
        for table, key, need in (
            (daily_count, "k1_full_context", DAILY_CONTEXT),
            (bars_count, "k2_full_context", INTRADAY_CONTEXT),
        ):
            found = table.get(ticker)
            if found is None:
                continue
            days, counts = found
            pos = np.searchsorted(days, when, side="right")
            have = np.where(pos > 0, counts[np.maximum(pos - 1, 0)], 0)
            out[key] += int((have >= need).sum())
    return out


# Load the inputs the way the stage-3 export did: the cubes of the book
# names, the desk report (panel and grades) and the point-in-time
# membership.
def from_store(
    store,
    tickers: tuple[str, ...],
    membership_path: Path,
    desk_run: Callable[[Any], Any],
    workers: int = 8,
    log: Callable[[str], None] = print,
) -> Inputs:
    """Return the Inputs for the store."""
    import time

    from backend.agents.trading.desk import point_in_time
    from backend.cli.market_session_anatomy import load_cubes

    began = time.perf_counter()
    cubes, lines = load_cubes(store, tuple(tickers), workers=workers)
    log(f"cubes: {len(cubes)} ({time.perf_counter() - began:.0f} s)")
    report = desk_run(store)
    panel = report.panel
    log(
        f"desk: {len(panel.dates)} sessions x {len(panel.tickers)} names ({time.perf_counter() - began:.0f} s)"
    )
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    member = point_in_time.eligibility(
        dates, tuple(panel.tickers), history_path=membership_path
    )
    return Inputs(
        panel=panel,
        cubes=cubes,
        grades=np.asarray(report.graded.grades, dtype=int),
        member=np.asarray(member, dtype=bool),
        meta={
            "store": str(store.root),
            "membership": str(membership_path),
            "cube_lines": lines,
            "names_with_cube": len(cubes),
        },
    )
