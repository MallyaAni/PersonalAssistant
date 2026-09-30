"""Structure rules S1: six fill candidates that read a level, priced on stage 4's book.

`docs/research/structure-rules-plan-2026-09-30.md` registers everything
here; this module computes nothing the plan did not fix. S1g, the structure
notch on the technical analyst, is not a fill rule and lives in
`backend/agents/trading/desk/technical.py`, judged through the point-in-time
scorecard (`notch_verdict` below reads two of its payloads).

**The levels** are the board's (`structure.py`, vectorised in
`structure_panel.py` so the study and the display cannot disagree): EMA21(t)
of the adjusted close, H20(t) the highest daily high over t-19..t, L(t+1)
the nearer of the two above the close of t (no level when neither is), the
tag (the first bar of t+1 has high >= L x 0.995 while close(t) < L) and the
rejection (a tag whose bar close < L). Every level is on the panel's
adjusted basis; a cube bar is moved onto it by `stage4_labels.cube_scale`
(never by `adj_close / close`, a dividend factor only).

**The control** is the board's `dip_or_close` in session t+1 on each side:
a buy at the first bar close at or below open x 0.99, a sell at the first
at or above open x 1.01, else the official close. The orders are stage
4's: every order of the control executor (`stage4_orders`) under
`graded-equal-weight/5`, from each of 20 start offsets, executed basis,
read at the median offset.

**The candidates**, each priced against the control of its side:

- `S1a` (`resistance_defer`, buy): the control, except that a buy whose
  first bar is *rejected* at L fills at the official close of t+1.
- `S1b` (`resistance_skip`, buy): as S1a, but the rejected buy is not
  filled in t+1: it is re-planned for t+2 as the desk's deferred-buy leg
  does (`OrderJournal.deferred_units`) and filled there by the control
  rule; its wait is one session and its drift-adjusted g is stage 4's
  g - s.mu.d with d = 1 (a buy that waits holds cash; `stage4_decisions.
  drift_adjusted`). Unpriced when t+2 is not a complete cube session.
- `S1c` (`hold_the_dip`, buy): when the first bar to reach the 1% dip is
  bar k, the buy is sent at the close of bar k+1 only if that bar closes
  above bar k's low; otherwise the rule keeps watching, for a later bar
  that closes 1% under the open and above the prior bar's low; else the
  close.
- `S1d` (`decision_reference`, buy): the dip level is min(open(t+1),
  close(t)) x 0.99, both adjusted; and when open(t+1) > close(t) x (1 +
  sigma_t) the buy waits for the close. sigma_t is stage 4's.
- `S1e` (`market_relative`, buy): the trigger is the bar's return from
  the session's open at or under -1% in excess of SPY's return from its
  open over the same bar (the index cube); with no SPY session the
  control applies.
- `S1f` (`sell_at_level`, sell): the control's pop rule, except that a
  sell is sent at the first bar whose high reaches L from below, at L (a
  resting limit at the level; a session that opens through it fills at
  the open); the limit wins a bar the control would also fill at.

**Validity.** A candidate prices an order only when t+1 is a complete cube
session (and sigma_t is finite for S1d; t+2 complete for S1b's rejected
buys); otherwise its price is NaN and the order fills as the control (g =
0, counted as unpriced). With `next_bar` a bar-close fill moves to the
next bar's open (`fill_timing._bar_price`); S1f's limit fill does not.

**Per order.** g = `stage4_labels.gain(control, candidate, side)` in bp,
positive when a buy pays less or a sell receives more. The book, the
windows, the statistics are stage 4's through `adaptive_entry.summarize`
(per offset the sum over the orders decided at t of weight x g, in bp of
equity; the model window 2018-01-02..2023-12-29 and 2024-2026; at the
median offset the Newey-West t at lag 20, the per re-timed order mean with
its clustered t, the drift-adjusted twin, the splits by grade and by
detail, the oracle capture).

**The deflated Sharpe** is at N = 7, the plan's registered count (six fill
rules and the notch), with the across-candidate variance of the six fill
candidates' model-window Sharpe ratios; the cumulative 464 beside it.

**Verdict** (`verdict`): REPLACES its side's rule when all six criteria
hold at the median offset - (1) the model-window mean >= +2.0 bp a session
with t >= 2.0; (2) the next-bar run holds the floor; (3) 2024-2026 not
negative; (4) the deflated Sharpe at N = 7 >= 0.95; (5) the drift-adjusted
mean >= +1.0 bp at t >= 2; (6) positive at 15 of 20 offsets - else RECORD,
or "RECORD: real but immaterial" when (1) fails but the per re-timed order
mean is >= 25 bp with a clustered t >= 3 (`adaptive_entry.judge`).

**Reported, never deciding:** how often each fires (`acted_share`), the
tag and rejection rates, the fills by bar, the reading by grade and by
leg, the oracle capture.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from backend.agents.trading.desk import point_in_time, structure_panel
from backend.market import adaptive_entry as ae
from backend.market import candidate_stats, fill_timing
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

PLAN = "docs/research/structure-rules-plan-2026-09-30.md"
STUDY = "structure_rules"
CONTROL = lab.CONTROL
BUY, SELL = "buy", "sell"
SIDES = (BUY, SELL)
RESISTANCE_DEFER = "resistance_defer"
RESISTANCE_SKIP = "resistance_skip"
HOLD_THE_DIP = "hold_the_dip"
DECISION_REFERENCE = "decision_reference"
MARKET_RELATIVE = "market_relative"
SELL_AT_LEVEL = "sell_at_level"
# The six fill candidates, in the plan's order: (rule, side).
CANDIDATES: dict[str, tuple[str, str]] = {
    "S1a": (RESISTANCE_DEFER, BUY),
    "S1b": (RESISTANCE_SKIP, BUY),
    "S1c": (HOLD_THE_DIP, BUY),
    "S1d": (DECISION_REFERENCE, BUY),
    "S1e": (MARKET_RELATIVE, BUY),
    "S1f": (SELL_AT_LEVEL, SELL),
}
# Every (rule, side) a grid carries: the control on both sides and the six.
KEYS: tuple[tuple[str, str], ...] = ((CONTROL, BUY), (CONTROL, SELL)) + tuple(
    CANDIDATES.values()
)
NOTCH = "S1g"
DIP = fill_timing.DIP
# The criteria, fixed by the plan (stage 4's for one side, plus the offsets).
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
# The plan's trial counts: seven registered candidates, cumulative 464.
TRIALS = {"registered": 7, "cumulative": 464}
MODEL = sd.MODEL
REPORTED = sd.REPORTED
MODEL_START = sd.DEFAULT_MODEL_START
REPLACES = sd.REPLACES
RECORD = sd.RECORD
IMMATERIAL = sd.IMMATERIAL
GROUPS = ae.GROUPS
# S1g's book gate on two point-in-time scorecard payloads (the plan).
NOTCH_COST_BPS = 25.0
NOTCH_DECIDING = "2016-2023"
NOTCH_RECENT = "2024-2026"
NOTCH_RULE_LINE = "rule / point-in-time"
NOTCH_DRAWDOWN_POINTS = 0.03
NOTCH_CAGR_BAND = 0.01

assert DIP == 0.01
assert TRIALS["registered"] == len(CANDIDATES) + 1
assert TRIALS["cumulative"] == ae.TRIALS["cumulative"] + TRIALS["registered"]
assert (FLOOR_BP, FLOOR_T, DSR_GATE, OFFSETS, OFFSETS_POSITIVE) == (
    2.0,
    2.0,
    0.95,
    20,
    15,
)


# --- the levels ------------------------------------------------------------------


@dataclass(frozen=True)
class Levels:
    """The board's structure for one name on every session t, adjusted basis."""

    ema21: np.ndarray  # (T,)
    falling: np.ndarray  # (T,) bool: EMA21(t) < EMA21(t-5)
    high20: np.ndarray  # (T,)
    level: np.ndarray  # (T,) L(t+1): the nearer of the two above close(t), NaN if none
    lower_highs: np.ndarray  # (T,) bool


# The levels of one name from its NameSeries (adjusted closes and highs),
# through `structure_panel`: nothing here restates a definition.
def levels(series: lab.NameSeries) -> Levels:
    """Return the Levels of one name."""
    ema = structure_panel.ema21(series.close)
    high = structure_panel.high20(series.high)
    level = structure_panel.buy_level(series.close, ema, high)
    return Levels(
        ema21=ema,
        falling=structure_panel.ema_falling(ema),
        high20=high,
        level=level,
        lower_highs=structure_panel.lower_highs(series.high, series.close, level),
    )


# --- the fills -------------------------------------------------------------------


@dataclass(frozen=True)
class Fills:
    """One (rule, side)'s fills for every decision session t of one name."""

    price: np.ndarray  # (T,) adjusted fill price, NaN where it cannot be priced
    reached: np.ndarray  # (T,) bool: filled at its trigger rather than the close
    active: (
        np.ndarray
    )  # (T,) bool: the rule acted (its fill may differ from the control's)
    slot: np.ndarray  # (T,) int: the bar of a trigger fill, -1 at the close or unpriced
    wait: np.ndarray  # (T,) int: sessions waited past t+1 (S1b's rejected buys: 1)
    tagged: (
        np.ndarray
    )  # (T,) bool: the level was tagged (S1a/b: the first bar; S1f: any bar)


# Empty fills for T sessions: nothing priced.
def _empty(length: int) -> Fills:
    """Return unpriced Fills."""
    return Fills(
        np.full(length, np.nan),
        np.zeros(length, dtype=bool),
        np.zeros(length, dtype=bool),
        np.full(length, -1, dtype=np.int64),
        np.zeros(length, dtype=np.int64),
        np.zeros(length, dtype=bool),
    )


# Fills from per-cube-row raw prices and flags, read at each priced
# session's t+1 row (`ahead`) and scaled onto the adjusted basis.
def _read(
    raw: np.ndarray,
    hit: np.ndarray,
    slot: np.ndarray,
    ahead: np.ndarray,
    scale: np.ndarray,
    priced: np.ndarray,
    active: np.ndarray,
    tagged: np.ndarray | None = None,
) -> Fills:
    """Return the Fills of per-row prices at the priced sessions."""
    out = _empty(len(ahead))
    idx = np.flatnonzero(priced)
    out.price[idx] = raw[ahead[idx]] * scale[idx]
    out.reached[idx] = hit[ahead[idx]]
    out.slot[idx] = np.where(hit[ahead[idx]], slot[ahead[idx]], -1)
    out.active[idx] = np.asarray(active, dtype=bool)[idx]
    if tagged is not None:
        out.tagged[idx] = np.asarray(tagged, dtype=bool)[idx]
    return out


# The per-row fill of a close-triggered level: the first bar close at or
# past `level` (a buy at or below, a sell at or above), else the official
# close; returns (price, filled at a bar, first slot).
def _close_rule(
    cube: SessionCube, side: str, level: np.ndarray, next_bar: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ((N,) raw price, (N,) hit, (N,) slot) for a per-row level."""
    price, hit = fill_timing._first_close_past(cube, side, level, next_bar)
    _, first = fill_timing._first_past(cube, side, level)
    return price, hit, first


# The per-row fill of a per-bar trigger matrix `trigger` (N, 26): the first
# bar it holds on, else the official close; (price, hit, slot).
def _bar_rule(
    cube: SessionCube, trigger: np.ndarray, next_bar: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ((N,) raw price, (N,) hit, (N,) slot) for a per-bar trigger."""
    any_hit = trigger.any(axis=1)
    first = np.argmax(trigger, axis=1)
    picked = fill_timing._bar_price(cube, first, next_bar)
    price = np.where(any_hit, picked, fill_timing._official_close(cube))
    return price, fill_timing._filled_at_bar(any_hit, first, next_bar), first


# S1c on every cube row: with k the first bar whose close is at or under
# open x (1 - DIP), the fill is bar k+1's close when that close is above
# bar k's low; else the first later bar (k+2 on) closing at or under the
# dip and above the prior bar's low; else the official close. No dip: the
# official close. Returns (price, hit, slot).
def hold_the_dip(
    cube: SessionCube, next_bar: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ((N,) raw price, (N,) hit, (N,) slot) of the hold-the-dip rule."""
    n = len(cube)
    slots = np.arange(FULL_SESSION_SLOTS)
    dip = cube.close <= fill_timing._dip_level(cube, BUY)[:, None]
    any_dip = dip.any(axis=1)
    k = np.argmax(dip, axis=1)
    rows = np.arange(n)
    following = np.minimum(k + 1, FULL_SESSION_SLOTS - 1)
    has_next = any_dip & (k + 1 < FULL_SESSION_SLOTS)
    holds = has_next & (cube.close[rows, following] > cube.low[rows, k])
    above_prior = np.zeros(cube.close.shape, dtype=bool)
    above_prior[:, 1:] = cube.close[:, 1:] > cube.low[:, :-1]
    later = dip & above_prior & (slots[None, :] >= (k + 2)[:, None]) & any_dip[:, None]
    trigger = later.copy()
    trigger[holds] = False
    trigger[rows[holds], following[holds]] = True
    return _bar_rule(cube, trigger, next_bar)


# S1e on every cube row with a SPY row: the first bar whose return from the
# session's open is at or under -DIP in excess of SPY's return from its
# open over the same bar; a row without SPY (`spy_row` -1) takes the
# control's trigger. Returns (price, hit, slot, had SPY).
def market_relative(
    cube: SessionCube,
    spy: SessionCube | None,
    spy_row: np.ndarray,
    next_bar: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return ((N,) raw price, (N,) hit, (N,) slot, (N,) with SPY) of the rule."""
    open0 = cube.open[:, :1]
    with np.errstate(all="ignore"):
        own = cube.close / open0 - 1.0
    excess = np.zeros(cube.close.shape)
    with_spy = np.asarray(spy_row) >= 0
    if spy is not None and with_spy.any():
        s = spy_row[with_spy]
        with np.errstate(all="ignore"):
            excess[with_spy] = spy.close[s] / spy.open[s, :1] - 1.0
    with np.errstate(invalid="ignore"):
        trigger = own <= -DIP + excess
    price, hit, slot = _bar_rule(cube, trigger, next_bar)
    return price, hit, slot, with_spy


# S1f on every cube row: a resting limit at `level_raw` (NaN: no level)
# fills at the first bar whose high reaches it, at the level - at the open
# when the session opens through it - unless the control's pop rule fired
# on an earlier bar, in which case the control's fill stands; no level or
# no touch: the control's fill. Returns (price, hit, slot, filled at the
# level, the level touched at all).
def sell_at_level(
    cube: SessionCube, level_raw: np.ndarray, next_bar: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return ((N,) raw price, hit, slot, filled at L, touched L) of the rule."""
    control, c_hit, c_slot = _close_rule(
        cube, SELL, fill_timing._dip_level(cube, SELL), next_bar
    )
    lv = np.asarray(level_raw, dtype=float)
    with np.errstate(invalid="ignore"):
        touch = cube.high >= lv[:, None]
    any_touch = np.isfinite(lv) & touch.any(axis=1)
    first = np.argmax(touch, axis=1)
    at_level = any_touch & (~c_hit | (first <= c_slot))
    open0 = cube.open[:, 0]
    limit = np.where(first == 0, np.maximum(lv, open0), lv)
    price = np.where(at_level, limit, control)
    hit = np.where(at_level, True, c_hit)
    slot = np.where(at_level, first, c_slot)
    return price, hit, slot, at_level, any_touch


# The control and the six rules for every decision session of one name,
# both sides, on the adjusted basis. `spy` is the index cube (S1e; None or
# a missing session: the control). A session t whose t+1 is not a complete
# cube session is unpriced; S1d also needs sigma_t; S1b's rejected buys
# need t+2.
def name_fills(  # noqa: C901 - one pass per name, one block per rule
    series: lab.NameSeries,
    cube: SessionCube,
    spy: SessionCube | None = None,
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
    scale1 = np.full(length, np.nan)
    scale1[:-1] = scale[1:]
    ahead2 = np.full(length, -1, dtype=np.int64)
    ahead2[:-2] = rows[2:]
    scale2 = np.full(length, np.nan)
    scale2[:-2] = scale[2:]
    ok = (ahead >= 0) & np.isfinite(scale1)
    ok2 = ok & (ahead2 >= 0) & np.isfinite(scale2)
    with_sigma = ok & np.isfinite(series.sigma)
    ones = np.ones(length, dtype=bool)
    lv = levels(series)
    out: dict[tuple[str, str], Fills] = {}
    # The controls, both sides.
    control: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for side in SIDES:
        control[side] = _close_rule(
            cube, side, fill_timing._dip_level(cube, side), next_bar
        )
        out[(CONTROL, side)] = _read(*control[side], ahead, scale1, ok, ones)
    c_price, c_hit, c_slot = control[BUY]
    # The tag of the first bar of t+1 against L, both on the adjusted basis.
    row1 = np.maximum(ahead, 0)
    bar_high = np.where(ok, cube.high[row1, 0] * scale1, np.nan)
    bar_close = np.where(ok, cube.close[row1, 0] * scale1, np.nan)
    tagged, rejected = structure_panel.first_bar_tag(
        lv.level, series.close, bar_high, bar_close
    )
    tagged &= ok
    rejected &= ok
    official = fill_timing._official_close(cube)
    # S1a: a rejected first bar sends the buy to the official close of t+1.
    defer = _read(c_price, c_hit, c_slot, ahead, scale1, ok, rejected, tagged)
    defer.price[rejected] = official[ahead[rejected]] * scale1[rejected]
    defer.reached[rejected] = False
    defer.slot[rejected] = -1
    out[(RESISTANCE_DEFER, BUY)] = defer
    # S1b: a rejected first bar re-plans the buy for t+2, the control rule
    # there; wait 1. Without t+2 the order is unpriced.
    skip = _read(c_price, c_hit, c_slot, ahead, scale1, ok, rejected, tagged)
    priced2 = rejected & ok2
    skip.price[rejected] = np.nan
    skip.price[priced2] = c_price[ahead2[priced2]] * scale2[priced2]
    skip.reached[rejected] = False
    skip.reached[priced2] = c_hit[ahead2[priced2]]
    skip.slot[rejected] = -1
    skip.slot[priced2] = np.where(c_hit[ahead2[priced2]], c_slot[ahead2[priced2]], -1)
    skip.wait[priced2] = 1
    skip.active[rejected & ~ok2] = False
    out[(RESISTANCE_SKIP, BUY)] = skip
    # S1c: hold the dip; it acts wherever the control's dip was reached.
    h_price, h_hit, h_slot = hold_the_dip(cube, next_bar)
    out[(HOLD_THE_DIP, BUY)] = _read(
        h_price, h_hit, h_slot, ahead, scale1, ok, c_hit[row1] & ok
    )
    # S1d: the decision-price reference and the sigma gap guard.
    open_adj = np.where(with_sigma, cube.open[row1, 0] * scale1, np.nan)
    with np.errstate(invalid="ignore"):
        gap_up = with_sigma & (open_adj > series.close * (1.0 + series.sigma))
        lower_reference = with_sigma & (series.close < open_adj)
    reference = np.minimum(open_adj, series.close) / scale1
    level = np.full(len(cube), np.nan)
    keep = with_sigma & ~gap_up
    level[ahead[keep]] = reference[keep] * (1.0 - DIP)
    d_price, d_hit, d_slot = _close_rule(cube, BUY, level, next_bar)
    out[(DECISION_REFERENCE, BUY)] = _read(
        d_price, d_hit, d_slot, ahead, scale1, with_sigma, gap_up | lower_reference
    )
    # S1e: the market-relative dip; the control where SPY has no session.
    spy_row = (
        lab.cube_rows(cube.dates, spy)
        if spy is not None and len(spy)
        else np.full(len(cube), -1, dtype=np.int64)
    )
    m_price, m_hit, m_slot, with_spy = market_relative(cube, spy, spy_row, next_bar)
    out[(MARKET_RELATIVE, BUY)] = _read(
        m_price, m_hit, m_slot, ahead, scale1, ok, with_spy[row1] & ok
    )
    # S1f: a sell at the level, the level on t+1's raw basis.
    level_raw = np.full(len(cube), np.nan)
    has_level = ok & np.isfinite(lv.level)
    level_raw[ahead[has_level]] = lv.level[has_level] / scale1[has_level]
    s_price, s_hit, s_slot, _, touched = sell_at_level(cube, level_raw, next_bar)
    out[(SELL_AT_LEVEL, SELL)] = _read(
        s_price, s_hit, s_slot, ahead, scale1, ok, has_level, touched[row1] & ok
    )
    return out


@dataclass(frozen=True)
class Grid:
    """Every (session, name)'s fills under one fill mode, on the panel's grid."""

    next_bar: bool
    price: dict[tuple[str, str], np.ndarray]  # -> (T, N) adjusted price, NaN unpriced
    reached: dict[tuple[str, str], np.ndarray]  # -> (T, N) bool
    active: dict[tuple[str, str], np.ndarray]  # -> (T, N) bool
    slot: dict[tuple[str, str], np.ndarray]  # -> (T, N) int
    wait: dict[tuple[str, str], np.ndarray]  # -> (T, N) int
    tagged: dict[tuple[str, str], np.ndarray]  # -> (T, N) bool


# Every name's fills on the panel's grid, with bar-close and next-bar fills,
# the same-session oracle per side (the best bar close of t+1) and stage 4's
# five-session one, and the levels' coverage. `spy` is the index cube.
def fill_grids(
    panel: Any, cubes: Mapping[str, SessionCube], spy: SessionCube | None = None
) -> tuple[Grid, Grid, dict[str, np.ndarray], dict[str, np.ndarray], dict[str, Any]]:
    """Return (bar-close grid, next-bar grid, {side: oracle}, {side: five-session
    oracle}, coverage)."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    grids = {
        mode: Grid(
            next_bar=mode,
            price={k: np.full(shape, np.nan) for k in KEYS},
            reached={k: np.zeros(shape, dtype=bool) for k in KEYS},
            active={k: np.zeros(shape, dtype=bool) for k in KEYS},
            slot={k: np.full(shape, -1, dtype=np.int64) for k in KEYS},
            wait={k: np.zeros(shape, dtype=np.int64) for k in KEYS},
            tagged={k: np.zeros(shape, dtype=bool) for k in KEYS},
        )
        for mode in (False, True)
    }
    oracle = {side: np.full(shape, np.nan) for side in SIDES}
    oracle_five = {side: np.full(shape, np.nan) for side in SIDES}
    with_level = np.zeros(shape, dtype=bool)
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
            for key, fills in name_fills(series, cube, spy, next_bar=mode).items():
                grid.price[key][:, j] = fills.price
                grid.reached[key][:, j] = fills.reached
                grid.active[key][:, j] = fills.active
                grid.slot[key][:, j] = fills.slot
                grid.wait[key][:, j] = fills.wait
                grid.tagged[key][:, j] = fills.tagged
        for side in SIDES:
            oracle[side][:, j] = sd.oracle_prices(series, cube, 1)[side]
            oracle_five[side][:, j] = sd.oracle_prices(series, cube, lab.WINDOW)[side]
        with_level[:, j] = np.isfinite(levels(series).level)
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
        "spy_sessions": int(len(spy)) if spy is not None else 0,
        "spy_first_date": str(spy.dates[0]) if spy is not None and len(spy) else None,
        "name_sessions_with_level": int(with_level.sum()),
    }
    return grids[False], grids[True], oracle, oracle_five, coverage


@dataclass(frozen=True)
class Market:
    """Everything the engine reads besides the orders, on the panel's (T, N) grid."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    fills: Grid  # bar-close fills
    next_bar: Grid  # next-bar fills
    oracle: dict[str, np.ndarray]  # side -> (T, N) the best bar close of t+1, adjusted
    oracle_five: dict[str, np.ndarray]  # side -> (T, N) stage 4's oracle over t+1..t+5
    grades: np.ndarray  # (T, N) the desk grade of the report the orders came from
    closes: np.ndarray  # (T, N) adjusted closes (the drift)


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
    """Return (rule, side) of "S1<k>"."""
    if candidate not in CANDIDATES:
        raise ValueError(
            f"unknown candidate {candidate!r}; registered: {', '.join(CANDIDATES)}"
        )
    return CANDIDATES[candidate]


@dataclass(frozen=True)
class Book(ae.Book):
    """The adaptive-entry Book with the order's column and the rule's tag flag."""

    column: np.ndarray  # (K,) the name's panel column
    tagged: np.ndarray  # (K,) bool: the level was tagged (priced orders only)


# Price one candidate on one run's orders of its side: the candidate's fill
# against the control's per order, g, the wait and the counts. An order
# whose candidate or control has no price fills as the control (g = 0) and
# is counted.
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
    gain = np.where(unpriced, 0.0, lab.gain(control, price, side))
    return Book(
        candidate=candidate,
        side=side,
        start=orders.start,
        stop=orders.stop,
        rows=rows,
        session=t,
        weight=orders.weight[rows],
        gain=gain,
        wait=np.where(unpriced, 0, grid.wait[(rule, side)][t, j]).astype(np.int64),
        acted=grid.active[(rule, side)][t, j] & ~unpriced,
        unpriced=unpriced,
        no_forecast=np.zeros(len(rows), dtype=bool),
        oracle=lab.gain(control, market.oracle[side][t, j], side),
        reached=grid.reached[(rule, side)][t, j] & ~unpriced,
        slot=np.where(unpriced, -1, grid.slot[(rule, side)][t, j]).astype(np.int64),
        oracle_five=lab.gain(control, market.oracle_five[side][t, j], side),
        column=j,
        tagged=grid.tagged[(rule, side)][t, j] & ~unpriced,
    )


# --- statistics ----------------------------------------------------------------


# Stage 4's statistics of a book over one window through `adaptive_entry.
# summarize` (the trigger, the bars, the five-session oracle), plus the
# rule's tag rate: the priced orders whose level was tagged (S1a/b: the
# first bar; S1f: any bar).
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
    tagged = priced & book.tagged
    out["tagged"] = int(tagged.sum())
    out["tagged_share"] = (
        float(tagged.sum() / priced.sum()) if priced.any() else math.nan
    )
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


# The deflated Sharpe of one candidate at the plan's trial counts (N = 7,
# cumulative 464), the trial variance the across-candidate variance of the
# six fill candidates' model-window Sharpe ratios: `adaptive_entry.
# deflated` at this study's counts.
def deflated(excess: Mapping[str, Mapping[str, Any]], candidate: str) -> dict[str, Any]:
    """Return the deflated Sharpe record of `candidate`."""
    return ae.deflated(excess, candidate, TRIALS)


# --- the whole test --------------------------------------------------------------


# The per-order rows of the median offset's orders, for an independent
# recomputation: the order's date, ticker, side, weight, detail and grade,
# the run's decision dates, the control fill of its side, and per
# candidate (on the orders of its side, by row index) the fill, g (bar-close
# and next-bar), the wait and the flags.
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
            "wait": book.wait.tolist(),
            "reached": book.reached.tolist(),
            "acted": book.acted.tolist(),
            "unpriced": book.unpriced.tolist(),
            "slot": book.slot.tolist(),
        }
    return out


# Price every candidate on every offset's orders and assemble the payload:
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
            "EMA_SPAN": structure_panel.EMA_SPAN,
            "SLOPE_SESSIONS": structure_panel.SLOPE_SESSIONS,
            "HIGH_WINDOW": structure_panel.HIGH_WINDOW,
            "TAG_BAND": structure_panel.TAG_BAND,
            "NEAR_BAND": structure_panel.NEAR_BAND,
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


# The plan's verdict per candidate from the payload (`adaptive_entry.
# judge`: the six criteria and the real-but-immaterial reading), one line
# each, and the headline; a smoke run's headline says it is not the
# registered test.
def verdict(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return {"candidates", "replaces", "immaterial", "lines", "text"}."""
    candidates = {
        c: ae.judge(payload["results"][c], payload["deflated"][c]) for c in CANDIDATES
    }
    for c, info in candidates.items():
        model = payload["results"][c]["default"][MODEL]
        info["tagged_share"] = sd._f(model.get("tagged_share"))
        info["waited_share"] = sd._f(model.get("waited_share"))
    replaces = [c for c, v in candidates.items() if v["label"] == REPLACES]
    immaterial = [c for c, v in candidates.items() if v["label"] == IMMATERIAL]
    return {
        "candidates": candidates,
        "replaces": replaces,
        "immaterial": immaterial,
        "lines": [_line(c, v) for c, v in candidates.items()],
        "text": _headline(payload.get("offsets") or {}, replaces, immaterial),
    }


# The verdict's headline: which candidates replace their side of the
# board's rule, or that none does, and which are real but immaterial.
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
            "dip_or_close for their side; a live change needs a separate "
            "registration and the operator's go-ahead"
        )
    else:
        head += (
            f"{RECORD}: no fill candidate clears every criterion; the board keeps "
            "dip_or_close on both sides"
        )
    if immaterial:
        head += f". {IMMATERIAL}: {', '.join(immaterial)} (kept for the manual book)"
    return head


# One candidate's verdict line, stage-4 style: each criterion's number, the
# reported shares, then the label.
def _line(candidate: str, info: Mapping[str, Any]) -> str:
    """Return the candidate's verdict line."""
    signed, share = sd._signed, sd._share
    holds = "holds" if info["criteria"]["2_next_bar"] else "fails"
    rule, side = CANDIDATES[candidate]
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
        f"fired {share(info['acted_share'])}",
        f"tagged {share(info['tagged_share'])}",
        f"level reached {share(info['reached_share'])}",
        f"oracle capture {share(info['capture'])}",
    ]
    if rule == RESISTANCE_SKIP:
        parts.insert(7, f"waited {share(info['waited_share'])}")
    return f"{candidate} ({rule}, {side}): {'; '.join(parts)} - {info['label']}"


# --- S1g on the scorecard's payloads ---------------------------------------------


# The (line, window) summary row of a point-in-time scorecard payload at
# the registration's cost.
def _row(payload: Mapping[str, Any], window: str, cost: float = NOTCH_COST_BPS) -> dict:
    """Return the rule / point-in-time row, or raise when the payload lacks it."""
    for r in payload["rows"]:
        if (
            r["line"] == NOTCH_RULE_LINE
            and r["window"] == window
            and float(r["cost_bps"]) == cost
        ):
            return r
    raise KeyError(f"no {NOTCH_RULE_LINE!r} row for {window!r} at {cost:g} bp")


# The median-offset daily returns of the rule line on a window, paired
# session by session between two scorecard payloads (dates matched, both
# finite), as (notch, control).
def _paired_daily(
    notch: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> tuple[np.ndarray, np.ndarray]:
    """Return (notch daily, control daily) on the sessions both price."""
    start, end = notch["windows"][window]
    key = f"{NOTCH_COST_BPS:g}"
    a, b = notch["curves"][key], control["curves"][key]
    theirs = dict(zip(b["dates"], b["lines"][NOTCH_RULE_LINE], strict=True))
    xs, ys = [], []
    for day, value in zip(a["dates"], a["lines"][NOTCH_RULE_LINE], strict=True):
        if (start is not None and day < start) or (end is not None and day >= end):
            continue
        other = theirs.get(day)
        if value is None or other is None:
            continue
        if not (math.isfinite(value) and math.isfinite(other)):
            continue
        xs.append(value)
        ys.append(other)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


# The paired difference (notch minus control) of the rule line on a window:
# its length, mean in bp a day, Newey-West t at lag 20, and the moments for
# the deflated Sharpe.
def notch_paired(
    notch: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> dict[str, Any]:
    """Return the statistics of the notch's rule line minus the control's."""
    a, b = _paired_daily(notch, control, window)
    diff = a - b
    mom = candidate_stats.moments(diff)
    return {
        "window": window,
        "sessions": int(len(diff)),
        "mean_daily_bp": float(diff.mean() * 1e4) if len(diff) else math.nan,
        "hac_t": candidate_stats.hac_t(diff, HAC_LAG) if len(diff) > 2 else math.nan,
        "sharpe": mom.sharpe,
        "skew": mom.skew,
        "kurtosis": mom.kurtosis,
        "length": mom.length,
    }


# S1g's verdict from two point-in-time scorecard payloads (the incumbent
# and the notch, both `--graded-cap 0.25` at 20 offsets). REPLACES on the
# book gate: the paired daily difference at 25 bp on 2016-2023 >= +2.0 bp
# a session with Newey-West t >= 2, 2024-2026 not negative, above the
# control's CAGR at 15 of 20 offsets, the deflated Sharpe at the cumulative
# 464 >= 0.95 (`trial_variance`: the fill candidates' across-candidate
# variance from the study's payload; NaN leaves it unjudged and failing);
# or on drawdown: the median worst drawdown better by 3 points on both
# windows with the CAGR difference inside +-1 point on both. Else RECORD.
def notch_verdict(
    control: Mapping[str, Any],
    notch: Mapping[str, Any],
    trial_variance: float = math.nan,
) -> dict[str, Any]:
    """Return S1g's verdict record from the two payloads."""
    deciding = notch_paired(notch, control, NOTCH_DECIDING)
    recent = notch_paired(notch, control, NOTCH_RECENT)
    own = np.asarray(_row(notch, NOTCH_DECIDING)["cagrs"], dtype=float)
    theirs = np.asarray(_row(control, NOTCH_DECIDING)["cagrs"], dtype=float)
    above = int(np.nansum(own > theirs)) if len(own) == len(theirs) else 0
    dsr = math.nan
    if math.isfinite(trial_variance) and math.isfinite(deciding["sharpe"]):
        dsr = candidate_stats.deflated_sharpe(
            deciding["sharpe"],
            deciding["length"],
            deciding["skew"],
            deciding["kurtosis"],
            TRIALS["cumulative"],
            trial_variance,
        )
    gate = {
        "1_floor": sd.clears(deciding["mean_daily_bp"], deciding["hac_t"]),
        "2_not_negative_2024_2026": bool(
            math.isfinite(recent["mean_daily_bp"]) and recent["mean_daily_bp"] >= 0.0
        ),
        "3_offsets_positive": len(own) == len(theirs) and above >= OFFSETS_POSITIVE,
        "4_deflated_sharpe": bool(math.isfinite(dsr) and dsr >= DSR_GATE),
    }
    drawdown: dict[str, Any] = {}
    for window in (NOTCH_DECIDING, NOTCH_RECENT):
        a, b = _row(notch, window), _row(control, window)
        drawdown[window] = {
            "drawdown_notch": sd._f(a["median_drawdown"]),
            "drawdown_control": sd._f(b["median_drawdown"]),
            "drawdown_gain": sd._f(a["median_drawdown"]) - sd._f(b["median_drawdown"]),
            "cagr_notch": sd._f(a["median_cagr"]),
            "cagr_control": sd._f(b["median_cagr"]),
            "cagr_difference": sd._f(a["median_cagr"]) - sd._f(b["median_cagr"]),
        }
    drawdown_ok = all(
        math.isfinite(d["drawdown_gain"])
        and d["drawdown_gain"] >= NOTCH_DRAWDOWN_POINTS
        and math.isfinite(d["cagr_difference"])
        and abs(d["cagr_difference"]) <= NOTCH_CAGR_BAND
        for d in drawdown.values()
    )
    on_return = all(gate.values())
    label = REPLACES if (on_return or drawdown_ok) else RECORD
    reading = {
        "label": label,
        "replaces_on": [
            k for k, ok in (("return", on_return), ("drawdown", drawdown_ok)) if ok
        ],
        "gate": gate,
        "paired": {NOTCH_DECIDING: deciding, NOTCH_RECENT: recent},
        "offsets_above": above,
        "offsets": int(len(theirs)),
        "dsr": dsr,
        "trials": TRIALS["cumulative"],
        "trial_variance": trial_variance,
        "drawdown": drawdown,
        "drawdown_criterion": drawdown_ok,
        "cost_bps": NOTCH_COST_BPS,
        "notch_arm": notch.get("arm"),
        "control_arm": control.get("arm"),
    }
    reading["lines"] = _notch_lines(reading)
    return reading


# S1g's verdict lines: the gate's numbers, the drawdown reading, the label.
def _notch_lines(reading: Mapping[str, Any]) -> list[str]:
    """Return the notch verdict as lines."""
    signed = sd._signed
    d, r = reading["paired"][NOTCH_DECIDING], reading["paired"][NOTCH_RECENT]
    lines = [
        f"{NOTCH} (structure notch): paired {NOTCH_DECIDING} "
        f"{signed(d['mean_daily_bp'], 1)} bp/session (t {signed(d['hac_t'])}) over "
        f"{d['sessions']} sessions; {NOTCH_RECENT} {signed(r['mean_daily_bp'], 1)} "
        f"bp/session (t {signed(r['hac_t'])}); above the control at "
        f"{reading['offsets_above']} of {reading['offsets']} offsets; deflated "
        f"Sharpe {signed(reading['dsr'])} at {reading['trials']}"
    ]
    for window, v in reading["drawdown"].items():
        lines.append(
            f"  {window}: median worst drawdown {v['drawdown_notch'] * 100:+.1f}% "
            f"against {v['drawdown_control'] * 100:+.1f}% "
            f"({signed(v['drawdown_gain'] * 100, 1)} points); CAGR "
            f"{v['cagr_notch'] * 100:+.1f}% against {v['cagr_control'] * 100:+.1f}% "
            f"({signed(v['cagr_difference'] * 100, 1)} points)"
        )
    on = ", ".join(reading["replaces_on"]) or "neither the return gate nor drawdown"
    lines.append(f"  {reading['label']} ({on})")
    return lines
