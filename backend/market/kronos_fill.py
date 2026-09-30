"""Kronos K2: the predicted next-session path as a fill rule, priced on stage 4's book.

`docs/research/kronos-plan-2026-09-30.md` registers the arm; Addendum 1
fixes the cutoff and Addendum 2 the build choices here. The harness is
`adaptive_entry`'s (the control, the orders, the book, the statistics,
the six criteria), with two candidates and the model window moved to the
post-cutoff sessions.

**The control** is the board's `dip_or_close` in session t+1 on each side:
a buy at the first bar close at or below open x 0.99, a sell at the first
at or above open x 1.01, else the official close.

**The candidates.** The RTX writes, per graded cell (t, name), the
predicted session low, high and open of t+1 from the last 512 15-minute
bars through t. `K2_buy` (`kronos_low`): the dip level is t+1's actual
open times the predicted low over the predicted open, capped at open x
0.97 and floored at the control's open x 0.99 (the plan), so the rule
waits for a deeper dip than 1% only when the model predicts one and never
for more than 3%; the fill is the first bar close at or below that level,
else the official close. `K2_sell` (`kronos_high`): the mirror with the
predicted high over the predicted open, in [open x 1.01, open x 1.03]. A
cell without a forecast fills as the control (g = 0, counted as
`no_forecast`).

**Prices** are on the panel's adjusted basis via `stage4_labels.
cube_scale`; the level is a multiple of t+1's own open, so it is compared
on the raw bars and the fill is scaled. A session t whose t+1 is not a
complete cube session is unpriced.

**The windows.** The model window is the post-cutoff sessions
2024-07-01 onwards (Addendum 1); the contaminated window 2018-01-02..
2024-06-30 is reported. The plan's S1 criteria (adaptive_entry's six)
apply at the median of 20 offsets, with criterion 3 ("2024-2026 not
negative") read on the contaminated window, the only other window there
is, and the deflated Sharpe at N = 2 (the plan's two trials) with the
across-candidate variance of the two candidates' model-window Sharpe
ratios, the cumulative 466 beside it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.market import adaptive_entry as ae
from backend.market import candidate_stats, fill_timing
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market.sip_cube import SessionCube

PLAN = "docs/research/kronos-plan-2026-09-30.md"
STUDY = "kronos_fill"
CONTROL = lab.CONTROL
BUY, SELL = "buy", "sell"
SIDES = (BUY, SELL)
KRONOS_LOW = "kronos_low"
KRONOS_HIGH = "kronos_high"
CANDIDATES: dict[str, tuple[str, str]] = {
    "K2_buy": (KRONOS_LOW, BUY),
    "K2_sell": (KRONOS_HIGH, SELL),
}
KEYS: tuple[tuple[str, str], ...] = ((CONTROL, BUY), (CONTROL, SELL)) + tuple(
    CANDIDATES.values()
)
DIP = fill_timing.DIP
# The plan's cap: never wait for more than a 3% dip (pop).
CAP = 0.03
# Addendum 1: the post-cutoff sessions are the model window.
POST_START = date(2024, 7, 1)
MODEL_START = sd.DEFAULT_MODEL_START
MODEL = "model"
CONTAMINATED = "contaminated"
# The criteria, stage 4's for one side, plus the offsets.
FLOOR_BP = sd.FLOOR_BP
FLOOR_T = sd.FLOOR_T
DRIFT_FLOOR_BP = sd.DRIFT_FLOOR_BP
DRIFT_FLOOR_T = sd.DRIFT_FLOOR_T
DSR_GATE = sd.DSR_GATE
IMMATERIAL_BP = sd.IMMATERIAL_BP
IMMATERIAL_T = sd.IMMATERIAL_T
OFFSETS = ae.OFFSETS
OFFSETS_POSITIVE = ae.OFFSETS_POSITIVE
HAC_LAG = sd.HAC_LAG
TRIALS = {"registered": 2, "cumulative": 466}
REPLACES = sd.REPLACES
RECORD = sd.RECORD
IMMATERIAL = sd.IMMATERIAL
GROUPS = ae.GROUPS

assert DIP == 0.01 and CAP == 0.03
assert (FLOOR_BP, FLOOR_T, DSR_GATE, OFFSETS, OFFSETS_POSITIVE) == (
    2.0,
    2.0,
    0.95,
    20,
    15,
)


# The study's windows by decision date: the post-cutoff model window and
# the contaminated window before it.
def windows() -> dict[str, tuple[date | None, date | None]]:
    """Return {window: (start, end)}, end exclusive."""
    return {MODEL: (POST_START, None), CONTAMINATED: (MODEL_START, POST_START)}


# --- the fills -------------------------------------------------------------------


@dataclass(frozen=True)
class Fills:
    """One (rule, side)'s fills for every decision session t of one name."""

    price: np.ndarray  # (T,) adjusted fill price, NaN where it cannot be priced
    reached: np.ndarray  # (T,) bool: filled at its trigger rather than the close
    active: np.ndarray  # (T,) bool: the rule had a forecast (its level may differ)
    slot: np.ndarray  # (T,) int: the bar of a trigger fill, -1 at the close or unpriced
    level_ratio: np.ndarray  # (T,) the level over t+1's open, NaN without a forecast


# Empty fills for T sessions: nothing priced.
def _empty(length: int) -> Fills:
    """Return unpriced Fills."""
    return Fills(
        np.full(length, np.nan),
        np.zeros(length, dtype=bool),
        np.zeros(length, dtype=bool),
        np.full(length, -1, dtype=np.int64),
        np.full(length, np.nan),
    )


# The level ratio of a side from the predicted extreme over the predicted
# open: a buy's low ratio clipped to [1 - CAP, 1 - DIP], a sell's high
# ratio to [1 + DIP, 1 + CAP]; NaN stays NaN.
def level_ratio(predicted: np.ndarray, side: str) -> np.ndarray:
    """Return the (T,) clipped level ratio."""
    r = np.asarray(predicted, dtype=float)
    if side == BUY:
        return np.clip(r, 1.0 - CAP, 1.0 - DIP)
    return np.clip(r, 1.0 + DIP, 1.0 + CAP)


# One rule's fills from a per-cube-row level: `fill_timing._first_close_
# past` on the cube (a NaN level never fills at a bar, so it is the
# official close), read at each priced session's t+1 row and scaled onto
# the adjusted basis.
def _place(
    level: np.ndarray,
    cube: SessionCube,
    side: str,
    ahead: np.ndarray,
    scale_ahead: np.ndarray,
    priced: np.ndarray,
    active: np.ndarray,
    ratio: np.ndarray,
    next_bar: bool,
) -> Fills:
    """Return the Fills of one level."""
    raw, hit = fill_timing._first_close_past(cube, side, level, next_bar)
    _, first = fill_timing._first_past(cube, side, level)
    out = _empty(len(ahead))
    idx = np.flatnonzero(priced)
    out.price[idx] = raw[ahead[idx]] * scale_ahead[idx]
    out.reached[idx] = hit[ahead[idx]]
    out.slot[idx] = np.where(hit[ahead[idx]], first[ahead[idx]], -1)
    out.active[idx] = np.asarray(active, dtype=bool)[idx]
    out.level_ratio[idx] = np.asarray(ratio, dtype=float)[idx]
    return out


# The control and the two K2 rules for every decision session of one
# name, on the adjusted basis. `low_ratio` and `high_ratio` are the (T,)
# predicted low and high over the predicted open at each t (NaN: no
# forecast, the control's level). A session t whose t+1 is not a complete
# cube session is unpriced.
def name_fills(
    series: lab.NameSeries,
    cube: SessionCube,
    low_ratio: np.ndarray,
    high_ratio: np.ndarray,
    next_bar: bool = False,
) -> dict[tuple[str, str], Fills]:
    """Return {(rule, side): Fills} for one name."""
    length = len(series.dates)
    if not len(cube):
        return {key: _empty(length) for key in KEYS}
    rows = lab.cube_rows(series.dates, cube)
    scale = lab.cube_scale(series, cube)
    ahead = np.full(length, -1, dtype=np.int64)
    ahead[:-1] = rows[1:]
    scale_ahead = np.full(length, np.nan)
    scale_ahead[:-1] = scale[1:]
    ok = (ahead >= 0) & np.isfinite(scale_ahead)
    open_raw = cube.open[:, 0]
    out: dict[tuple[str, str], Fills] = {}
    control_ratio = {BUY: 1.0 - DIP, SELL: 1.0 + DIP}
    for side, predicted, rule in (
        (BUY, low_ratio, KRONOS_LOW),
        (SELL, high_ratio, KRONOS_HIGH),
    ):
        out[(CONTROL, side)] = _place(
            fill_timing._dip_level(cube, side),
            cube,
            side,
            ahead,
            scale_ahead,
            ok,
            np.ones(length, dtype=bool),
            np.full(length, control_ratio[side]),
            next_bar,
        )
        ratio = level_ratio(predicted, side)
        has = ok & np.isfinite(ratio)
        used = np.where(has, ratio, control_ratio[side])
        level = np.full(len(cube), np.nan)
        level[ahead[ok]] = open_raw[ahead[ok]] * used[ok]
        out[(rule, side)] = _place(
            level,
            cube,
            side,
            ahead,
            scale_ahead,
            ok,
            has,
            np.where(has, ratio, np.nan),
            next_bar,
        )
    return out


@dataclass(frozen=True)
class Grid:
    """Every (session, name)'s fills under one fill mode, on the panel's grid."""

    next_bar: bool
    price: dict[tuple[str, str], np.ndarray]
    reached: dict[tuple[str, str], np.ndarray]
    active: dict[tuple[str, str], np.ndarray]
    slot: dict[tuple[str, str], np.ndarray]
    level_ratio: dict[tuple[str, str], np.ndarray]


# Every name's fills on the panel's grid, bar-close and next-bar, the
# same-session oracle per side and stage 4's five-session one, and the
# coverage. `low_ratio` and `high_ratio` are (T, N) forecast grids.
def fill_grids(
    panel: Any,
    cubes: Mapping[str, SessionCube],
    low_ratio: np.ndarray,
    high_ratio: np.ndarray,
) -> tuple[Grid, Grid, dict[str, np.ndarray], dict[str, np.ndarray], dict[str, Any]]:
    """Return (bar-close grid, next-bar grid, {side: oracle}, {side: five-session oracle}, coverage)."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    if np.shape(low_ratio) != shape or np.shape(high_ratio) != shape:
        raise ValueError("the forecast grids must be on the panel's grid")
    grids = {
        mode: Grid(
            next_bar=mode,
            price={k: np.full(shape, np.nan) for k in KEYS},
            reached={k: np.zeros(shape, dtype=bool) for k in KEYS},
            active={k: np.zeros(shape, dtype=bool) for k in KEYS},
            slot={k: np.full(shape, -1, dtype=np.int64) for k in KEYS},
            level_ratio={k: np.full(shape, np.nan) for k in KEYS},
        )
        for mode in (False, True)
    }
    oracle = {side: np.full(shape, np.nan) for side in SIDES}
    oracle_five = {side: np.full(shape, np.nan) for side in SIDES}
    covered: list[str] = []
    for j, ticker in enumerate(panel.tickers):
        if str(ticker) == str(panel.benchmark):
            continue
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
            for key, fills in name_fills(
                series, cube, low_ratio[:, j], high_ratio[:, j], next_bar=mode
            ).items():
                grid.price[key][:, j] = fills.price
                grid.reached[key][:, j] = fills.reached
                grid.active[key][:, j] = fills.active
                grid.slot[key][:, j] = fills.slot
                grid.level_ratio[key][:, j] = fills.level_ratio
        for side in SIDES:
            oracle[side][:, j] = sd.oracle_prices(series, cube, 1)[side]
            oracle_five[side][:, j] = sd.oracle_prices(series, cube, lab.WINDOW)[side]
        covered.append(str(ticker))
    first = min((cubes[t].dates[0] for t in covered), default=None)
    coverage = {
        "names_with_cube": len(covered),
        "names_without_cube": sorted(
            str(t)
            for t in panel.tickers
            if str(t) not in set(covered) and str(t) != str(panel.benchmark)
        ),
        "first_cube_date": str(first) if first is not None else None,
        "cells_with_low_forecast": int(np.isfinite(low_ratio).sum()),
        "cells_with_high_forecast": int(np.isfinite(high_ratio).sum()),
    }
    return grids[False], grids[True], oracle, oracle_five, coverage


@dataclass(frozen=True)
class Market:
    """Everything the engine reads besides the orders, on the panel's (T, N) grid."""

    dates: np.ndarray
    tickers: tuple[str, ...]
    fills: Grid
    next_bar: Grid
    oracle: dict[str, np.ndarray]
    oracle_five: dict[str, np.ndarray]
    grades: np.ndarray
    closes: np.ndarray


# Assemble the Market from the panel, its grades and the grids.
def build_market(
    panel: Any,
    grades: np.ndarray,
    fills: Grid,
    next_bar: Grid,
    oracle: Mapping[str, np.ndarray],
    oracle_five: Mapping[str, np.ndarray],
) -> Market:
    """Return the Market."""
    if fills.next_bar or not next_bar.next_bar:
        raise ValueError(
            "fills must be the bar-close grid and next_bar the next-bar grid"
        )
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    if np.asarray(grades).shape != shape or any(
        np.shape(oracle[s]) != shape for s in SIDES
    ):
        raise ValueError("the grades and the oracle must be on the panel's grid")
    return Market(
        dates=dates,
        tickers=tuple(str(t) for t in panel.tickers),
        fills=fills,
        next_bar=next_bar,
        oracle={s: np.asarray(oracle[s], dtype=float) for s in SIDES},
        oracle_five={s: np.asarray(oracle_five[s], dtype=float) for s in SIDES},
        grades=np.asarray(grades),
        closes=np.asarray(panel.adj_close, dtype=float),
    )


# --- pricing one candidate ----------------------------------------------------


# The (rule, side) of a candidate name, refused when unknown.
def rule_of(candidate: str) -> tuple[str, str]:
    """Return (rule, side) of a candidate."""
    if candidate not in CANDIDATES:
        raise ValueError(
            f"unknown candidate {candidate!r}; registered: {', '.join(CANDIDATES)}"
        )
    return CANDIDATES[candidate]


@dataclass(frozen=True)
class Book(ae.Book):
    """The adaptive-entry Book with the order's column and its level ratio."""

    column: np.ndarray
    level_ratio: np.ndarray


# Price one candidate on one run's orders of its side: the candidate's
# fill against the control's per order, g and the counts. An order whose
# candidate or control has no price fills as the control (g = 0) and is
# counted; one without a forecast fills as the control and is counted as
# `no_forecast`.
def price_book(
    orders: so.Orders, market: Market, candidate: str, next_bar: bool = False
) -> Book:
    """Return the candidate's Book on the orders."""
    rule, side = rule_of(candidate)
    grid = market.next_bar if next_bar else market.fills
    rows = np.flatnonzero(orders.side == side)
    t = orders.session[rows]
    j = orders.column[rows]
    control = grid.price[(CONTROL, side)][t, j]
    price = grid.price[(rule, side)][t, j]
    unpriced = ~np.isfinite(control) | ~np.isfinite(price)
    active = grid.active[(rule, side)][t, j] & ~unpriced
    gain = np.where(unpriced, 0.0, lab.gain(control, price, side))
    k = len(rows)
    return Book(
        candidate=candidate,
        side=side,
        start=orders.start,
        stop=orders.stop,
        rows=rows,
        session=t,
        weight=orders.weight[rows],
        gain=gain,
        wait=np.zeros(k, dtype=np.int64),
        acted=active,
        unpriced=unpriced,
        no_forecast=~unpriced & ~grid.active[(rule, side)][t, j],
        oracle=lab.gain(control, market.oracle[side][t, j], side),
        reached=grid.reached[(rule, side)][t, j] & ~unpriced,
        slot=np.where(unpriced, -1, grid.slot[(rule, side)][t, j]).astype(np.int64),
        oracle_five=lab.gain(control, market.oracle_five[side][t, j], side),
        column=j,
        level_ratio=grid.level_ratio[(rule, side)][t, j],
    )


# --- statistics ----------------------------------------------------------------


# Adaptive entry's statistics of a book over one window plus the rule's
# own: the share of priced orders with a forecast and the mean level
# ratio of those.
def summarize(
    book: Book,
    dates: np.ndarray,
    lo: date | None,
    hi: date | None,
    mu_bp: float,
    subset: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return the statistics of one window."""
    out = ae.summarize(book, dates, lo, hi, mu_bp, subset)
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
    with_forecast = priced & book.acted
    out["with_forecast"] = int(with_forecast.sum())
    out["forecast_share"] = (
        float(with_forecast.sum() / priced.sum()) if priced.any() else math.nan
    )
    out["mean_level_ratio"] = sd._mean(book.level_ratio[with_forecast])
    return out


# The same statistics per grade group and per order detail of a book's
# orders, per window, for the book's side.
def splits(
    book: Book,
    groups: Mapping[str, np.ndarray],
    dates: np.ndarray,
    spans: Mapping[str, tuple[date | None, date | None]],
    mus: Mapping[str, float],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return {group: {label: {window: statistics}}}."""
    values = sd.group_values(book.side)
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


# The deflated Sharpe of one candidate at the plan's trial counts (N = 2,
# cumulative 466), the trial variance the across-candidate variance of
# the two candidates' model-window Sharpe ratios.
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
        label: (
            candidate_stats.deflated_sharpe(
                sharpe, length, skew, kurtosis, count, variance
            )
            if math.isfinite(variance) and math.isfinite(sharpe)
            else math.nan
        )
        for label, count in TRIALS.items()
    }
    dsr = values["registered"]
    return {
        "candidate": candidate,
        "sharpe": sharpe,
        "length": length,
        "candidates": int(len(sharpes)),
        "trial_variance": variance,
        "trials": int(TRIALS["registered"]),
        "dsr": dsr,
        "dsr_cumulative": values["cumulative"],
        "gate": DSR_GATE,
        "passes": bool(math.isfinite(dsr) and dsr >= DSR_GATE),
    }


# --- the whole test --------------------------------------------------------------


# The per-order rows of the median offset's orders, for an independent
# recomputation.
def order_rows(
    orders: so.Orders, market: Market, books: Mapping[str, tuple[Book, Book]]
) -> dict[str, Any]:
    """Return the payload's "rows" block."""
    t = orders.session
    j = orders.column
    control = np.where(
        orders.buy,
        market.fills.price[(CONTROL, BUY)][t, j],
        market.fills.price[(CONTROL, SELL)][t, j],
    )
    out: dict[str, Any] = {
        "sessions": [str(d) for d in market.dates[orders.start : orders.stop]],
        "date": [str(d) for d in market.dates[t]],
        "ticker": orders.ticker.tolist(),
        "side": orders.side.tolist(),
        "weight": orders.weight.tolist(),
        "detail": orders.detail.tolist(),
        "grade": orders.grade.tolist(),
        "control": control.tolist(),
        "candidates": {},
    }
    for candidate, (book, nb) in books.items():
        rule, side = rule_of(candidate)
        if not np.array_equal(book.rows, np.flatnonzero(orders.side == side)):
            raise ValueError("the books must be priced on the same orders")
        out["candidates"][candidate] = {
            "side": side,
            "rows": book.rows.tolist(),
            "fill": market.fills.price[(rule, side)][
                t[book.rows], j[book.rows]
            ].tolist(),
            "g_bp": book.gain.tolist(),
            "next_bar_g_bp": nb.gain.tolist(),
            "level_ratio": book.level_ratio.tolist(),
            "reached": book.reached.tolist(),
            "acted": book.acted.tolist(),
            "unpriced": book.unpriced.tolist(),
            "no_forecast": book.no_forecast.tolist(),
            "slot": book.slot.tolist(),
        }
    return out


# Price every candidate on every offset's orders and assemble the payload.
def evaluate(
    runs: Sequence[so.Orders], market: Market, registered: int = OFFSETS
) -> dict[str, Any]:
    """Return the study's payload."""
    if not runs:
        raise ValueError("no offsets were priced")
    bases = {o.basis for o in runs}
    if len(bases) != 1:
        raise ValueError(f"the offsets' orders mix bases: {sorted(bases)}")
    spans = windows()
    median = len(runs) // 2
    dates = market.dates
    drifts = {w: sd.drift(market, lo, hi) for w, (lo, hi) in spans.items()}
    mus = {w: d["mu_bp"] for w, d in drifts.items()}
    per_offset: dict[str, dict[str, list[float]]] = {
        c: {"model_bp": [], "contaminated_bp": [], "next_bar_model_bp": []}
        for c in CANDIDATES
    }
    for orders in runs:
        for c in CANDIDATES:
            book = price_book(orders, market, c)
            nb = price_book(orders, market, c, next_bar=True)
            per_offset[c]["model_bp"].append(sd.window_mean(book, dates, *spans[MODEL]))
            per_offset[c]["contaminated_bp"].append(
                sd.window_mean(book, dates, *spans[CONTAMINATED])
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
            "across_offsets_contaminated": sd._across(per_offset[c]["contaminated_bp"]),
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
            "sides": list(SIDES),
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
            "DIP": DIP,
            "CAP": CAP,
            "POST_START": str(POST_START),
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
        "candidates": {c: {"rule": r, "side": s} for c, (r, s) in CANDIDATES.items()},
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


# The six criteria for one candidate at the median offset: the model
# (post-cutoff) floor, the next-bar floor, the contaminated window not
# negative, the deflated Sharpe gate at N = 2, the drift-adjusted floor
# and the count of positive offsets.
def criteria_of(result: Mapping[str, Any], dsr: Mapping[str, Any]) -> dict[str, bool]:
    """Return {criterion: passes}."""
    model = result["default"][MODEL]
    other = sd._f(result["default"][CONTAMINATED]["mean_bp"])
    bar = result["next_bar"][MODEL]
    positive = int(result["across_offsets"]["positive"])
    return {
        "1_floor": sd.clears(model["mean_bp"], model["hac_t"]),
        "2_next_bar": sd.clears(bar["mean_bp"], bar["hac_t"]),
        "3_not_negative_contaminated": bool(math.isfinite(other) and other >= 0.0),
        "4_deflated_sharpe": bool(dsr["passes"]),
        "5_drift_adjusted": sd.clears(
            model["drift_mean_bp"], model["drift_hac_t"], DRIFT_FLOOR_BP, DRIFT_FLOOR_T
        ),
        "6_offsets_positive": positive >= OFFSETS_POSITIVE,
    }


# One candidate's verdict record: REPLACES when all six hold, "RECORD:
# real but immaterial" when the floor fails but the re-timed orders gain
# 25 bp at a clustered t of 3, else RECORD - with the numbers behind it.
def judge(result: Mapping[str, Any], dsr: Mapping[str, Any]) -> dict[str, Any]:
    """Return the candidate's label, criteria and numbers."""
    criteria = criteria_of(result, dsr)
    model = result["default"][MODEL]
    bar = result["next_bar"][MODEL]
    other = result["default"][CONTAMINATED]
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
        "model_sessions": int(model["sessions"]),
        "next_bar_bp": sd._f(bar["mean_bp"]),
        "next_bar_t": sd._f(bar["hac_t"]),
        "contaminated_bp": sd._f(other["mean_bp"]),
        "contaminated_t": sd._f(other["hac_t"]),
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
        "forecast_share": sd._f(model["forecast_share"]),
        "mean_level_ratio": sd._f(model["mean_level_ratio"]),
        "capture": sd._f(model["capture"]),
    }


# The verdict per candidate from the payload, one line each, and the headline.
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


# The headline: which candidates replace their side's rule, or that none does.
def _headline(
    offsets: Mapping[str, Any], replaces: Sequence[str], immaterial: Sequence[str]
) -> str:
    """Return the headline text."""
    head = ""
    if offsets.get("smoke"):
        head = f"SMOKE RUN ({offsets.get('priced')} of {offsets.get('registered')} offsets): not the registered test. "
    if replaces:
        head += f"{REPLACES}: {', '.join(replaces)} clear every criterion against dip_or_close for their side on the post-cutoff window; a live change needs a separate registration and the operator's go-ahead"
    else:
        head += f"{RECORD}: no Kronos fill candidate clears every criterion on the post-cutoff window; the board keeps dip_or_close on both sides"
    if immaterial:
        head += f". {IMMATERIAL}: {', '.join(immaterial)}"
    return head


# One candidate's verdict line, stage-4 style.
def _line(candidate: str, info: Mapping[str, Any]) -> str:
    """Return the candidate's verdict line."""
    signed, share = sd._signed, sd._share
    holds = "holds" if info["criteria"]["2_next_bar"] else "fails"
    rule, side = CANDIDATES[candidate]
    parts = [
        f"post-cutoff model window {signed(info['model_bp'], 1)} bp/session (t {signed(info['model_t'])}) over {info['model_sessions']} sessions",
        f"next-bar {signed(info['next_bar_bp'], 1)} (t {signed(info['next_bar_t'])}) {holds}",
        f"contaminated 2018-01..2024-06 {signed(info['contaminated_bp'], 1)} bp/session (t {signed(info['contaminated_t'])})",
        f"deflated Sharpe {signed(info['dsr'])} at N = {TRIALS['registered']} ({signed(info['dsr_cumulative'])} at {TRIALS['cumulative']})",
        f"drift-adjusted {signed(info['drift_bp'], 1)} (t {signed(info['drift_t'])})",
        f"positive at {info['offsets_positive']} of {info['offsets']} offsets",
        f"per re-timed order {signed(info['retimed_bp'], 1)} bp (t {signed(info['retimed_t'])}) over {info['retimed']} of {info['orders']} orders",
        f"forecast on {share(info['forecast_share'])}",
        (
            f"mean level ratio {info['mean_level_ratio']:.4f}"
            if math.isfinite(info["mean_level_ratio"])
            else "mean level ratio n/a"
        ),
        f"level reached {share(info['reached_share'])}",
        f"oracle capture {share(info['capture'])}",
    ]
    return f"{candidate} ({rule}, {side}): {'; '.join(parts)} - {info['label']}"
