"""Stage 3's T-S1 decision: the `/4` book without its worst-forecast decile.

`docs/research/stage3-plan-2026-09-29.md` ("The two questions", T-S1) asks
whether a model of the next twenty sessions' relative return, made at
session t's close for every graded name (`stage3_io.Stage3Forecast`, kind
"s1"), should keep the worst-ranked names out of the book. The decision is
an overlay on the live executor as it runs tonight:

* The control is `ew-redeploy`: `market_pit_scorecard._live_options` plus
  the redeploy of idle cash, exactly `profit_taking.control_options`, with
  `policy_v4.allocator(mask)`.
* The overlay is the same run with the allocator wrapped (`Overlay`, the
  `profit_taking.ProfitTaking` pattern): each time the simulator asks for
  targets on session t - at a reset, and on every mid-cycle session for the
  redeploy's - take the policy's targets and its names with a positive
  target and a finite forecast on row t. If there are n >= S1_MIN_NAMES of
  them, the ceil(S1_DROP_SHARE * n) with the lowest forecast get a zero
  target (ties: the lower panel column first). The rest of the book is
  recomputed as the policy's own equal weight over the reduced set under
  the same 20% cap - `policy_v4.targets` on the membership row with the
  dropped names taken out, so a name without a forecast is never dropped
  and is re-weighted with the others, and a book at the cap leaves the
  dropped weight in cash. With nothing dropped the policy's own targets are
  returned untouched, so an overlay with no forecast is the control, bit
  for bit.
* There are no mid-cycle trims: no `weight_filter`, no `midcycle_trims`. A
  dropped name the book holds leaves at the next reset; between resets the
  redeploy buys toward the reduced targets, so it never buys a dropped name.
* What the plan does not gate, and this module leaves as the executor runs
  it: the live mid-cycle breakout entry (`paper._entry_orders`, a band
  breakout in any A/A+ name, sized by the band, paid from cash before the
  redeploy) never reads the allocator, so a dropped name can be bought back
  between resets when cash is on hand, and a reset's sell of a dropped name
  is held back on a green open like every live sell. The payload measures
  it: `drops.held_after_reset_drop` is the weight the book held, at each
  session's close from a reset's fill to the next reset, in the names that
  reset dropped (zero where the drop held).

The forecast row (ticker, t) sits at the panel's row of t (`align`): the
decision made at t's close reads it, and fills at t + 1 as every order of
the executor does. Nothing dated after t is read on row t.

Statistics are `profit_taking`'s: twenty offsets, the costs 10, 16 and 25
bp, the paired daily difference against the control at the median offset
with a Newey-West t at `stage3_io.HAC_LAG`, median CAGR and median worst
drawdown across offsets, offsets above the control, and the exposure
reading of a `midcycle_ew.Ledger` (cash share, the allocator's own idle
share - the overlay's for the overlay - turnover). The windows are the
model window (from the first forecast date through 2023-12-29, the plan's
choosing window for a model decision), 2016-2023, 2024-2026 and all.
`stage3_verdict.s1_reading` gives this run's reading of the criteria it
can judge alone; the ADOPT / RECORD verdict (`stage3_verdict.s1_verdict`)
adds the deflated Sharpe across the outer candidates and the five
single-seed runs (`--seed-column`). Nothing here trades or changes the
executor.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np

from backend.agents.trading.desk import point_in_time, policy_v4, simulate
from backend.cli.market_pit_scorecard import WINDOWS, Curve, _on, _since, window_stats
from backend.market import candidate_stats, profit_taking, stage3_verdict
from backend.market import stage3_io as io
from backend.market.midcycle_ew import (
    DIAGNOSTICS,
    REBALANCE,
    Ledger,
    diagnostics,
    idle_target_path,
)

if TYPE_CHECKING:
    from backend.agents.trading.desk.desk import DeskReport
    from backend.market.panel import Panel

STUDY = "stage3_overlay"
# The control, the live executor with the redeploy, and the overlay's line.
CONTROL = profit_taking.CONTROL
LINE = "s1-overlay"
LINES = (CONTROL, LINE)
# The plan's costs and offsets; the verdict reads 25 bp.
COSTS = stage3_verdict.COSTS
VERDICT_COST_BPS = stage3_verdict.VERDICT_COST_BPS
OFFSETS = stage3_verdict.OFFSETS
HAC_LAG = io.HAC_LAG
# The model window: from the first forecast date up to (not including)
# MODEL_END, i.e. through the last session of 2023.
MODEL = stage3_verdict.MODEL
MODEL_END = date(2024, 1, 1)

assert CONTROL == "ew-redeploy"
assert set(WINDOWS) == {"2016-2023", "2024-2026", "all"}


@dataclass(frozen=True)
class S1Grid:
    """An S1 forecast on the panel's grid, and what placing it found."""

    grid: np.ndarray  # (T, N): row (ticker, t) at the panel's row of t; NaN elsewhere
    rows: int  # forecast rows read
    placed: int  # rows placed on the panel's grid
    off_panel: int  # rows whose date or ticker the panel does not hold
    first: date | None  # the first panel date with a finite forecast
    seed_column: int | None = None  # the single-seed column read, None for the ensemble


# Place an S1 forecast on the panel: row (ticker, date t) goes to panel
# cell [t, ticker], NaN everywhere else; rows whose date or ticker the
# panel lacks are counted and left out. `column`, when given, reads that
# seed's column of `yhat_seeds` instead of the ensemble. A (ticker, date)
# given twice is refused rather than silently overwritten.
def align(
    forecast: io.Stage3Forecast, panel: Panel, column: int | None = None
) -> S1Grid:
    """Return the forecast as an S1Grid on the panel's grid."""
    if forecast.kind != io.S1:
        raise ValueError(f"an S1 forecast is needed; this one is {forecast.kind!r}")
    values = np.asarray(forecast.yhat, dtype=float)
    if column is not None:
        seeds = np.asarray(forecast.yhat_seeds)
        if seeds.ndim != 2 or not 0 <= int(column) < seeds.shape[1]:
            raise ValueError(
                f"seed column {column} is outside the file's "
                f"{seeds.shape[1] if seeds.ndim == 2 else 0} seed columns"
            )
        values = np.asarray(seeds[:, int(column)], dtype=float)
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    rows, names = len(dates), len(panel.tickers)
    days = np.asarray(forecast.dates, dtype="datetime64[D]")
    at = np.searchsorted(dates, days)
    on = (at < rows) & (dates[np.minimum(at, rows - 1)] == days)
    index = {str(t): j for j, t in enumerate(panel.tickers)}
    cols = np.array([index.get(str(t), -1) for t in forecast.tickers], dtype=int)
    on &= cols >= 0
    keys = at[on] * names + cols[on]
    if len(np.unique(keys)) != len(keys):
        raise ValueError("the forecast gives some (ticker, date) more than once")
    grid = np.full((rows, names), np.nan)
    grid[at[on], cols[on]] = values[on]
    covered = np.isfinite(grid).any(axis=1)
    first = dates[np.argmax(covered)].astype(object) if covered.any() else None
    return S1Grid(
        grid=grid,
        rows=int(len(days)),
        placed=int(on.sum()),
        off_panel=int((~on).sum()),
        first=first,
        seed_column=None if column is None else int(column),
    )


# How many of n forecast names the overlay drops: ceil(S1_DROP_SHARE * n)
# once n reaches S1_MIN_NAMES, none below.
def drop_count(n: int) -> int:
    """Return the number of lowest-forecast names dropped from n candidates."""
    n = int(n)
    if n < io.S1_MIN_NAMES:
        return 0
    return int(math.ceil(io.S1_DROP_SHARE * n))


# The overlay on one session's targets: the candidates are the names with a
# positive policy target and a finite forecast; with n >= S1_MIN_NAMES of
# them the drop_count(n) lowest forecasts (ties: lower column first) are
# dropped, and the book is recomputed by the policy's own function
# (`policy_v4.targets`) on the membership row without them - equal weight
# over the reduced set, under the same cap, names without a forecast
# included. With nothing dropped the policy's targets come back untouched.
# Returns (targets, dropped columns, n).
def reduce_targets(
    target: np.ndarray,
    scores: np.ndarray,
    mask_row: np.ndarray,
    grades_row: np.ndarray,
    prices_row: np.ndarray,
    benchmark: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (overlay targets, dropped columns, candidate count) for one session."""
    target = np.asarray(target, dtype=float)
    scores = np.asarray(scores, dtype=float)
    candidates = np.flatnonzero((target > 0) & np.isfinite(scores))
    n = int(len(candidates))
    k = drop_count(n)
    if k == 0:
        return target, np.zeros(0, dtype=int), n
    order = candidates[np.argsort(scores[candidates], kind="stable")]
    dropped = np.sort(order[:k])
    reduced = np.asarray(mask_row, dtype=bool).copy()
    reduced[dropped] = False
    return policy_v4.targets(grades_row, prices_row, reduced, benchmark), dropped, n


class Overlay:
    """The policy's allocator with the lowest-forecast decile of its book dropped.

    `allocator` is the `simulate.run(allocator=...)` callable; `calls`
    records, per session it was asked about, the candidate count and the
    columns it dropped (the simulator asks once per session: at a reset,
    and mid-cycle for the redeploy's targets).
    """

    # Bind the membership mask and the (T, N) forecast grid; the base is
    # always `policy_v4.allocator(mask)`, whose arithmetic `reduce_targets`
    # repeats on the reduced row.
    def __init__(self, mask: np.ndarray, grid: np.ndarray) -> None:
        self.mask = np.asarray(mask, dtype=bool)
        self.grid = np.asarray(grid, dtype=float)
        if self.grid.shape != self.mask.shape:
            raise ValueError(
                f"the forecast grid {self.grid.shape} is not the mask's "
                f"{self.mask.shape}"
            )
        self.base = policy_v4.allocator(self.mask)
        self.calls: dict[int, tuple[int, tuple[int, ...]]] = {}

    # The overlay's targets on `t`: the policy's, with the decile dropped
    # and the rest re-spread, from row t of the mask, grades, prices and
    # forecasts only.
    def allocator(
        self, report: DeskReport, panel: Panel, config: Any, t: int
    ) -> np.ndarray:
        """Return the overlay's target weights on session `t`."""
        t = int(t)
        target = np.asarray(self.base(report, panel, config, t), dtype=float)
        out, dropped, n = reduce_targets(
            target,
            self.grid[t],
            self.mask[t],
            report.graded.grades[t],
            panel.adj_close[t],
            panel.index(panel.benchmark),
        )
        self.calls[t] = (n, tuple(int(c) for c in dropped))
        return out


# The share of equity the overlay's own allocator leaves idle on each
# session (one minus the sum of its targets): the policy's idle share,
# plus what a dropped name leaves in cash when the cap binds.
def overlay_idle_path(
    restricted: DeskReport, mask: np.ndarray, grid: np.ndarray
) -> np.ndarray:
    """Return (T,) idle shares of the overlay's allocator per session."""
    panel = restricted.panel
    overlay = Overlay(mask, grid)
    return np.array(
        [
            max(
                0.0,
                1.0 - float(np.nansum(overlay.allocator(restricted, panel, None, t))),
            )
            for t in range(len(panel.dates))
        ]
    )


# The study's windows: the model window from the first forecast date (an
# empty window when there is none) through 2023, and the scorecard's
# 2016-2023, 2024-2026 and all.
def windows(first: date | None) -> dict[str, tuple[date | None, date | None]]:
    """Return {window: (start, end)} for a first forecast date."""
    start = first if first is not None else MODEL_END
    return {MODEL: (start, MODEL_END), **WINDOWS}


@dataclass
class Priced:
    """One line, one offset, one cost: curve, diagnostics, the overlay's record."""

    curve: Curve
    diagnostics: dict[str, dict[str, float]] = field(default_factory=dict)
    calls: dict[int, tuple[int, tuple[int, ...]]] = field(default_factory=dict)
    kinds: dict[int, str] = field(default_factory=dict)
    # Per session from a reset's fill to the next reset: the weight the
    # book held, at that session's close, in the names that reset dropped.
    held_after_drop: dict[int, float] = field(default_factory=dict)


# The weight the book held, at each session's close from a reset's fill
# (the session after the reset decision) through the next reset, in the
# names that reset dropped: zero where the drop held, above zero where a
# dropped name was still (or again) in the book - its sell held back on a
# green open, or a breakout entry between resets. A name dropped only
# between resets is not counted: without mid-cycle trims it is held to the
# next reset by design.
def _held_after_drop(
    overlay: Overlay, ledger: Ledger, closes: np.ndarray
) -> dict[int, float]:
    """Return {session: weight held in the names the last reset dropped}."""
    resets = sorted(t for t, kind in ledger.kinds.items() if kind == REBALANCE)
    sessions = sorted(ledger.marks)
    out: dict[int, float] = {}
    for i, reset in enumerate(resets):
        dropped = list(overlay.calls.get(reset, (0, ()))[1])
        if not dropped:
            continue
        end = resets[i + 1] if i + 1 < len(resets) else sessions[-1]
        for s in sessions:
            if not reset < s <= end:
                continue
            _, shares, nav, _ = ledger.marks[s]
            value = float(np.nansum(np.asarray(shares)[dropped] * closes[s, dropped]))
            out[s] = value / nav if nav > 0 else math.nan
    return out


# Price one line from one offset at one cost: `simulate.run` on the
# restricted report under the control's options (the live executor with
# the redeploy, `profit_taking.control_options`) with a fresh Ledger, the
# policy's allocator for the control and the overlay's for the overlay -
# nothing else differs, and no weight_filter or mid-cycle trim is passed.
# `idle` is the line's own allocator's idle path, computed once.
def price(
    restricted: DeskReport,
    mask: np.ndarray,
    line: str,
    since: date | None,
    cost_bps: float,
    grid: np.ndarray | None,
    spans: dict[str, tuple[date | None, date | None]],
    idle: np.ndarray | None = None,
) -> Priced:
    """Return the line's Priced result from `since` at `cost_bps`."""
    if line not in LINES:
        raise ValueError(f"unknown line {line!r}")
    panel = restricted.panel
    options = profit_taking.control_options(panel)
    ledger = Ledger()
    ledger.exposure = options.get("event_exposure")
    overlay = None
    if line == CONTROL:
        allocator = policy_v4.allocator(mask)
        ledger.idle = idle_target_path(restricted, mask) if idle is None else idle
    else:
        if grid is None:
            raise ValueError("the overlay needs the forecast grid")
        overlay = Overlay(mask, grid)
        allocator = overlay.allocator
        ledger.idle = (
            overlay_idle_path(restricted, mask, grid) if idle is None else idle
        )
    result = simulate.run(
        restricted,
        since=since,
        cost_bps=cost_bps,
        allocator=allocator,
        journal=ledger,
        **options,
    )
    return Priced(
        Curve(line, result.dates, result.returns),
        {w: diagnostics(ledger, s, e) for w, (s, e) in spans.items()},
        dict(overlay.calls) if overlay is not None else {},
        dict(ledger.kinds),
        _held_after_drop(overlay, ledger, np.asarray(panel.adj_close, dtype=float))
        if overlay is not None
        else {},
    )


# Median over finite entries, NaN when there are none.
def _nanmedian(x: Any) -> float:
    """Return the median of the finite entries, NaN when none."""
    x = np.asarray(x, dtype=float)
    return float(np.nanmedian(x)) if np.isfinite(x).any() else math.nan


# Minimum over finite entries, NaN when there are none.
def _nanmin(x: Any) -> float:
    """Return the minimum of the finite entries, NaN when none."""
    x = np.asarray(x, dtype=float)
    return float(np.nanmin(x)) if np.isfinite(x).any() else math.nan


# Maximum over finite entries, NaN when there are none.
def _nanmax(x: Any) -> float:
    """Return the maximum of the finite entries, NaN when none."""
    x = np.asarray(x, dtype=float)
    return float(np.nanmax(x)) if np.isfinite(x).any() else math.nan


# One row per (line, window) at one cost across the offsets, on the
# control's sessions: the median, worst and best CAGR, the median and
# worst drawdown, the median Sharpe, the offsets whose CAGR beats the
# control's and the median CAGR difference, and the median of each ledger
# diagnostic (the exposure reading).
def summarise(
    priced: list[dict[str, Priced]],
    cost_bps: float,
    spans: dict[str, tuple[date | None, date | None]],
) -> list[dict[str, Any]]:
    """Return the per-window rows of both lines at `cost_bps`."""
    rows: list[dict[str, Any]] = []
    for window, (start, end) in spans.items():
        stats: dict[str, list[dict[str, float]]] = {line: [] for line in LINES}
        for offset in priced:
            base = offset[CONTROL].curve.dates
            keep = point_in_time.window(base, start, end)
            for line in LINES:
                stats[line].append(window_stats(_on(base, offset[line].curve)[keep]))
        control = np.array([s["cagr"] for s in stats[CONTROL]], dtype=float)
        for line in LINES:
            cagrs = np.array([s["cagr"] for s in stats[line]], dtype=float)
            row: dict[str, Any] = {
                "line": line,
                "cost_bps": cost_bps,
                "window": window,
                "offsets": len(priced),
                "median_cagr": _nanmedian(cagrs),
                "worst_cagr": _nanmin(cagrs),
                "best_cagr": _nanmax(cagrs),
                "median_drawdown": _nanmedian([s["drawdown"] for s in stats[line]]),
                "worst_drawdown": _nanmin([s["drawdown"] for s in stats[line]]),
                "median_sharpe": _nanmedian([s["sharpe"] for s in stats[line]]),
                "offsets_above_control": int(np.nansum(cagrs > control)),
                "median_cagr_vs_control": _nanmedian(cagrs - control),
                "sessions": int(np.nanmedian([s["sessions"] for s in stats[line]])),
            }
            for key in DIAGNOSTICS:
                row[key] = _nanmedian(
                    [
                        offset[line].diagnostics.get(window, {}).get(key, math.nan)
                        for offset in priced
                    ]
                )
            rows.append(row)
    return rows


# The paired daily difference of the overlay against the control at the
# median offset, per window: mean bp a day, the Newey-West t at the plan's
# lag, the probabilistic Sharpe, and the excess series' per-period moments
# (what the deflated Sharpe reads).
def paired(
    priced: list[dict[str, Priced]],
    cost_bps: float,
    spans: dict[str, tuple[date | None, date | None]],
) -> list[dict[str, Any]]:
    """Return the paired rows at the median offset for `cost_bps`."""
    out: list[dict[str, Any]] = []
    offset = priced[len(priced) // 2]
    base = offset[CONTROL].curve.dates
    for window, (start, end) in spans.items():
        keep = point_in_time.window(base, start, end)
        diff = (
            _on(base, offset[LINE].curve)[keep] - _on(base, offset[CONTROL].curve)[keep]
        )
        diff = diff[np.isfinite(diff)]
        mom = candidate_stats.moments(diff)
        out.append(
            {
                "cost_bps": cost_bps,
                "window": window,
                "line": LINE,
                "against": CONTROL,
                "sessions": int(len(diff)),
                "mean_daily_bp": float(diff.mean() * 1e4) if len(diff) else math.nan,
                "hac_t": candidate_stats.hac_t(diff, HAC_LAG)
                if len(diff) > 2
                else math.nan,
                "psr": candidate_stats.probabilistic_sharpe(
                    mom.sharpe, mom.length, mom.skew, mom.kurtosis
                ),
                "excess": {
                    "sharpe": mom.sharpe,
                    "skew": mom.skew,
                    "kurtosis": mom.kurtosis,
                    "length": mom.length,
                },
            }
        )
    return out


# What the overlay did at one offset: over every session the simulator
# asked it about and over the resets alone (the ledger's scheduled
# decisions), how many sessions dropped a name, the mean candidate count
# and the mean number dropped; which names were dropped at the resets; and
# how much the book still held, after a reset's fill, in the names that
# reset dropped (the mean and largest weight at the close, and the share
# of those sessions with any).
def drop_stats(run: Priced, tickers: Iterable[str]) -> dict[str, Any]:
    """Return the overlay's drop record at one offset."""
    tickers = list(tickers)
    resets = sorted(t for t, kind in run.kinds.items() if kind == REBALANCE)
    weights = np.array(list(run.held_after_drop.values()), dtype=float)
    weights = weights[np.isfinite(weights)]

    # The drop summary over some sessions the overlay was asked about.
    def summary(sessions: Iterable[int]) -> dict[str, Any]:
        entries = [run.calls[t] for t in sessions if t in run.calls]
        return {
            "sessions": len(entries),
            "with_drops": sum(1 for _, dropped in entries if dropped),
            "mean_candidates": float(np.mean([n for n, _ in entries]))
            if entries
            else math.nan,
            "mean_dropped": float(np.mean([len(d) for _, d in entries]))
            if entries
            else math.nan,
        }

    names = Counter(
        tickers[c] for t in resets if t in run.calls for c in run.calls[t][1]
    )
    return {
        "calls": summary(sorted(run.calls)),
        "resets": summary(resets),
        "dropped_at_resets": dict(names.most_common()),
        "held_after_reset_drop": {
            "sessions": int(len(weights)),
            "mean": float(weights.mean()) if len(weights) else math.nan,
            "max": float(weights.max()) if len(weights) else math.nan,
            "held_share": float((weights > 0).mean()) if len(weights) else math.nan,
        },
    }


# Run both lines at every offset and cost and assemble the payload, with
# this run's reading (`stage3_verdict.s1_reading`). `candidate` is the
# outer candidate's name (s1_<family>) and `identity` the forecast file's
# record. The overlay's drops are kept for the median offset at the
# verdict cost.
def run_overlay(
    restricted: DeskReport,
    mask: np.ndarray,
    s1: S1Grid,
    offsets: int = OFFSETS,
    costs: tuple[float, ...] = COSTS,
    candidate: str = "s1",
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the overlay study's payload."""
    if offsets < 1:
        raise ValueError("offsets must be at least 1")
    panel = restricted.panel
    costs = tuple(float(c) for c in costs)
    verdict_cost = VERDICT_COST_BPS if VERDICT_COST_BPS in costs else max(costs)
    spans = windows(s1.first)
    idle = {
        CONTROL: idle_target_path(restricted, mask),
        LINE: overlay_idle_path(restricted, mask, s1.grid),
    }
    payload: dict[str, Any] = {
        "study": STUDY,
        "plan": io.PLAN,
        "policy": policy_v4.POLICY_VERSION,
        "asof": str(panel.dates[-1]),
        "candidate": candidate,
        "control": CONTROL,
        "line": LINE,
        "seed_column": s1.seed_column,
        "forecast": {
            **(identity or {}),
            "rows": s1.rows,
            "placed": s1.placed,
            "off_panel": s1.off_panel,
            "first_forecast_date": str(s1.first) if s1.first is not None else None,
            "coverage": float(np.isfinite(s1.grid).mean()),
            "seed_column": s1.seed_column,
        },
        "offsets": int(offsets),
        "median_offset": int(offsets) // 2,
        "costs_bps": list(costs),
        "verdict_cost_bps": verdict_cost,
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in spans.items()
        },
        "options": profit_taking._describe(profit_taking.control_options(panel)),
        "rule": {
            "drop_share": io.S1_DROP_SHARE,
            "min_names": io.S1_MIN_NAMES,
            "hold_cap": policy_v4.HOLD_CAP,
            "midcycle_trims": False,
        },
        "hac_lag": HAC_LAG,
        "diagnostics": list(DIAGNOSTICS),
        "rows": [],
        "paired": [],
        "drops": {},
        "note": (
            "The control is ew-redeploy (the live executor with the redeploy of idle "
            "cash, profit_taking.control_options) under policy_v4.allocator(mask); the "
            "overlay is the same run with the allocator wrapped: the lowest-forecast "
            "ceil(0.1 n) of the n >= 5 names with a positive target and a forecast get "
            "no target, the rest the policy's equal weight under the 20% cap; no "
            "mid-cycle trims. Both lines are priced on identical sessions from each of "
            "the first `offsets` sessions; medians and worsts across offsets; paired "
            "statistics at the median offset. The model window runs from the first "
            "forecast date through 2023-12-29."
        ),
    }
    for cost in costs:
        priced: list[dict[str, Priced]] = []
        for k in range(int(offsets)):
            since = _since(panel, k)
            priced.append(
                {
                    line: price(
                        restricted, mask, line, since, cost, s1.grid, spans, idle[line]
                    )
                    for line in LINES
                }
            )
        payload["rows"].extend(summarise(priced, cost, spans))
        payload["paired"].extend(paired(priced, cost, spans))
        if cost == verdict_cost:
            payload["drops"] = drop_stats(priced[len(priced) // 2][LINE], panel.tickers)
    payload["reading"] = stage3_verdict.s1_reading(payload)
    return payload
