"""Adaptive entry: the buy's dip threshold scaled by the name's own volatility.

`docs/research/adaptive-entry-plan-2026-09-30.md` registers everything
here; this module computes nothing the plan did not fix.

**The control.** The board's `dip_or_close` for a buy decided at session
t's close: the first 15-minute bar close of session t+1 at or below
open × (1 − 1%), else the official close of t+1 (`fill_timing.
_dip_or_close_fill`). The orders are stage 4's: every buy of the control
executor (`ew-redeploy`, `stage4_orders`) under `graded-equal-weight/5`
(`policy_v5.allocator(mask)`), from each of 20 start offsets, on the
executed basis, read at the median offset.

**The candidates**, each a same-session rule in t+1 with the official
close of t+1 as the fallback, all buys, σ_t the standard deviation (ddof 1)
of the name's last 20 daily log close-to-close returns through t
(`stage4_labels.NameSeries.sigma`):

- `E1` (`sigma_half`): the first bar close at or below open × (1 − 0.5σ_t);
- `E2` (`sigma_one`): the same at open × (1 − σ_t);
- `E3` (`gap_guard`): the control's 1% rule, except that when
  open_{t+1} < close_t × exp(−2σ_t) (a gap-down of more than two sigma) the
  buy waits for the official close.

**Prices.** Every price is on the panel's adjusted basis: a cube price in
session s is multiplied by `stage4_labels.cube_scale` (the panel's
adjusted close over the cube's own official close that session), never by
`adj_close / close` - the store's close is already split-adjusted, so that
ratio is a dividend factor only, and a raw bar before a split would then
meet an adjusted level. The dip levels are multiples of the same session's
open, so they are compared on the raw bars and the fill is scaled; the gap
guard compares two sessions and reads both on the adjusted basis.

**Validity.** A convention prices an order only when t+1 is a complete cube
session and σ_t is finite; otherwise its price is NaN and the order fills as
the control (g = 0, counted as unpriced). With `next_bar` a fill at a bar's
close moves to the next bar's open (`fill_timing._bar_price`); a fill at
the last bar or at the official close stays at the official close.

**Per order.** g = `stage4_labels.gain(control, candidate, "buy")` in bp of
the order, positive when the candidate pays less. No candidate waits past
t+1, so the wait is 0 and the drift-adjusted reading equals the plain one;
it is computed anyway.

**The book, the windows, the statistics** are stage 4's
(`stage4_decisions`): per offset the sum over the buys decided at t of
weight × g, in bp of equity, over the run's decision sessions; the model
window 2018-01-02..2023-12-29 and 2024-2026 by decision date; at the median
offset (`offsets // 2`) the mean gain a session with its Newey-West t
(lag 20), the per re-timed order (g ≠ 0) mean with its date-clustered t,
the drift-adjusted twin, the splits by grade group and by order detail,
the oracle (the lowest bar close of t+1, and stage 4's five-session one,
reported) and each candidate's capture of it.

**The deflated Sharpe** is `candidate_stats.deflated_sharpe` on the
model-window session series at N = 3 (the registered candidates) with the
across-candidate variance of the three model-window Sharpe ratios, and
beside it at the cumulative 457.

**Verdict** (`verdict`), per candidate: REPLACES when all six criteria
hold at the median offset - (1) the model-window mean ≥ +2.0 bp a session
with t ≥ 2.0; (2) the next-bar run holds the same floor; (3) 2024-2026 not
negative; (4) the deflated Sharpe at N = 3 ≥ 0.95; (5) the drift-adjusted
mean ≥ +1.0 bp at t ≥ 2; (6) positive at 15 of 20 offsets - else RECORD,
or "RECORD: real but immaterial" when (1) fails but the per re-timed order
mean is ≥ 25 bp with a clustered t ≥ 3.

**Reported, never deciding:** the fill's bar distribution, the share of
buys the level reaches (and the share of buys the guard holds to the
close), the reading by grade group and by detail, the oracle capture.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.market import candidate_stats, fill_timing
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

PLAN = "docs/research/adaptive-entry-plan-2026-09-30.md"
STUDY = "adaptive_entry"
SIDE = "buy"
CONTROL = lab.CONTROL
SIGMA_HALF = "sigma_half"
SIGMA_ONE = "sigma_one"
GAP_GUARD = "gap_guard"
# The three registered candidates, in the plan's order, and their rules.
CANDIDATES: dict[str, str] = {"E1": SIGMA_HALF, "E2": SIGMA_ONE, "E3": GAP_GUARD}
CONVENTIONS = (CONTROL, SIGMA_HALF, SIGMA_ONE, GAP_GUARD)
# The rules' constants.
SIGMA_MULTIPLE = {SIGMA_HALF: 0.5, SIGMA_ONE: 1.0}
GAP_SIGMAS = 2.0
DIP = fill_timing.DIP
# The criteria, fixed by the plan (stage 4's for one side, plus the offsets).
FLOOR_BP = sd.FLOOR_BP
FLOOR_T = sd.FLOOR_T
DRIFT_FLOOR_BP = sd.DRIFT_FLOOR_BP
DRIFT_FLOOR_T = sd.DRIFT_FLOOR_T
DSR_GATE = sd.DSR_GATE
IMMATERIAL_BP = sd.IMMATERIAL_BP
IMMATERIAL_T = sd.IMMATERIAL_T
OFFSETS = 20
OFFSETS_POSITIVE = 15
HAC_LAG = sd.HAC_LAG
# The plan's trial counts: three registered candidates, cumulative 457.
TRIALS = {"registered": 3, "cumulative": 457}
# The windows, by decision date.
MODEL = sd.MODEL
REPORTED = sd.REPORTED
MODEL_START = sd.DEFAULT_MODEL_START
# The labels.
REPLACES = sd.REPLACES
RECORD = sd.RECORD
IMMATERIAL = sd.IMMATERIAL
# The reported groups: the grade group and the order detail.
GROUPS = ("grade", "detail")

assert DIP == 0.01
assert HAC_LAG == 20
assert (FLOOR_BP, FLOOR_T, DSR_GATE) == (2.0, 2.0, 0.95)
assert date(2018, 1, 2) == MODEL_START


# --- the fills ---------------------------------------------------------------


@dataclass(frozen=True)
class Fills:
    """One convention's buy fills for every decision session t of one name."""

    price: np.ndarray  # (T,) adjusted fill price in t+1, NaN where it cannot be priced
    reached: np.ndarray  # (T,) bool: filled at its trigger rather than the close
    active: (
        np.ndarray
    )  # (T,) bool: the rule acted (the guard held the buy to the close)
    slot: np.ndarray  # (T,) int: the bar of a trigger fill, -1 at the close or unpriced


# Empty fills for T sessions: nothing priced.
def _empty(length: int) -> Fills:
    """Return unpriced Fills."""
    return Fills(
        np.full(length, np.nan),
        np.zeros(length, dtype=bool),
        np.zeros(length, dtype=bool),
        np.full(length, -1, dtype=np.int64),
    )


# The control and the three rules for every decision session of one name,
# on the adjusted basis: the fill in session t+1 at the first bar close at
# or below a level that is a multiple of t+1's open (compared on the raw
# bars, since a level and its bars share the session), else the official
# close, scaled by `cube_scale` of t+1. The gap guard reads t+1's open and
# t's close both adjusted. A session t whose t+1 is not a complete cube
# session, or whose σ_t is not finite, is unpriced (the control needs no
# σ).
def name_fills(
    series: lab.NameSeries, cube: SessionCube, next_bar: bool = False
) -> dict[str, Fills]:
    """Return {convention: Fills} for one name's buys."""
    length = len(series.dates)
    if not len(cube):
        return {c: _empty(length) for c in CONVENTIONS}
    rows = lab.cube_rows(series.dates, cube)
    scale = lab.cube_scale(series, cube)
    ahead = np.full(length, -1, dtype=np.int64)
    ahead[:-1] = rows[1:]
    scale_ahead = np.full(length, np.nan)
    scale_ahead[:-1] = scale[1:]
    ok = (ahead >= 0) & np.isfinite(scale_ahead)
    valid = ok & np.isfinite(series.sigma)
    open_raw = cube.open[:, 0]
    out: dict[str, Fills] = {}
    # The control: the board's 1% rule on every cube session.
    out[CONTROL] = _place(
        fill_timing._dip_level(cube, SIDE),
        cube,
        ahead,
        scale_ahead,
        ok,
        np.ones(length, dtype=bool),
        next_bar,
    )
    # The sigma dips: the level is a multiple of t+1's open, set by σ_t.
    for name, multiple in SIGMA_MULTIPLE.items():
        level = np.full(len(cube), np.nan)
        level[ahead[valid]] = open_raw[ahead[valid]] * (
            1.0 - multiple * series.sigma[valid]
        )
        out[name] = _place(
            level,
            cube,
            ahead,
            scale_ahead,
            valid,
            np.ones(length, dtype=bool),
            next_bar,
        )
    # The gap guard: the control's level, or no level (the official close)
    # when t+1 opens more than 2σ below t's adjusted close.
    open_adjusted = np.full(length, np.nan)
    open_adjusted[valid] = open_raw[ahead[valid]] * scale_ahead[valid]
    with np.errstate(invalid="ignore"):
        gap = valid & (
            open_adjusted < series.close * np.exp(-GAP_SIGMAS * series.sigma)
        )
    level = np.full(len(cube), np.nan)
    keep = valid & ~gap
    level[ahead[keep]] = open_raw[ahead[keep]] * (1.0 - DIP)
    out[GAP_GUARD] = _place(level, cube, ahead, scale_ahead, valid, gap, next_bar)
    return out


# One convention's fills from its per-cube-row level: `fill_timing.
# _first_close_past` on the cube (a NaN level never fills at a bar, so it
# is the official close), read at each priced session's t+1 row and
# scaled onto the adjusted basis.
def _place(
    level: np.ndarray,
    cube: SessionCube,
    ahead: np.ndarray,
    scale_ahead: np.ndarray,
    priced: np.ndarray,
    active: np.ndarray,
    next_bar: bool,
) -> Fills:
    """Return the Fills of one level."""
    length = len(ahead)
    raw, hit = fill_timing._first_close_past(cube, SIDE, level, next_bar)
    _, first = fill_timing._first_past(cube, SIDE, level)
    fills = _empty(length)
    price, reached, slot = fills.price, fills.reached, fills.slot
    idx = np.flatnonzero(priced)
    price[idx] = raw[ahead[idx]] * scale_ahead[idx]
    reached[idx] = hit[ahead[idx]]
    slot[idx] = np.where(hit[ahead[idx]], first[ahead[idx]], -1)
    return Fills(price, reached, np.asarray(active, dtype=bool) & priced, slot)


@dataclass(frozen=True)
class Grid:
    """Every (session, name)'s buy fills under one fill mode, on the panel's grid."""

    next_bar: bool
    price: dict[str, np.ndarray]  # convention -> (T, N) adjusted price, NaN unpriced
    reached: dict[str, np.ndarray]  # -> (T, N) bool
    active: dict[str, np.ndarray]  # -> (T, N) bool
    slot: dict[str, np.ndarray]  # -> (T, N) int


# Every name's fills on the panel's grid, with bar-close fills and with
# next-bar fills, the same-session oracle (the lowest bar close of t+1) and
# stage 4's five-session oracle: `stage4_labels.name_series` per name with
# a cube; a name without one is unpriced.
def fill_grids(
    panel: Any, cubes: Mapping[str, SessionCube]
) -> tuple[Grid, Grid, np.ndarray, np.ndarray, dict[str, Any]]:
    """Return (bar-close grid, next-bar grid, (T, N) oracle, (T, N) five-session
    oracle, coverage)."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    grids = {
        mode: Grid(
            next_bar=mode,
            price={c: np.full(shape, np.nan) for c in CONVENTIONS},
            reached={c: np.zeros(shape, dtype=bool) for c in CONVENTIONS},
            active={c: np.zeros(shape, dtype=bool) for c in CONVENTIONS},
            slot={c: np.full(shape, -1, dtype=np.int64) for c in CONVENTIONS},
        )
        for mode in (False, True)
    }
    oracle = np.full(shape, np.nan)
    oracle_five = np.full(shape, np.nan)
    covered: list[str] = []
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(str(ticker))
        if cube is None or not len(cube):
            continue
        series = lab.name_series(
            dates,
            panel.close[:, j],
            panel.adj_close[:, j],
            panel.high[:, j],
            panel.low[:, j],
        )
        for mode, grid in grids.items():
            for name, fills in name_fills(series, cube, next_bar=mode).items():
                grid.price[name][:, j] = fills.price
                grid.reached[name][:, j] = fills.reached
                grid.active[name][:, j] = fills.active
                grid.slot[name][:, j] = fills.slot
        oracle[:, j] = sd.oracle_prices(series, cube, 1)[SIDE]
        oracle_five[:, j] = sd.oracle_prices(series, cube, lab.WINDOW)[SIDE]
        covered.append(str(ticker))
    first = min((cubes[t].dates[0] for t in covered), default=None)
    coverage = {
        "names_with_cube": len(covered),
        "names_without_cube": sorted(
            str(t) for t in panel.tickers if str(t) not in set(covered)
        ),
        "first_cube_date": str(first) if first is not None else None,
    }
    return grids[False], grids[True], oracle, oracle_five, coverage


@dataclass(frozen=True)
class Market:
    """Everything the engine reads besides the orders, on the panel's (T, N) grid."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    fills: Grid  # bar-close fills
    next_bar: Grid  # next-bar fills
    oracle: np.ndarray  # (T, N) the lowest bar close of t+1, adjusted
    oracle_five: np.ndarray  # (T, N) stage 4's oracle over t+1..t+5
    grades: np.ndarray  # (T, N) the desk grade of the report the orders came from
    closes: np.ndarray  # (T, N) adjusted closes (the drift)


# Assemble the Market from the panel, its grades and the grids.
def build_market(
    panel: Any,
    grades: np.ndarray,
    fills: Grid,
    next_bar: Grid,
    oracle: np.ndarray,
    oracle_five: np.ndarray,
) -> Market:
    """Return the Market."""
    if fills.next_bar or not next_bar.next_bar:
        raise ValueError(
            "fills must be the bar-close grid and next_bar the next-bar grid"
        )
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    if np.asarray(grades).shape != shape or np.shape(oracle) != shape:
        raise ValueError("the grades and the oracle must be on the panel's grid")
    return Market(
        dates=dates,
        tickers=tuple(str(t) for t in panel.tickers),
        fills=fills,
        next_bar=next_bar,
        oracle=np.asarray(oracle, dtype=float),
        oracle_five=np.asarray(oracle_five, dtype=float),
        grades=np.asarray(grades),
        closes=np.asarray(panel.adj_close, dtype=float),
    )


# --- pricing one candidate ----------------------------------------------------


@dataclass(frozen=True)
class Book(sd.Book):
    """Stage 4's Book with the rule's own reading: the trigger, its bar, the oracle."""

    reached: (
        np.ndarray
    )  # (K,) bool: the level was reached (the control's for E3 outside a gap)
    slot: np.ndarray  # (K,) int: the bar of a trigger fill, -1 otherwise
    oracle_five: (
        np.ndarray
    )  # (K,) stage 4's oracle gain over the control, bp; NaN unpriced


# The rule of a candidate name, refused when unknown.
def rule_of(candidate: str) -> str:
    """Return the convention of "E<k>"."""
    if candidate not in CANDIDATES:
        raise ValueError(
            f"unknown candidate {candidate!r}; registered: {', '.join(CANDIDATES)}"
        )
    return CANDIDATES[candidate]


# Price one candidate on one run's buys: the candidate's fill against the
# control's per order, g, and the counts. An order whose candidate or
# control has no price fills as the control (g = 0) and is counted.
def price_book(
    orders: so.Orders, market: Market, candidate: str, next_bar: bool = False
) -> Book:
    """Return the candidate's Book on the orders."""
    rule = rule_of(candidate)
    grid = market.next_bar if next_bar else market.fills
    rows = np.flatnonzero(orders.buy)
    t = orders.session[rows]
    j = orders.column[rows]
    control = grid.price[CONTROL][t, j]
    price = grid.price[rule][t, j]
    unpriced = ~np.isfinite(control) | ~np.isfinite(price)
    gain = np.where(unpriced, 0.0, lab.gain(control, price, SIDE))
    k = len(rows)
    return Book(
        candidate=candidate,
        side=SIDE,
        start=orders.start,
        stop=orders.stop,
        rows=rows,
        session=t,
        weight=orders.weight[rows],
        gain=gain,
        wait=np.zeros(k, dtype=np.int64),
        acted=grid.active[rule][t, j] & ~unpriced,
        unpriced=unpriced,
        no_forecast=np.zeros(k, dtype=bool),
        oracle=lab.gain(control, market.oracle[t, j], SIDE),
        reached=grid.reached[rule][t, j] & ~unpriced,
        slot=np.where(unpriced, -1, grid.slot[rule][t, j]).astype(np.int64),
        oracle_five=lab.gain(control, market.oracle_five[t, j], SIDE),
    )


# --- statistics ----------------------------------------------------------------


# Stage 4's statistics of a book over one window (`stage4_decisions.
# summarize`), plus the rule's own: the priced orders, those whose trigger
# was reached and the share, the orders the rule acted on (the guard's
# holds for E3), the bar distribution of the trigger fills, and the
# five-session oracle's mean gain.
def summarize(
    book: Book,
    dates: np.ndarray,
    lo: date | None,
    hi: date | None,
    mu_bp: float,
    subset: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return the statistics of one window."""
    out = sd.summarize(book, dates, lo, hi, mu_bp, subset)
    keep_sessions = sd.session_window(book, dates, lo, hi)
    chosen = (
        np.ones(len(book.session), dtype=bool)
        if subset is None
        else np.asarray(subset, dtype=bool)
    )
    inside = (
        chosen & keep_sessions[book.session - book.start]
        if len(book.session)
        else chosen
    )
    priced = inside & ~book.unpriced
    reached = priced & book.reached
    bars = np.bincount(
        book.slot[reached & (book.slot >= 0)], minlength=FULL_SESSION_SLOTS
    )[:FULL_SESSION_SLOTS]
    five = inside & np.isfinite(book.oracle_five)
    out.update(
        {
            "priced": int(priced.sum()),
            "reached": int(reached.sum()),
            "reached_share": float(reached.sum() / priced.sum())
            if priced.any()
            else math.nan,
            "acted_share": float((priced & book.acted).sum() / priced.sum())
            if priced.any()
            else math.nan,
            "bars": [int(v) for v in bars],
            "oracle_five_bp": sd._mean(book.oracle_five[five]),
        }
    )
    return out


# The same statistics per grade group and per order detail of a book's
# buys, per window (`stage4_decisions.order_groups`' labels).
def splits(
    book: Book,
    groups: Mapping[str, np.ndarray],
    dates: np.ndarray,
    spans: Mapping[str, tuple[date | None, date | None]],
    mus: Mapping[str, float],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return {group: {label: {window: statistics}}}."""
    values = sd.group_values(SIDE)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for group in GROUPS:
        mine = np.asarray(groups[group])[book.rows]
        out[group] = {
            label: {
                window: summarize(
                    book, dates, lo, hi, mus[window], subset=mine == label
                )
                for window, (lo, hi) in spans.items()
            }
            for label in values[group]
        }
    return out


# The deflated Sharpe of one candidate's model-window session series at
# the plan's trial counts: the gate at N = 3, the trial variance the
# across-candidate variance (ddof 1) of the three model-window Sharpe
# ratios; the cumulative 457 beside it. NaN with fewer than two finite
# Sharpes.
def deflated(excess: Mapping[str, Mapping[str, Any]], candidate: str) -> dict[str, Any]:
    """Return the deflated Sharpe record of `candidate`."""
    sharpes = np.array(
        [sd._f((e or {}).get("sharpe")) for e in excess.values()], dtype=float
    )
    sharpes = sharpes[np.isfinite(sharpes)]
    variance = float(sharpes.var(ddof=1)) if len(sharpes) >= 2 else math.nan
    own = excess.get(candidate) or {}
    sharpe = sd._f(own.get("sharpe"))
    length = int(own.get("length") or 0)
    skew = sd._f(own.get("skew"))
    kurtosis = sd._f(own.get("kurtosis"))
    values = {
        label: candidate_stats.deflated_sharpe(
            sharpe, length, skew, kurtosis, trials, variance
        )
        if math.isfinite(variance) and math.isfinite(sharpe)
        else math.nan
        for label, trials in TRIALS.items()
    }
    dsr = values["registered"]
    return {
        "candidate": candidate,
        "sharpe": sharpe,
        "length": length,
        "candidates": int(len(sharpes)),
        "trial_variance": variance,
        "trials": TRIALS["registered"],
        "dsr": dsr,
        "dsr_cumulative": values["cumulative"],
        "gate": DSR_GATE,
        "passes": bool(math.isfinite(dsr) and dsr >= DSR_GATE),
    }


# --- the whole test --------------------------------------------------------------


# The per-order rows of the median offset's buys, for an independent
# recomputation: the order's date, ticker, weight, detail and grade, the
# run's decision dates, and per candidate the control and candidate
# fills, g (bar-close and next-bar) and the flags.
def order_rows(
    orders: so.Orders, market: Market, books: Mapping[str, tuple[Book, Book]]
) -> dict[str, Any]:
    """Return the payload's "rows" block."""
    rows = np.flatnonzero(orders.buy)
    t = orders.session[rows]
    j = orders.column[rows]
    control = market.fills.price[CONTROL][t, j]
    out: dict[str, Any] = {
        "sessions": [str(d) for d in market.dates[orders.start : orders.stop]],
        "date": [str(d) for d in market.dates[t]],
        "ticker": orders.ticker[rows].tolist(),
        "weight": orders.weight[rows].tolist(),
        "detail": orders.detail[rows].tolist(),
        "grade": orders.grade[rows].tolist(),
        "control": control.tolist(),
        "candidates": {},
    }
    for candidate, (book, nb) in books.items():
        if not np.array_equal(book.rows, rows):
            raise ValueError("the books must be priced on the same orders")
        out["candidates"][candidate] = {
            "fill": market.fills.price[rule_of(candidate)][t, j].tolist(),
            "g_bp": book.gain.tolist(),
            "next_bar_g_bp": nb.gain.tolist(),
            "reached": book.reached.tolist(),
            "acted": book.acted.tolist(),
            "unpriced": book.unpriced.tolist(),
            "slot": book.slot.tolist(),
        }
    return out


# Price every candidate on every offset's buys and assemble the payload:
# per offset the model-window and 2024-2026 means (and the next-bar
# model-window mean); at the median offset every statistic, the next-bar
# run, the splits, the oracle and the per-order rows; the deflated Sharpe
# and the verdict. `registered` is the plan's offset count; a run over
# fewer offsets is a smoke run and says so.
def evaluate(
    runs: Sequence[so.Orders], market: Market, registered: int = OFFSETS
) -> dict[str, Any]:
    """Return the study's payload."""
    if not runs:
        raise ValueError("no offsets were priced")
    bases = {o.basis for o in runs}
    if len(bases) != 1:
        raise ValueError(f"the offsets' orders mix bases: {sorted(bases)}")
    spans = sd.windows(MODEL_START)
    median = len(runs) // 2
    dates = market.dates
    drifts = {w: sd.drift(market, lo, hi) for w, (lo, hi) in spans.items()}
    mus = {w: d["mu_bp"] for w, d in drifts.items()}
    per_offset: dict[str, dict[str, list[float]]] = {
        c: {"model_bp": [], "reported_bp": [], "next_bar_model_bp": []}
        for c in CANDIDATES
    }
    for orders in runs:
        for c in CANDIDATES:
            book = price_book(orders, market, c)
            nb = price_book(orders, market, c, next_bar=True)
            per_offset[c]["model_bp"].append(sd.window_mean(book, dates, *spans[MODEL]))
            per_offset[c]["reported_bp"].append(
                sd.window_mean(book, dates, *spans[REPORTED])
            )
            per_offset[c]["next_bar_model_bp"].append(
                sd.window_mean(nb, dates, *spans[MODEL])
            )
    at_median = runs[median]
    groups = sd.order_groups(at_median, np.full(len(dates), np.nan))
    results: dict[str, dict[str, Any]] = {}
    books: dict[str, tuple[Book, Book]] = {}
    for c in CANDIDATES:
        book = price_book(at_median, market, c)
        nb = price_book(at_median, market, c, next_bar=True)
        books[c] = (book, nb)
        results[c] = {
            "default": {
                w: summarize(book, dates, lo, hi, mus[w])
                for w, (lo, hi) in spans.items()
            },
            "next_bar": {
                w: summarize(nb, dates, lo, hi, mus[w]) for w, (lo, hi) in spans.items()
            },
            "splits": splits(book, groups, dates, spans, mus),
            "across_offsets": sd._across(per_offset[c]["model_bp"]),
            "across_offsets_2024_2026": sd._across(per_offset[c]["reported_bp"]),
        }
    excess = {c: results[c]["default"][MODEL]["excess"] for c in CANDIDATES}
    payload: dict[str, Any] = {
        "study": STUDY,
        "plan": PLAN,
        "asof": str(dates[-1]) if len(dates) else None,
        "control": {
            "executor": so.CONTROL,
            "policy": "graded-equal-weight/5",
            "fills": "dip_or_close",
            "dip": DIP,
            "basis": runs[0].basis,
            "side": SIDE,
        },
        "offsets": {
            "registered": int(registered),
            "priced": len(runs),
            "median": median,
            "smoke": len(runs) < int(registered),
            "starts": [int(o.start) for o in runs],
        },
        "windows": {
            w: [str(lo) if lo else None, str(hi) if hi else None]
            for w, (lo, hi) in spans.items()
        },
        "hac_lag": HAC_LAG,
        "constants": {
            "SIGMA_MULTIPLE": SIGMA_MULTIPLE,
            "GAP_SIGMAS": GAP_SIGMAS,
            "SIGMA_SESSIONS": lab.SIGMA_SESSIONS,
            "FLOOR_BP": FLOOR_BP,
            "FLOOR_T": FLOOR_T,
            "DRIFT_FLOOR_BP": DRIFT_FLOOR_BP,
            "DRIFT_FLOOR_T": DRIFT_FLOOR_T,
            "DSR_GATE": DSR_GATE,
            "IMMATERIAL_BP": IMMATERIAL_BP,
            "IMMATERIAL_T": IMMATERIAL_T,
            "OFFSETS_POSITIVE": OFFSETS_POSITIVE,
            "TRIALS": TRIALS,
            "expected_best_null_t": {
                k: candidate_stats.expected_max_sharpe(n, 1.0)
                for k, n in TRIALS.items()
            },
        },
        "candidates": {c: {"rule": r, "side": SIDE} for c, r in CANDIDATES.items()},
        "drift": drifts,
        "orders": {
            "per_offset": [so.order_counts(o) for o in runs],
            "median_by_window": {
                w: so.order_counts(
                    at_median.subset(
                        point_in_time.window(dates[at_median.session], lo, hi)
                    ),
                    int(
                        point_in_time.window(
                            dates[at_median.start : at_median.stop], lo, hi
                        ).sum()
                    ),
                )
                for w, (lo, hi) in spans.items()
            },
        },
        "per_offset": per_offset,
        "results": results,
        "deflated": {c: deflated(excess, c) for c in CANDIDATES},
        "rows": order_rows(at_median, market, books),
    }
    payload["verdict"] = verdict(payload)
    return payload


# --- the verdict ---------------------------------------------------------------


# The plan's six criteria for one candidate at the median offset: the
# model-window floor, the next-bar floor, 2024-2026 not negative, the
# deflated Sharpe gate at N = 3, the drift-adjusted floor and the count of
# positive offsets.
def criteria_of(result: Mapping[str, Any], dsr: Mapping[str, Any]) -> dict[str, bool]:
    """Return {criterion: passes}."""
    model = result["default"][MODEL]
    later = sd._f(result["default"][REPORTED]["mean_bp"])
    bar = result["next_bar"][MODEL]
    positive = int(result["across_offsets"]["positive"])
    return {
        "1_floor": sd.clears(model["mean_bp"], model["hac_t"]),
        "2_next_bar": sd.clears(bar["mean_bp"], bar["hac_t"]),
        "3_not_negative_2024_2026": bool(math.isfinite(later) and later >= 0.0),
        "4_deflated_sharpe": bool(dsr["passes"]),
        "5_drift_adjusted": sd.clears(
            model["drift_mean_bp"], model["drift_hac_t"], DRIFT_FLOOR_BP, DRIFT_FLOOR_T
        ),
        "6_offsets_positive": positive >= OFFSETS_POSITIVE,
    }


# One candidate's verdict record: REPLACES when all six criteria hold,
# "RECORD: real but immaterial" when the floor fails but the re-timed
# orders gain at least 25 bp at a clustered t of 3, else RECORD - with the
# numbers behind it.
def judge(result: Mapping[str, Any], dsr: Mapping[str, Any]) -> dict[str, Any]:
    """Return the candidate's label, criteria and numbers."""
    criteria = criteria_of(result, dsr)
    model = result["default"][MODEL]
    bar = result["next_bar"][MODEL]
    later = result["default"][REPORTED]
    across = result["across_offsets"]
    per_order = sd.clears(
        model["retimed_bp"], model["retimed_t"], IMMATERIAL_BP, IMMATERIAL_T
    )
    real = bool(not criteria["1_floor"] and per_order)
    label = REPLACES if all(criteria.values()) else (IMMATERIAL if real else RECORD)
    return {
        "label": label,
        "criteria": criteria,
        "real_but_immaterial": real,
        "model_bp": sd._f(model["mean_bp"]),
        "model_t": sd._f(model["hac_t"]),
        "next_bar_bp": sd._f(bar["mean_bp"]),
        "next_bar_t": sd._f(bar["hac_t"]),
        "reported_bp": sd._f(later["mean_bp"]),
        "reported_t": sd._f(later["hac_t"]),
        "dsr": sd._f(dsr["dsr"]),
        "dsr_cumulative": sd._f(dsr["dsr_cumulative"]),
        "drift_bp": sd._f(model["drift_mean_bp"]),
        "drift_t": sd._f(model["drift_hac_t"]),
        "offsets_positive": int(across["positive"]),
        "offsets": int(across["offsets"]),
        "retimed_bp": sd._f(model["retimed_bp"]),
        "retimed_t": sd._f(model["retimed_t"]),
        "orders": int(model["orders"]),
        "retimed": int(model["retimed"]),
        "reached_share": sd._f(model["reached_share"]),
        "acted_share": sd._f(model["acted_share"]),
        "capture": sd._f(model["capture"]),
    }


# The plan's verdict per candidate from the payload, one line each, and the
# headline; a smoke run's headline says it is not the registered test.
def verdict(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return {"candidates", "replaces", "immaterial", "lines", "text"}."""
    candidates = {
        c: judge(payload["results"][c], payload["deflated"][c]) for c in CANDIDATES
    }
    replaces = [c for c, v in candidates.items() if v["label"] == REPLACES]
    immaterial = [c for c, v in candidates.items() if v["label"] == IMMATERIAL]
    return {
        "candidates": candidates,
        "replaces": replaces,
        "immaterial": immaterial,
        "lines": [_line(c, v) for c, v in candidates.items()],
        "text": _headline(payload.get("offsets") or {}, replaces, immaterial),
    }


# The verdict's headline: which candidates replace the board's buy rule,
# or that none does, and which are real but immaterial.
def _headline(
    offsets: Mapping[str, Any], replaces: Sequence[str], immaterial: Sequence[str]
) -> str:
    """Return the headline text."""
    head = ""
    if offsets.get("smoke"):
        head = (
            f"SMOKE RUN ({offsets.get('priced')} of {offsets.get('registered')} "
            "offsets): not the registered test. "
        )
    if replaces:
        head += (
            f"{REPLACES}: {', '.join(replaces)} clear every criterion against "
            "dip_or_close for buys; a live change needs a separate registration "
            "and the operator's go-ahead"
        )
    else:
        head += (
            f"{RECORD}: no candidate clears every criterion; the board keeps the "
            "fixed 1% dip_or_close"
        )
    if immaterial:
        head += f". {IMMATERIAL}: {', '.join(immaterial)}"
    return head


# One candidate's verdict line, stage-4 style: each criterion's number, the
# reported shares, then the label.
def _line(candidate: str, info: Mapping[str, Any]) -> str:
    """Return the candidate's verdict line."""
    signed, share = sd._signed, sd._share
    holds = "holds" if info["criteria"]["2_next_bar"] else "fails"
    rule = CANDIDATES[candidate]
    acted = "guard held" if rule == GAP_GUARD else "level reached"
    acted_share = info["acted_share" if rule == GAP_GUARD else "reached_share"]
    parts = [
        f"model window {signed(info['model_bp'], 1)} bp/session "
        f"(t {signed(info['model_t'])})",
        f"next-bar {signed(info['next_bar_bp'], 1)} "
        f"(t {signed(info['next_bar_t'])}) {holds}",
        f"{REPORTED} {signed(info['reported_bp'], 1)} bp/session",
        f"deflated Sharpe {signed(info['dsr'])} at N = {TRIALS['registered']} "
        f"({signed(info['dsr_cumulative'])} at {TRIALS['cumulative']})",
        f"drift-adjusted {signed(info['drift_bp'], 1)} (t {signed(info['drift_t'])})",
        f"positive at {info['offsets_positive']} of {info['offsets']} offsets",
        f"per re-timed order {signed(info['retimed_bp'], 1)} bp "
        f"(t {signed(info['retimed_t'])}) "
        f"over {info['retimed']} of {info['orders']} orders",
        f"{acted} {share(acted_share)}",
        f"oracle capture {share(info['capture'])}",
    ]
    return f"{candidate} ({rule}): {'; '.join(parts)} - {info['label']}"
