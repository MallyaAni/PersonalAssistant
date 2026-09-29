"""Stage 3's export: the two datasets, the sequence tensor and the daily bars.

This assembles, from inputs already loaded (`Inputs`), exactly the rows
`docs/research/stage3-plan-2026-09-29.md` registers:

* ``s1`` - one row per (name, decision date t) the desk graded and the
  point-in-time membership held, from the first SIP session on. The label is
  the per-date rank-Gauss of r(i, t) = ln(O~(t+21) / O~(t+1)) minus the mean
  of the same over the date's rows, O~ the dividend-adjusted open; r itself
  is kept as `extra["r"]`. Name-level columns are rank-Gaussed across the
  date's rows; date-level columns stay raw.
* ``ti`` - one row per (name, session s, slot k), k = 0..23, for every
  complete cube session s whose previous panel session t the name was an
  eligible, graded member on. Columns: the intraday block at the close of
  slot k, the daily block at t, and the two stage-1/2 forecasts at t (V06).
  The label is 1e4 * ln(official close of s / C_k), in bp.

The sequence tensor holds every name's cube sessions (the 12 channels of
`stage3_intraday.sequence_channels`), and the daily bars are the panel's
adjusted OHLCV for the chart images.

`from_store` loads the inputs as the desk and the earlier studies do; every
other function is pure and is tested on synthetic inputs.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from backend.market import sr_levels, stage3_features, stage3_intraday
from backend.market import stage3_io as io
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

# The side of the book each ETF stands for.
SIDE_ETF = {"ai": "SMH", "software": "IGV"}
MARKET_ETFS = ("SPY", "QQQ")
# The daily columns of the two stage-1/2 forecasts (T-I only).
FORECAST_COLUMNS = ("d_volfc", "d_ddfc")


@dataclass
class Inputs:
    """Everything the export reads, already on the panel's grid."""

    panel: Any
    cubes: Mapping[str, SessionCube]  # book names and the ETFs
    grades: np.ndarray  # (T, N) int, -1 where the desk did not grade
    stances: Mapping[str, np.ndarray]
    regime: np.ndarray  # (T, 6)
    sides: Mapping[str, str]
    member: np.ndarray  # (T, N) bool point-in-time membership
    earnings_day: np.ndarray  # (T, N) bool: an earnings reaction session
    shares: np.ndarray | None = None
    edgar: tuple[np.ndarray, tuple[str, ...]] | None = None
    tone: tuple[np.ndarray, tuple[str, ...]] | None = None
    calendar: tuple[np.ndarray, tuple[str, ...]] | None = None
    macro: tuple[np.ndarray, tuple[str, ...]] | None = None
    vol_forecast: np.ndarray | None = None  # (T, N)
    dd_forecast: np.ndarray | None = None  # (T, N)
    meta: dict[str, Any] = field(default_factory=dict)

    # The (T, N) rows the study may use: members the desk graded, never
    # the benchmark column.
    def eligible(self) -> np.ndarray:
        """Return the eligible (member and graded) grid."""
        out = np.asarray(self.member, dtype=bool) & (np.asarray(self.grades) >= 0)
        out[:, self.panel.index(self.panel.benchmark)] = False
        return out


# The daily log returns of each side's ETF on the panel's dates, from its
# cube (official close over prior close); sessions the cube lacks (early
# closes) are 0, the stated approximation.
def side_returns(panel, cubes: Mapping[str, SessionCube]) -> dict[str, np.ndarray]:
    """Return {side: (T,) daily log returns of its ETF}."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    out: dict[str, np.ndarray] = {}
    for side, etf in SIDE_ETF.items():
        series = np.zeros(len(dates))
        cube = cubes.get(etf)
        if cube is not None and len(cube):
            official = np.where(
                np.isfinite(cube.auction_open) & (cube.auction_open > 0),
                cube.auction_open,
                cube.close[:, -1],
            )
            with np.errstate(all="ignore"):
                values = np.log(official / cube.prior_close)
            pos = np.searchsorted(dates, cube.dates)
            ok = (pos < len(dates)) & (dates[np.minimum(pos, len(dates) - 1)] == cube.dates)
            series[pos[ok]] = np.where(np.isfinite(values[ok]), values[ok], 0.0)
        out[side] = series
    return out


# The daily block of the inputs, with the internals the intraday block reads.
def build_daily(inputs: Inputs) -> tuple[stage3_features.DailyBlock, dict[str, Any]]:
    """Return (DailyBlock, internals) for the inputs."""
    edgar_values, edgar_names = inputs.edgar if inputs.edgar else (None, ())
    tone_values, tone_names = inputs.tone if inputs.tone else (None, ())
    calendar_values, calendar_names = inputs.calendar if inputs.calendar else (None, ())
    macro_values, macro_names = inputs.macro if inputs.macro else (None, ())
    return stage3_features.daily_block(
        inputs.panel,
        sides=inputs.sides,
        side_returns=side_returns(inputs.panel, inputs.cubes),
        cubes=inputs.cubes,
        eligible=inputs.eligible(),
        grades=inputs.grades,
        stances=inputs.stances,
        regime=inputs.regime,
        earnings_day=inputs.earnings_day,
        shares=inputs.shares,
        edgar_values=edgar_values,
        edgar_names=edgar_names,
        tone_values=tone_values,
        tone_names=tone_names,
        calendar_values=calendar_values,
        calendar_names=calendar_names,
        macro_values=macro_values,
        macro_names=macro_names,
    )


# The first date with a SIP session for any book name: the s1 rows start there.
def _first_cube_date(inputs: Inputs) -> np.datetime64:
    book = [c for t, c in inputs.cubes.items() if t in inputs.panel.tickers and len(c)]
    if not book:
        raise ValueError("no book name has a cube")
    return min(c.dates[0] for c in book)


# The T-S1 dataset: rows, rank-Gaussed features, the relative-return label.
def s1_data(inputs: Inputs, block: stage3_features.DailyBlock) -> io.Stage3Data:
    """Return the s1 Stage3Data."""
    panel = inputs.panel
    eligible = inputs.eligible()
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    eligible &= (dates >= _first_cube_date(inputs))[:, None]
    open_, _, _, _ = stage3_features.adjusted_ohlc(panel)
    rows_total = len(dates)
    raw = np.full(open_.shape, np.nan)
    horizon = io.S1_HORIZON
    with np.errstate(all="ignore"):
        if rows_total > horizon + 1:
            raw[: rows_total - horizon - 1] = np.log(open_[horizon + 1 :] / open_[1 : rows_total - horizon])
    raw = np.where(eligible & np.isfinite(raw), raw, np.nan)
    with np.errstate(invalid="ignore"):
        centre = np.nanmean(np.where(np.isfinite(raw), raw, np.nan), axis=1, keepdims=True) if raw.size else raw
    relative = raw - centre
    ranked = io.rank_gauss_panel(block.values.astype(float), eligible)
    values = np.where(block.date_level[None, None, :], block.values.astype(float), ranked)
    t_idx, n_idx = np.nonzero(eligible)
    tickers = np.asarray(panel.tickers)[n_idx]
    order = np.lexsort((tickers, dates[t_idx]))
    t_idx, n_idx, tickers = t_idx[order], n_idx[order], tickers[order]
    r = relative[t_idx, n_idx]
    y = io.rank_gauss(r, dates[t_idx])
    return io.Stage3Data(
        kind=io.S1,
        dates=dates[t_idx],
        tickers=tickers,
        slot=np.zeros(len(t_idx), dtype=np.int8),
        x=values[t_idx, n_idx].astype(np.float32),
        feature_names=block.names,
        y=y.astype(np.float32),
        extra={"r": r.astype(np.float32), "grade": np.asarray(inputs.grades)[t_idx, n_idx].astype(np.int8)},
        meta={"rows": int(len(t_idx)), **inputs.meta},
    )


# Per cube session of one name: its panel row, the previous row t, and the
# daily values the intraday block reads at t. Sessions without a panel row
# or without a previous one carry NaN.
def _daily_at_t(inputs: Inputs, block: stage3_features.DailyBlock, internals: Mapping[str, Any], j: int, cube: SessionCube) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    panel = inputs.panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    pos = np.searchsorted(dates, cube.dates)
    ok = (pos < len(dates)) & (dates[np.minimum(pos, len(dates) - 1)] == cube.dates) & (pos >= 1)
    t = np.where(ok, pos - 1, 0)
    _, high, low, close = stage3_features.adjusted_ohlc(panel)

    def at_t(grid: np.ndarray) -> np.ndarray:
        return np.where(ok, np.asarray(grid, dtype=float)[t, j], np.nan)

    daily = {
        "atr": at_t(internals["atr14"]),
        "pdh": at_t(high),
        "pdl": at_t(low),
        "pdc": at_t(close),
        "adj_close_t": at_t(close),
        "beta_spy": at_t(block.values[:, :, block.column("d_beta60_spy")]),
        "beta_side": at_t(block.values[:, :, block.column("d_beta60_side")]),
        "trend_daily": at_t(internals["trend_daily"]),
        "trend_weekly": at_t(internals["trend_weekly"]),
        "trend_monthly": at_t(internals["trend_monthly"]),
    }
    return pos, ok, daily


# The official close of every cube session: the auction print, else the
# last regular bar's close.
def official_close(cube: SessionCube) -> np.ndarray:
    """Return (S,) the official close of each cube session."""
    return np.where(
        np.isfinite(cube.auction_open) & (cube.auction_open > 0), cube.auction_open, cube.close[:, -1]
    )


# The T-I dataset. Rows are placed directly at their sorted (date, ticker,
# slot) positions so the ~2 GB feature matrix is written once, never copied
# or re-sorted.
def ti_data(
    inputs: Inputs,
    block: stage3_features.DailyBlock,
    internals: Mapping[str, Any],
    log: Callable[[str], None] | None = None,
) -> io.Stage3Data:
    """Return the ti Stage3Data."""
    panel = inputs.panel
    eligible = inputs.eligible()
    tickers = tuple(panel.tickers)
    spy, qqq = inputs.cubes.get("SPY"), inputs.cubes.get("QQQ")
    keep_by_name: dict[str, np.ndarray] = {}
    info: dict[str, tuple] = {}
    for j, ticker in enumerate(tickers):
        cube = inputs.cubes.get(ticker)
        if cube is None or len(cube) == 0 or ticker == panel.benchmark:
            continue
        pos, ok, daily = _daily_at_t(inputs, block, internals, j, cube)
        keep = ok & eligible[np.where(ok, pos - 1, 0), j]
        if keep.any():
            keep_by_name[ticker] = keep
            info[ticker] = (j, pos, daily)
    market = stage3_intraday.breadth({t: inputs.cubes[t] for t in keep_by_name}, keep_by_name)
    # Global row order.
    keys = [(cube_date, ticker) for ticker, keep in keep_by_name.items() for cube_date in inputs.cubes[ticker].dates[keep]]
    key_dates = np.array([k[0] for k in keys], dtype="datetime64[D]")
    key_tickers = np.array([k[1] for k in keys])
    order = np.lexsort((key_tickers, key_dates))
    rank = np.empty(len(order), dtype=np.int64)
    rank[order] = np.arange(len(order))
    daily_names = block.names
    extra_names = FORECAST_COLUMNS
    intraday_names: tuple[str, ...] | None = None
    rows = len(keys) * io.TI_SLOTS
    x = None
    y = np.full(rows, np.nan, dtype=np.float32)
    levels = sr_levels.daily_levels(panel)
    offset = 0
    began = time.perf_counter()
    for ticker, keep in keep_by_name.items():
        cube = inputs.cubes[ticker]
        j, pos, daily = info[ticker]
        side = inputs.cubes.get(SIDE_ETF.get(inputs.sides.get(ticker, "ai"), "SMH"))
        rows_pos = np.where(pos < len(levels.dates), pos, len(levels.dates) - 1)
        level_block = (
            np.where((pos < len(levels.dates))[:, None], levels.levels[rows_pos, j], np.nan),
            np.where(pos < len(levels.dates), levels.width[rows_pos, j], np.nan),
        )
        name = stage3_intraday.name_block(cube, daily, spy, qqq, side, market, level_block)
        if intraday_names is None:
            intraday_names = name.names
            x = np.full((rows, len(intraday_names) + len(daily_names) + len(extra_names)), np.nan, dtype=np.float32)
        elif name.names != intraday_names:
            raise ValueError(f"{ticker}: intraday columns differ from the first name's")
        count = int(keep.sum())
        targets = rank[offset : offset + count]
        offset += count
        slot_rows = targets[:, None] * io.TI_SLOTS + np.arange(io.TI_SLOTS)[None, :]
        t = pos[keep] - 1
        width_i = len(intraday_names)
        x[slot_rows, :width_i] = name.values[keep]
        daily_values = block.values[t, j]  # (count, F_d)
        x[slot_rows, width_i : width_i + len(daily_names)] = daily_values[:, None, :]
        for c, grid in enumerate((inputs.vol_forecast, inputs.dd_forecast)):
            if grid is not None:
                x[slot_rows, width_i + len(daily_names) + c] = np.asarray(grid, dtype=float)[t, j][:, None]
        with np.errstate(all="ignore"):
            label = 1e4 * np.log(official_close(cube)[keep][:, None] / cube.close[keep][:, : io.TI_SLOTS])
        y[slot_rows] = np.where(np.isfinite(label), label, np.nan)
        if log is not None:
            log(f"  {ticker:<6} {count:>5} sessions ({time.perf_counter() - began:.0f} s)")
    if x is None:
        raise ValueError("no T-I rows")
    names = intraday_names + daily_names + extra_names
    session_dates = np.repeat(key_dates[order], io.TI_SLOTS)
    session_tickers = np.repeat(key_tickers[order], io.TI_SLOTS)
    slot = np.tile(np.arange(io.TI_SLOTS, dtype=np.int8), len(keys))
    return io.Stage3Data(
        kind=io.TI,
        dates=session_dates,
        tickers=session_tickers,
        slot=slot,
        x=x,
        feature_names=names,
        y=y,
        extra={},
        meta={"rows": int(rows), "name_sessions": int(len(keys)), **inputs.meta},
    )


# The sequence tensor over the union of the book names' cube sessions.
def seq_tensor(inputs: Inputs, block: stage3_features.DailyBlock, internals: Mapping[str, Any]) -> io.SeqTensor:
    """Return the SeqTensor of every book name with a cube."""
    panel = inputs.panel
    tickers = [t for t in panel.tickers if t != panel.benchmark and t in inputs.cubes and len(inputs.cubes[t])]
    sessions = np.unique(np.concatenate([inputs.cubes[t].dates for t in tickers]))
    seq = np.full((len(tickers), len(sessions), io.STEPS_PER_SESSION, len(io.SEQ_CHANNELS)), np.nan, dtype=np.float16)
    valid = np.zeros((len(tickers), len(sessions)), dtype=bool)
    spy = inputs.cubes.get("SPY")
    for n, ticker in enumerate(tickers):
        cube = inputs.cubes[ticker]
        j = panel.index(ticker)
        _, _, daily = _daily_at_t(inputs, block, internals, j, cube)
        side = inputs.cubes.get(SIDE_ETF.get(inputs.sides.get(ticker, "ai"), "SMH"))
        channels = stage3_intraday.sequence_channels(cube, daily, spy, side)
        where = np.searchsorted(sessions, cube.dates)
        seq[n, where] = channels.astype(np.float16)
        valid[n, where] = True
    return io.SeqTensor(
        tickers=np.asarray(tickers),
        sessions=sessions.astype("datetime64[D]"),
        seq=seq,
        valid=valid,
        meta=dict(inputs.meta),
    )


# The panel's adjusted daily bars for the chart images.
def daily_bars(inputs: Inputs) -> io.DailyOHLCV:
    """Return the DailyOHLCV of the panel (benchmark column included)."""
    panel = inputs.panel
    open_, high, low, close = stage3_features.adjusted_ohlc(panel)
    return io.DailyOHLCV(
        tickers=np.asarray(panel.tickers),
        dates=np.asarray(panel.dates, dtype="datetime64[D]"),
        open=open_.astype(np.float32),
        high=high.astype(np.float32),
        low=low.astype(np.float32),
        close=close.astype(np.float32),
        volume=np.asarray(panel.volume, dtype=np.float32),
        meta=dict(inputs.meta),
    )


# Shares outstanding known at each session: the latest "shares" fact filed
# strictly before the session's date, NaN before any.
def shares_known(panel, records: Mapping[str, Any]) -> np.ndarray:
    """Return the (T, N) point-in-time shares outstanding."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    out = np.full((len(dates), len(panel.tickers)), np.nan)
    for j, ticker in enumerate(panel.tickers):
        record = records.get(ticker)
        if record is None:
            continue
        facts = sorted((f.filed, float(f.value)) for f in record.facts if f.name == "shares" and f.value and f.value > 0)
        if not facts:
            continue
        filed = np.array([np.datetime64(d, "D") for d, _ in facts])
        values = np.array([v for _, v in facts])
        idx = np.searchsorted(filed, dates, side="left") - 1
        out[:, j] = np.where(idx >= 0, values[np.maximum(idx, 0)], np.nan)
    return out


# The earnings reaction sessions on the panel, with the strict publication
# rule `edgar.edgar_features(strict_publication=True)` uses.
def earnings_days(panel, records: Mapping[str, Any]) -> np.ndarray:
    """Return the (T, N) bool of each name's earnings reaction sessions."""
    from backend.market.calendar import publication_session

    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    out = np.zeros((len(dates), len(panel.tickers)), dtype=bool)
    for j, ticker in enumerate(panel.tickers):
        record = records.get(ticker)
        if record is None:
            continue
        days = {d for e in record.events if (d := publication_session(e.accepted, before=False)) is not None}
        if not days:
            continue
        pos = np.searchsorted(dates, np.array(sorted(days), dtype="datetime64[D]"), side="left")
        pos = pos[pos < len(dates)]
        out[pos, j] = True
    return out


# Load every input from the market store the way the desk and the earlier
# studies do: the cubes, the desk report (panel, grades, stances, regime),
# the point-in-time membership, EDGAR (strict publication) and tone
# (strict before session), the calendar and VIX, and the stage-1/2
# forecast files when given.
def from_store(
    store,
    tickers: tuple[str, ...],
    membership_path: Path,
    desk_run: Callable[[Any], Any],
    workers: int = 8,
    vol_forecasts: Path | None = None,
    dd_forecasts: Path | None = None,
    asof: date | None = None,
    log: Callable[[str], None] = print,
) -> Inputs:
    """Return the Inputs for the store."""
    from backend.agents.trading.desk import point_in_time
    from backend.cli.market_session_anatomy import load_cubes
    from backend.market import calendar, deep_stage2, drawdown_forecast, edgar, language, macro, vol_forecast
    from backend.market.universe import book_sides, build_universe

    began = time.perf_counter()
    cubes, lines = load_cubes(store, (*tickers, *SIDE_ETF.values(), *MARKET_ETFS), workers=workers)
    log(f"cubes: {len(cubes)} ({time.perf_counter() - began:.0f} s)")
    report = desk_run(store)
    panel = report.panel
    log(f"desk: {len(panel.dates)} sessions x {len(panel.tickers)} names ({time.perf_counter() - began:.0f} s)")
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    member = point_in_time.eligibility(dates, tuple(panel.tickers), history_path=membership_path)
    records = _edgar_records(store, panel, asof)
    edgar_values = edgar.edgar_features(panel, records, strict_publication=True) if records else None
    tone_records = {
        t: language.records_from_frame(frame[0])
        for t in panel.tickers
        if (frame := store.read_frame(language.TONE_KIND, t, asof)) is not None
    }
    tone_values = language.tone_features(panel, tone_records, strict_before_session=True) if tone_records else None
    calendar_values = calendar.calendar_features(panel)
    try:
        macro_values = macro.macro_features(store, panel, asof)
    except Exception as exc:  # noqa: BLE001 - a missing macro layer is NaN, and said
        log(f"macro: not loaded ({type(exc).__name__}: {exc})")
        macro_values = None
    vol_grid = vol_forecast.aligned_to_panel(vol_forecasts, panel).forecast if vol_forecasts else None
    dd_grid = drawdown_forecast.aligned_to_panel(dd_forecasts, panel) if dd_forecasts else None
    universe = build_universe()
    stances = {
        name: np.asarray(values, dtype=float) for name, values in sorted(report.graded.stances.items())
    }
    return Inputs(
        panel=panel,
        cubes=cubes,
        grades=np.asarray(report.graded.grades, dtype=int),
        stances=stances,
        regime=deep_stage2.regime_scalars(report),
        sides=book_sides(universe),
        member=np.asarray(member, dtype=bool),
        earnings_day=earnings_days(panel, records),
        shares=shares_known(panel, records) if records else None,
        edgar=(edgar_values, tuple(edgar.FEATURE_NAMES)) if edgar_values is not None else None,
        tone=(tone_values, tuple(language.FEATURE_NAMES)) if tone_values is not None else None,
        calendar=(calendar_values, tuple(calendar.CALENDAR_NAMES)),
        macro=(macro_values, tuple(macro.MACRO_NAMES)) if macro_values is not None else None,
        vol_forecast=vol_grid,
        dd_forecast=dd_grid,
        meta={
            "store": str(store.root),
            "membership": str(membership_path),
            "vol_forecasts": str(vol_forecasts) if vol_forecasts else None,
            "dd_forecasts": str(dd_forecasts) if dd_forecasts else None,
            "cube_lines": lines,
            "edgar_names": len(records),
            "tone_names": len(tone_records),
        },
    )


# The EDGAR records as `model.load_edgar_features` assembles them (events,
# facts, and the release financials of the tone frames folded in).
def _edgar_records(store, panel, asof) -> dict[str, Any]:
    from dataclasses import replace
    from datetime import datetime

    from backend.market import edgar, language

    records = {}
    for ticker in panel.tickers:
        events = store.read_frame("edgar_events", ticker, asof)
        facts = store.read_frame("edgar_facts", ticker, asof)
        if events is None or facts is None:
            continue
        columns, meta = events
        records[ticker] = edgar.record_from_frames(
            ticker,
            int(meta.get("cik", "0")),
            columns,
            facts[0],
            datetime.fromisoformat(meta.get("source_time", "2000-01-01T00:00:00+00:00")),
        )
    release = edgar.release_facts(
        {
            ticker: language.records_from_frame(frame[0])
            for ticker in panel.tickers
            if (frame := store.read_frame(language.TONE_KIND, ticker, asof)) is not None
        }
    )
    for ticker, extra_facts in release.items():
        if ticker in records and extra_facts:
            records[ticker] = replace(records[ticker], facts=records[ticker].facts + tuple(extra_facts))
    return records


__all__ = [
    "FULL_SESSION_SLOTS",
    "Inputs",
    "build_daily",
    "daily_bars",
    "from_store",
    "s1_data",
    "seq_tensor",
    "ti_data",
]
