"""Support and resistance: do dips into a level hold where dips into nothing continue?

The pre-registration is `docs/research/sr-levels-plan-2026-09-29.md`,
including its addendum. That addendum was written before any run, and it
changed two things after the synthetic null worlds failed: the match is on
the exact slot, and the t-statistic is month-clustered. This module is the
plan's event study and computes nothing the plan did not fix in advance. It
trades nothing and changes nothing on the board. The test that could is the
pair of fill conventions in `fill_timing` (`SR_CONVENTIONS`).

Events. On every point-in-time member session of every book name, every
regular fifteen-minute bar from slot 2 (10:00-10:15) is checked against the
22 levels of `sr_levels` in force during it, all known at the prior bar's
close. A support touch is a bar whose low enters the zone of a level below
the prior bar's close, with that bar closed above the zone. The touched zone
is the highest such level's; the touch records the families inside it and
its confluence (`sr_levels.touches`). Resistance touches mirror it.

Controls. Each touch is matched to non-level moves: bars of the same name, in
the same calendar year and the same fifteen-minute slot, on another member
session. They must have traded beyond the prior bar's close with no level
within CLEARANCE half-widths (`sr_levels.clear_moves`), and their close must
sit within MATCH_POINTS percentage points of the touch bar's close, both
measured from the session open. (A name has one bar per slot per session,
so every same-name control is from another session.) The control outcome is
the mean over every matched bar. If the name's year has none, the pooled
same-year set is used: every member name's candidates in that year and slot,
on other dates. A touch with no control either way is dropped. The match
rate is reported.

Outcomes, from the touch bar's close:

  r_close_bp  log return to the official close (the closing auction's first
              print, else the last regular bar's close)
  bounce_pp   support: the close above the zone's upper edge; resistance:
              below its lower edge. A control is scored against the touch's
              zone edges, as ratios to its own bar close.
  break_pp    support: the close below the lower edge; resistance: above the
              upper edge
  r_next_bp   the panel's adjusted close of the session to the next session's
  r_5_bp      and to the close five sessions on

Statistics. Per touch, D is the touch's outcome minus its controls' mean. A
cell's estimate is the mean of the daily cross-sectional average of D: each
date's touches across names are averaged first. That is a weighted mean,
sum(w_i D_i) with w_i = 1 / (dates x that date's touches). It is linear in
every observation: each touch enters with weight w_i, and each control bar
with minus its usage, the sum of w_i / n_i over the touches that average
it. Its t divides by the square root of the sum, over calendar months, of
the squared monthly sum of every observation's influence. Each observation
is credited to its own session's month. One trend day's control bars,
reused by a year of touches, are counted once, where they happened. A month
holds the touches and controls of the same dates (market moves), the same
session, and most of r_5's overlap.

The t is reported with at least MIN_CELL_DATES dates and MIN_MONTHS months.
The registered Newey-West t on the daily series is kept in every cell as
`t_daily_hac`, for the record. It ignores the control reuse and overstates
the evidence; the null worlds in the tests show it.

Cells are:

- side;
- population: every member, and names graded A/A+ at the prior close;
- window: 2016-2023 (choosing) and 2024-2026 (reported);
- group: all, each family, confluence 1 / 2 / 3+;
- outcome.

That is TRIALS = 640 cells, and every t is printed beside the Bonferroni
line BONFERRONI_T. One cell is the registered primary test (PRIMARY).
SUPPORTED needs its mean above zero with t >= PRIMARY_T on the choosing
window, and above zero on the reported window.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from backend.agents.trading.desk import policy_v4
from backend.market import fill_timing, sr_levels
from backend.market.candidate_stats import hac_t, normal_ppf
from backend.market.session_anatomy import json_ready
from backend.market.sip_cube import SessionCube

STUDY_VERSION = 1
PLAN = "docs/research/sr-levels-plan-2026-09-29.md"
WINDOWS: dict[str, tuple[date, date | None]] = {
    "2016-2023": (date(2016, 1, 1), date(2024, 1, 1)),
    "2024-2026": (date(2024, 1, 1), None),
}
CHOOSING = "2016-2023"
REPORTED = "2024-2026"
# A control's close must sit within this many percentage points of the
# touch bar's close, both measured from the session open.
MATCH_POINTS = 0.25
# Float slack on that window, so a hand-set 0.25 is inside it.
MATCH_SLACK = 1e-9
# No level within this many half-widths beyond a control bar's extreme.
CLEARANCE = 2.0
# Newey-West lag of the registered daily-series t, kept for the record.
HAC_LAG = 10
# A t on fewer dates, or fewer calendar-month clusters, is not reported.
MIN_CELL_DATES = 30
MIN_MONTHS = 12
# The panel sessions ahead of the forward outcomes.
FORWARD_SESSIONS = (1, 5)
OUTCOMES = ("r_close_bp", "bounce_pp", "break_pp", "r_next_bp", "r_5_bp")
# Log returns are reported in basis points, rates in percentage points.
OUTCOME_SCALE = {
    "r_close_bp": 1e4,
    "bounce_pp": 100.0,
    "break_pp": 100.0,
    "r_next_bp": 1e4,
    "r_5_bp": 1e4,
}
# Which control count divides each outcome's sum: every matched bar for the
# three same-session outcomes, the bars with a next / fifth close for the
# two forward returns.
COUNT_OF = (0, 0, 0, 1, 2)
POPULATIONS = ("members", "graded_a")
CONFLUENCE_GROUPS = ("confluence_1", "confluence_2", "confluence_3+")
GROUPS = ("all", *sr_levels.FAMILIES, *CONFLUENCE_GROUPS)
SIDES = sr_levels.SIDES
# The /4 policy's grade floor: the names it buys (A and A+).
GRADE_FLOOR = policy_v4.MIN_GRADE
FAMILY_ALPHA = 0.05
TRIALS = len(SIDES) * len(POPULATIONS) * len(WINDOWS) * len(GROUPS) * len(OUTCOMES)
BONFERRONI_T = normal_ppf(1.0 - FAMILY_ALPHA / (2.0 * TRIALS))
PRIMARY = {
    "side": sr_levels.SUPPORT,
    "population": "members",
    "group": "all",
    "outcome": "r_close_bp",
}
PRIMARY_T = 2.0
SUPPORTED = "SUPPORTED"
NOT_SUPPORTED = "NOT SUPPORTED"
# How a touch found its controls.
OWN_NAME = 0
POOLED = 1
UNMATCHED = 2

assert TRIALS == 640
assert len(COUNT_OF) == len(OUTCOMES)


@dataclass(frozen=True)
class SideEvents:
    """One side's touches and control candidates from one name, member sessions only."""

    touch_date: np.ndarray  # (M,) datetime64[D]
    touch_slot: np.ndarray  # (M,) int
    touch_depth: np.ndarray  # (M,) the bar close against the session open, points
    touch_families: np.ndarray  # (M,) int64 bitmask of sr_levels.FAMILIES
    touch_confluence: np.ndarray  # (M,) int
    touch_upper: np.ndarray  # (M,) log((L* + w) / the bar close)
    touch_lower: np.ndarray  # (M,) log((L* - w) / the bar close), -inf if L* <= w
    touch_graded: np.ndarray  # (M,) bool: graded A/A+ at the prior close
    touch_returns: np.ndarray  # (M, 3) log returns: to the close, next, five on
    control_date: np.ndarray  # (C,) datetime64[D]
    control_slot: np.ndarray  # (C,) int
    control_depth: np.ndarray  # (C,)
    control_returns: np.ndarray  # (C, 3)


@dataclass(frozen=True)
class NameEvents:
    """Everything one name contributes to the study, before matching."""

    ticker: str
    sides: dict[str, SideEvents]
    sessions: int  # cube sessions
    member_sessions: int  # of which point-in-time member sessions on the panel
    auction_closes: int  # member sessions whose official close is the auction print
    coverage: np.ndarray = field(
        default_factory=lambda: np.zeros(len(sr_levels.KINDS), dtype=np.int64)
    )  # (K,) member sessions with each level in force at slot 2


@dataclass(frozen=True)
class Matched:
    """One side's touches, pooled across names, with their controls by month."""

    date: np.ndarray  # (M,) datetime64[D]
    name: np.ndarray  # (M,) index into the names list
    graded: np.ndarray  # (M,) bool
    families: np.ndarray  # (M,) int64
    confluence: np.ndarray  # (M,) int
    touch: np.ndarray  # (M, 5) outcomes in OUTCOMES order, log / 0-1 units
    control: np.ndarray  # (M, 5) the controls' means, NaN where unmatched
    kind: np.ndarray  # (M,) OWN_NAME, POOLED or UNMATCHED
    controls: np.ndarray  # (M, 3) control bars averaged: all, with r_next, with r_5
    pair_touch: np.ndarray  # (P,) the touch a (touch, control month) pair belongs to
    pair_month: np.ndarray  # (P,) that month, as months since 1970-01
    pair_count: np.ndarray  # (P, 3) its control bars: all, with r_next, with r_5
    pair_sum: np.ndarray  # (P, 5) their outcomes' sums, as the touch scores them


# An empty SideEvents, for a name with no events on a side.
def _empty_side() -> SideEvents:
    """Return a SideEvents with no touches and no candidates."""
    day = np.zeros(0, dtype="datetime64[D]")
    return SideEvents(
        day,
        np.zeros(0, dtype=np.int64),
        np.zeros(0),
        np.zeros(0, dtype=np.int64),
        np.zeros(0, dtype=np.int64),
        np.zeros(0),
        np.zeros(0),
        np.zeros(0, dtype=bool),
        np.zeros((0, 3)),
        day.copy(),
        np.zeros(0, dtype=np.int64),
        np.zeros(0),
        np.zeros((0, 3)),
    )


# The log return from each cube session's panel close to the close `ahead`
# panel sessions later, NaN where the panel does not reach or either close is
# missing.
def _forward(
    adj_close: np.ndarray, pos: np.ndarray, ok: np.ndarray, ahead: int
) -> np.ndarray:
    """Return (N,) log(adj_close[pos + ahead] / adj_close[pos])."""
    out = np.full(len(pos), np.nan)
    reach = ok & (pos + ahead < len(adj_close))
    with np.errstate(all="ignore"):
        ratio = np.log(adj_close[pos[reach] + ahead] / adj_close[pos[reach]])
    out[reach] = np.where(np.isfinite(ratio), ratio, np.nan)
    return out


# One name's touches and control candidates on both sides, restricted to its
# point-in-time member sessions (`member`, on the panel's calendar). The
# levels come from `sr_levels` on the fills' own basis scale; `daily` holds
# this one name's daily structure (a one-column DailyLevels); `grades` is
# the restricted report's grade column, read at the prior session.
def name_events(
    ticker: str,
    cube: SessionCube,
    daily: sr_levels.DailyLevels,
    dates: np.ndarray,
    adj_close: np.ndarray,
    member: np.ndarray,
    grades: np.ndarray,
) -> NameEvents:
    """Return the NameEvents of one name."""
    if len(cube) == 0:
        return NameEvents(ticker, {s: _empty_side() for s in SIDES}, 0, 0, 0)
    adj_close = np.asarray(adj_close, dtype=float)
    pos, ok, scale = fill_timing.session_scale(cube, dates, adj_close)
    levels = sr_levels.for_cube(cube, daily, 0, pos, ok, scale)
    conf = sr_levels.confluence(levels)
    on = np.zeros(len(cube), dtype=bool)
    on[ok] = np.asarray(member, dtype=bool)[pos[ok]]
    graded = np.zeros(len(cube), dtype=bool)
    has_prior = ok & (pos >= 1)
    graded[has_prior] = np.asarray(grades)[pos[has_prior] - 1] >= GRADE_FLOOR
    official = fill_timing._official_close(cube)
    with np.errstate(all="ignore"):
        to_close = np.log(official[:, None] / cube.close)
        depth = 100.0 * (cube.close / cube.open[:, :1] - 1.0)
    forward = [_forward(adj_close, pos, ok, h) for h in FORWARD_SESSIONS]
    usable = on[:, None] & np.isfinite(to_close) & np.isfinite(depth)
    sides: dict[str, SideEvents] = {}
    for side in SIDES:
        touched = sr_levels.touches(levels, conf, side)
        clear = sr_levels.clear_moves(levels, side, CLEARANCE)
        n_t, s_t = np.nonzero(touched.hit & usable)
        n_c, s_c = np.nonzero(clear & usable)
        level = touched.level[n_t, s_t]
        width = levels.width[n_t]
        close = levels.close[n_t, s_t]
        with np.errstate(all="ignore"):
            upper = np.log((level + width) / close)
            lower = np.where(level > width, np.log((level - width) / close), -np.inf)
        sides[side] = SideEvents(
            touch_date=cube.dates[n_t].astype("datetime64[D]"),
            touch_slot=s_t.astype(np.int64),
            touch_depth=depth[n_t, s_t],
            touch_families=touched.families[n_t, s_t].astype(np.int64),
            touch_confluence=touched.confluence[n_t, s_t].astype(np.int64),
            touch_upper=upper,
            touch_lower=lower,
            touch_graded=graded[n_t],
            touch_returns=np.column_stack(
                [to_close[n_t, s_t], forward[0][n_t], forward[1][n_t]]
            ),
            control_date=cube.dates[n_c].astype("datetime64[D]"),
            control_slot=s_c.astype(np.int64),
            control_depth=depth[n_c, s_c],
            control_returns=np.column_stack(
                [to_close[n_c, s_c], forward[0][n_c], forward[1][n_c]]
            ),
        )
    coverage = np.isfinite(levels.levels[on, sr_levels.FIRST_SLOT, :]).sum(axis=0)
    return NameEvents(
        ticker=ticker,
        sides=sides,
        sessions=len(cube),
        member_sessions=int(on.sum()),
        auction_closes=int((on & np.isfinite(cube.auction_open)).sum()),
        coverage=coverage.astype(np.int64),
    )


# One panel column's daily structure as a one-name DailyLevels, so a worker
# receives only its own name's rows.
def column(daily: sr_levels.DailyLevels, j: int) -> sr_levels.DailyLevels:
    """Return the DailyLevels of panel column `j` alone."""
    return sr_levels.DailyLevels(
        dates=daily.dates,
        tickers=(daily.tickers[j],),
        levels=daily.levels[:, j : j + 1],
        width=daily.width[:, j : j + 1],
    )


# Every book name's events in this process: the daily structure once for
# the panel, then each name with a cube (the benchmark excluded) through
# `name_events` with its membership mask and grade columns.
def collect(
    cubes: Mapping[str, SessionCube],
    panel,
    mask: np.ndarray,
    grades: np.ndarray,
) -> list[NameEvents]:
    """Return the NameEvents of every panel name that has a cube."""
    daily = sr_levels.daily_levels(panel)
    out = []
    for j, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark or ticker not in cubes:
            continue
        out.append(
            name_events(
                ticker,
                cubes[ticker],
                column(daily, j),
                panel.dates,
                panel.adj_close[:, j],
                mask[:, j],
                grades[:, j],
            )
        )
    return out


# The calendar year of each date.
def _year(dates: np.ndarray) -> np.ndarray:
    """Return (M,) integer years."""
    return np.asarray(dates, dtype="datetime64[Y]").astype(np.int64) + 1970


# The calendar month of each date, as months since 1970-01: the cluster.
def month_of(dates: np.ndarray) -> np.ndarray:
    """Return (M,) integer months."""
    return np.asarray(dates, dtype="datetime64[M]").astype(np.int64)


# A touch's own outcomes in OUTCOMES order, in log / 0-1 units: the return
# to the close, bounce and break against its zone's edges (mirrored for
# resistance), and the two forward returns.
def _touch_outcomes(
    side: str, returns: np.ndarray, upper: np.ndarray, lower: np.ndarray
) -> np.ndarray:
    """Return (M, 5) outcomes."""
    to_close = returns[:, 0]
    above, below = to_close > upper, to_close < lower
    bounce, broke = (above, below) if side == sr_levels.SUPPORT else (below, above)
    return np.column_stack(
        [
            to_close,
            bounce.astype(float),
            broke.astype(float),
            returns[:, 1],
            returns[:, 2],
        ]
    )


@dataclass(frozen=True)
class _Block:
    """Controls matched to a set of touches: their means, and by calendar month."""

    means: np.ndarray  # (T, 5) the controls' mean outcomes, NaN without controls
    counts: np.ndarray  # (T, 3) control bars: all, with r_next, with r_5
    pair_row: np.ndarray  # (P,) which touch (row of the block)
    pair_month: np.ndarray  # (P,) the controls' month
    pair_count: np.ndarray  # (P, 3)
    pair_sum: np.ndarray  # (P, 5)


# The controls of a set of touches: `pick` (touches x control bars) says
# which bars each touch averages. Bounce and break score every control's
# return to the close against that touch's own zone edges; the forward
# returns average over the controls that have them. Everything is also
# summed by the control bars' calendar month, for the month-clustered t.
def _control_block(
    side: str,
    pick: np.ndarray,
    returns: np.ndarray,
    months: np.ndarray,
    upper: np.ndarray,
    lower: np.ndarray,
) -> _Block:
    """Return the controls' means, counts and per-month sums."""
    chosen = pick.astype(float)
    to_close = returns[:, 0]
    above = to_close[None, :] > upper[:, None]
    below = to_close[None, :] < lower[:, None]
    bounce, broke = (above, below) if side == sr_levels.SUPPORT else (below, above)
    have_next, have_five = np.isfinite(returns[:, 1]), np.isfinite(returns[:, 2])
    unique, where = np.unique(months, return_inverse=True)
    onehot = np.zeros((len(months), len(unique)))
    onehot[np.arange(len(months)), where] = 1.0
    counts = np.stack(
        [
            chosen @ onehot,
            (chosen * have_next[None, :]) @ onehot,
            (chosen * have_five[None, :]) @ onehot,
        ],
        axis=2,
    )  # (T, U, 3)
    sums = np.stack(
        [
            (chosen * to_close[None, :]) @ onehot,
            (pick & bounce).astype(float) @ onehot,
            (pick & broke).astype(float) @ onehot,
            (chosen * np.where(have_next, returns[:, 1], 0.0)[None, :]) @ onehot,
            (chosen * np.where(have_five, returns[:, 2], 0.0)[None, :]) @ onehot,
        ],
        axis=2,
    )  # (T, U, 5)
    total_counts = counts.sum(axis=1)
    denominator = total_counts[:, list(COUNT_OF)]
    with np.errstate(all="ignore"):
        means = np.where(denominator > 0, sums.sum(axis=1) / denominator, np.nan)
    row, month = np.nonzero(counts[:, :, 0] > 0)
    return _Block(
        means=means,
        counts=total_counts.astype(np.int64),
        pair_row=row,
        pair_month=unique[month],
        pair_count=counts[row, month].astype(np.int64),
        pair_sum=sums[row, month],
    )


# Whether each control depth sits inside each touch's window.
def _near(touch_depth: np.ndarray, control_depth: np.ndarray) -> np.ndarray:
    """Return (T, C) bool: |control - touch| <= MATCH_POINTS."""
    gap = np.abs(control_depth[None, :] - touch_depth[:, None])
    return gap <= MATCH_POINTS + MATCH_SLACK


# Match one side's touches to their controls across every name. First the
# same name, year and slot (every such bar is from another session). Then,
# for a touch with none, the pooled same-year set: every name's candidates
# in that year and slot, on other dates. Otherwise the touch is unmatched.
# The per-month control sums of every matched touch are kept for the t.
def match(side: str, names: list[NameEvents]) -> Matched:
    """Return the side's Matched touches."""
    parts = [n.sides[side] for n in names] or [_empty_side()]
    who_t = np.concatenate(
        [np.full(len(p.touch_date), i, dtype=np.int64) for i, p in enumerate(parts)]
    )
    who_c = np.concatenate(
        [np.full(len(p.control_date), i, dtype=np.int64) for i, p in enumerate(parts)]
    )

    # The same field of every name's SideEvents, stacked.
    def cat(attr: str) -> np.ndarray:
        return np.concatenate([getattr(p, attr) for p in parts])

    t_date, t_slot, t_depth = cat("touch_date"), cat("touch_slot"), cat("touch_depth")
    t_upper, t_lower = cat("touch_upper"), cat("touch_lower")
    t_returns = cat("touch_returns").reshape(-1, 3)
    c_date, c_slot, c_depth = (
        cat("control_date"),
        cat("control_slot"),
        cat("control_depth"),
    )
    c_returns = cat("control_returns").reshape(-1, 3)
    c_month = month_of(c_date)
    touches = len(t_date)
    control = np.full((touches, len(OUTCOMES)), np.nan)
    counts = np.zeros((touches, 3), dtype=np.int64)
    kind = np.full(touches, UNMATCHED, dtype=np.int64)
    pairs: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    t_year, c_year = _year(t_date), _year(c_date)

    # Record a block's results for the touches `rows` that found controls.
    def keep(rows: np.ndarray, block: _Block, how: int) -> None:
        found = block.counts[:, 0] > 0
        control[rows[found]] = block.means[found]
        counts[rows[found]] = block.counts[found]
        kind[rows[found]] = how
        live = found[block.pair_row]
        pairs.append(
            (
                rows[block.pair_row[live]],
                block.pair_month[live],
                block.pair_count[live],
                block.pair_sum[live],
            )
        )

    # Own name: group by (name, year, slot).
    t_key = (who_t * 10_000 + t_year) * 100 + t_slot
    c_key = (who_c * 10_000 + c_year) * 100 + c_slot
    c_order = np.argsort(c_key, kind="stable")
    c_sorted = c_key[c_order]
    t_order = np.argsort(t_key, kind="stable")
    keys, starts = np.unique(t_key[t_order], return_index=True)
    stops = np.append(starts[1:], touches)[: len(starts)]
    for key, start, stop in zip(keys, starts, stops, strict=True):
        rows = t_order[start:stop]
        lo = np.searchsorted(c_sorted, key, "left")
        hi = np.searchsorted(c_sorted, key, "right")
        if hi <= lo:
            continue
        cols = c_order[lo:hi]
        pick = _near(t_depth[rows], c_depth[cols])
        block = _control_block(
            side, pick, c_returns[cols], c_month[cols], t_upper[rows], t_lower[rows]
        )
        keep(rows, block, OWN_NAME)
    # Pooled: every name's candidates in the touch's year and slot, other dates.
    waiting = np.flatnonzero(kind == UNMATCHED)
    pool_key = c_year * 100 + c_slot
    pool_order = np.argsort(pool_key, kind="stable")
    pool_sorted = pool_key[pool_order]
    w_key = t_year[waiting] * 100 + t_slot[waiting]
    for key in np.unique(w_key):
        rows = waiting[w_key == key]
        lo = np.searchsorted(pool_sorted, key, "left")
        hi = np.searchsorted(pool_sorted, key, "right")
        if hi <= lo:
            continue
        cols = pool_order[lo:hi]
        pick = _near(t_depth[rows], c_depth[cols]) & (
            t_date[rows][:, None] != c_date[cols][None, :]
        )
        block = _control_block(
            side, pick, c_returns[cols], c_month[cols], t_upper[rows], t_lower[rows]
        )
        keep(rows, block, POOLED)
    if pairs:
        pair_touch = np.concatenate([p[0] for p in pairs])
        pair_month = np.concatenate([p[1] for p in pairs])
        pair_count = np.concatenate([p[2] for p in pairs]).reshape(-1, 3)
        pair_sum = np.concatenate([p[3] for p in pairs]).reshape(-1, len(OUTCOMES))
    else:
        pair_touch = np.zeros(0, dtype=np.int64)
        pair_month = np.zeros(0, dtype=np.int64)
        pair_count = np.zeros((0, 3), dtype=np.int64)
        pair_sum = np.zeros((0, len(OUTCOMES)))
    return Matched(
        date=t_date.astype("datetime64[D]"),
        name=who_t,
        graded=cat("touch_graded").astype(bool),
        families=cat("touch_families").astype(np.int64),
        confluence=cat("touch_confluence").astype(np.int64),
        touch=_touch_outcomes(side, t_returns, t_upper, t_lower),
        control=control,
        kind=kind,
        controls=counts,
        pair_touch=pair_touch.astype(np.int64),
        pair_month=pair_month.astype(np.int64),
        pair_count=pair_count,
        pair_sum=pair_sum,
    )


# Dates inside [start, end) as a mask.
def _in_window(dates: np.ndarray, start: date | None, end: date | None) -> np.ndarray:
    """Return (M,) bool."""
    days = np.asarray(dates, dtype="datetime64[D]")
    keep = np.ones(len(days), dtype=bool)
    if start is not None:
        keep &= days >= np.datetime64(start, "D")
    if end is not None:
        keep &= days < np.datetime64(end, "D")
    return keep


# The touches of one group: all, those whose zone holds a family, or a
# confluence bucket.
def group_mask(matched: Matched, group: str) -> np.ndarray:
    """Return (M,) bool for `group`."""
    if group == "all":
        return np.ones(len(matched.date), dtype=bool)
    if group in sr_levels.FAMILIES:
        bit = sr_levels.FAMILIES.index(group)
        return (matched.families >> bit & 1).astype(bool)
    if group == "confluence_1":
        return matched.confluence == 1
    if group == "confluence_2":
        return matched.confluence == 2
    if group == "confluence_3+":
        return matched.confluence >= 3
    raise ValueError(f"unknown group {group!r}")


# The month-clustered t of a cell's estimate, sum(w_i (y_i - c_i)) over
# the touches used. Each touch contributes w_i (y_i - mu_T) in its own
# month. Each (touch, control month) pair contributes
# -(w_i / n_i) (sum of the controls' outcomes that month - mu_C x their
# count) in the controls' month. Here n_i is the touch's control count for
# the outcome, and mu_T and mu_C the weighted touch and control means. The
# squared monthly sums, times G / (G - 1) for G months, are the variance.
# Returns (t, G); t is NaN below MIN_MONTHS.
def month_clustered_t(
    matched: Matched,
    used: np.ndarray,
    weights: np.ndarray,
    k: int,
    scale: float,
    estimate: float,
) -> tuple[float, int]:
    """Return (t, months) for the cell whose touches are `used` with `weights`."""
    touch = matched.touch[used, k] * scale
    control = matched.control[used, k] * scale
    mu_t = float((weights * touch).sum())
    mu_c = float((weights * control).sum())
    per_touch = np.zeros(len(matched.date))
    per_touch[used] = weights / matched.controls[used, COUNT_OF[k]]
    share = per_touch[matched.pair_touch]
    live = share > 0
    pair_part = -share[live] * (
        matched.pair_sum[live, k] * scale - mu_c * matched.pair_count[live, COUNT_OF[k]]
    )
    months = np.concatenate([month_of(matched.date[used]), matched.pair_month[live]])
    parts = np.concatenate([weights * (touch - mu_t), pair_part])
    unique, where = np.unique(months, return_inverse=True)
    sums = np.bincount(where, weights=parts, minlength=len(unique))
    clusters = len(unique)
    variance = float((sums**2).sum()) * clusters / max(clusters - 1, 1)
    if clusters < MIN_MONTHS or variance <= 0:
        return math.nan, clusters
    return estimate / math.sqrt(variance), clusters


# One cell: the touches selected and their difference from their controls
# on one outcome. The estimate averages across names within each date, then
# over dates. It carries the month-clustered t (`month_clustered_t`, NaN
# under MIN_CELL_DATES dates or MIN_MONTHS months), whether that t clears
# the Bonferroni line, and, for the record, the registered Newey-West t on
# the daily series. `inverse` maps each touch to its date's position in the
# side's sorted distinct dates.
def cell(
    matched: Matched, select: np.ndarray, outcome: str, inverse: np.ndarray, days: int
) -> dict[str, Any]:
    """Return one cell's statistics."""
    k = OUTCOMES.index(outcome)
    scale = OUTCOME_SCALE[outcome]
    touch = matched.touch[:, k] * scale
    control = matched.control[:, k] * scale
    diff = touch - control
    use = select & np.isfinite(diff)
    n = int(use.sum())
    record: dict[str, Any] = {
        "touches": n,
        "dates": 0,
        "months": 0,
        "touch_mean": math.nan,
        "control_mean": math.nan,
        "diff_per_touch": math.nan,
        "diff": math.nan,
        "t": math.nan,
        "beyond_bonferroni": False,
        "t_daily_hac": math.nan,
    }
    if n == 0:
        return record
    counts = np.bincount(inverse[use], minlength=days)
    sums = np.bincount(inverse[use], weights=diff[use], minlength=days)
    daily = sums[counts > 0] / counts[counts > 0]
    used = np.flatnonzero(use)
    weights = 1.0 / (counts[inverse[used]] * len(daily))
    estimate = float((weights * diff[used]).sum())
    enough = len(daily) >= MIN_CELL_DATES
    t, months = month_clustered_t(matched, used, weights, k, scale, estimate)
    t = t if enough else math.nan
    record.update(
        {
            "dates": int(len(daily)),
            "months": months,
            "touch_mean": float(touch[use].mean()),
            "control_mean": float(control[use].mean()),
            "diff_per_touch": float(diff[use].mean()),
            "diff": estimate,
            "t": t,
            "beyond_bonferroni": bool(math.isfinite(t) and abs(t) >= BONFERRONI_T),
            "t_daily_hac": hac_t(daily, HAC_LAG) if enough else math.nan,
        }
    )
    return record


# Every registered cell of one side: population x window x group x outcome.
def side_cells(side: str, matched: Matched) -> list[dict[str, Any]]:
    """Return the side's cells in registered order."""
    _, inverse = np.unique(matched.date, return_inverse=True)
    days = int(inverse.max()) + 1 if len(inverse) else 0
    everyone = np.ones(len(matched.date), dtype=bool)
    groups = {g: group_mask(matched, g) for g in GROUPS}
    out = []
    for population in POPULATIONS:
        people = matched.graded if population == "graded_a" else everyone
        for window, (start, end) in WINDOWS.items():
            inside = people & _in_window(matched.date, start, end)
            for group in GROUPS:
                select = inside & groups[group]
                for outcome in OUTCOMES:
                    record = {
                        "side": side,
                        "population": population,
                        "window": window,
                        "group": group,
                        "outcome": outcome,
                    }
                    record.update(cell(matched, select, outcome, inverse, days))
                    out.append(record)
    return out


# How each side's touches found controls, per window: the count, the shares
# matched in the name's own year, from the pooled set and not at all, and
# the median number of control bars behind a matched touch.
def match_summary(matched: Matched) -> dict[str, dict[str, Any]]:
    """Return {window: match counts and rates}."""
    out = {}
    for window, (start, end) in WINDOWS.items():
        inside = _in_window(matched.date, start, end)
        total = int(inside.sum())
        by_kind = {
            label: int((inside & (matched.kind == how)).sum())
            for label, how in (
                ("own_name", OWN_NAME),
                ("pooled", POOLED),
                ("unmatched", UNMATCHED),
            )
        }
        found = inside & (matched.kind != UNMATCHED)
        out[window] = {
            "touches": total,
            **by_kind,
            **{
                f"{label}_rate": (count / total if total else math.nan)
                for label, count in by_kind.items()
            },
            "median_controls": float(np.median(matched.controls[found, 0]))
            if found.any()
            else math.nan,
        }
    return out


# What the touches were, per window: how many held each family inside their
# zone and how many had each confluence.
def touch_summary(matched: Matched) -> dict[str, dict[str, Any]]:
    """Return {window: {"touches", "families": counts, "confluence": counts}}."""
    out = {}
    for window, (start, end) in WINDOWS.items():
        inside = _in_window(matched.date, start, end)
        out[window] = {
            "touches": int(inside.sum()),
            "families": {
                f: int((inside & group_mask(matched, f)).sum())
                for f in sr_levels.FAMILIES
            },
            "confluence": {
                g: int((inside & group_mask(matched, g)).sum())
                for g in CONFLUENCE_GROUPS
            },
        }
    return out


# Whether a number is finite (None, as JSON writes NaN, is not).
def _finite(x: Any) -> bool:
    """Return True for a finite float."""
    return x is not None and math.isfinite(float(x))


# The registered primary test read off the cells: support touches, every
# member, all touches, the return to the close, on the choosing window
# (mean above zero with t >= PRIMARY_T) and the reported one (mean above
# zero). Anything else, including a missing number, is NOT SUPPORTED.
def primary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the primary test's two cells and its reading."""

    # The cell of the primary on one window, empty when absent.
    def at(window: str) -> dict[str, Any]:
        for c in cells:
            if c["window"] == window and all(c[k] == v for k, v in PRIMARY.items()):
                return c
        return {}

    choose, later = at(CHOOSING), at(REPORTED)
    diff = choose.get("diff", math.nan)
    t = choose.get("t", math.nan)
    later_diff = later.get("diff", math.nan)
    supported = bool(
        _finite(diff)
        and _finite(t)
        and diff > 0
        and t >= PRIMARY_T
        and _finite(later_diff)
        and later_diff > 0
    )
    return {
        "cell": dict(PRIMARY),
        "threshold_t": PRIMARY_T,
        "choosing": choose,
        "reported": later,
        "verdict": SUPPORTED if supported else NOT_SUPPORTED,
    }


# The study on every name's events: match each side, score every cell, read
# the primary test, and gather the match rates, the touch counts, the level
# coverage and the official-close source. JSON-ready.
def study(names: list[NameEvents]) -> dict[str, Any]:
    """Return the study payload."""
    cells: list[dict[str, Any]] = []
    matches: dict[str, Any] = {}
    touched: dict[str, Any] = {}
    for side in SIDES:
        matched = match(side, names)
        cells.extend(side_cells(side, matched))
        matches[side] = match_summary(matched)
        touched[side] = touch_summary(matched)
    members = sum(n.member_sessions for n in names)
    coverage = (
        np.sum([n.coverage for n in names], axis=0)
        if names
        else np.zeros(len(sr_levels.KINDS))
    )
    auction = sum(n.auction_closes for n in names)
    return json_ready(
        {
            "study": "sr_levels",
            "version": STUDY_VERSION,
            "plan": PLAN,
            "choosing_window": CHOOSING,
            "reported_window": REPORTED,
            "windows": {
                k: [s.isoformat() if s else None, e.isoformat() if e else None]
                for k, (s, e) in WINDOWS.items()
            },
            "constants": {
                "levels": list(sr_levels.KINDS),
                "families": list(sr_levels.FAMILIES),
                "first_slot": sr_levels.FIRST_SLOT,
                "atr_share": sr_levels.ATR_SHARE,
                "atr_sessions": sr_levels.ATR_SESSIONS,
                "min_width": sr_levels.MIN_WIDTH,
                "swing": sr_levels.daily_structure.SWING,
                "swing_horizons": list(sr_levels.SWING_HORIZONS),
                "profile_sessions": sr_levels.PROFILE_SESSIONS,
                "profile_bin": sr_levels.PROFILE_BIN,
                "match": (
                    "same name, year and fifteen-minute slot; else pooled year and slot"
                ),
                "match_points": MATCH_POINTS,
                "clearance": CLEARANCE,
                "t": "month-clustered on every observation's influence",
                "min_cell_dates": MIN_CELL_DATES,
                "min_months": MIN_MONTHS,
                "hac_lag_of_t_daily_hac": HAC_LAG,
                "grade_floor": GRADE_FLOOR,
                "vwap": (
                    "proxy: bar closes weighted by bar volume, through the prior bar"
                ),
            },
            "trials": TRIALS,
            "family_alpha": FAMILY_ALPHA,
            "bonferroni_t": BONFERRONI_T,
            "primary": primary(cells),
            "bonferroni_survivors": [c for c in cells if c["beyond_bonferroni"]],
            "match": matches,
            "touches": touched,
            "coverage": {
                k: (float(c / members) if members else math.nan)
                for k, c in zip(sr_levels.KINDS, coverage, strict=True)
            },
            "official_close": {"auction": auction, "last_bar": members - auction},
            "names": len([n for n in names if n.member_sessions]),
            "tickers": [n.ticker for n in names],
            "sessions": int(sum(n.sessions for n in names)),
            "member_sessions": int(members),
            "cells": cells,
        }
    )


# One line per cell of a payload beyond the Bonferroni line.
def survivors_text(payload: dict[str, Any]) -> list[str]:
    """Return one line per Bonferroni survivor."""
    return [
        f"{c['side']} / {c['population']} / {c['window']} / {c['group']} / "
        f"{c['outcome']}: {c['diff']:+.2f} (t {c['t']:+.2f})"
        for c in payload["bonferroni_survivors"]
    ]


# Cells of a payload by their registered key, for rendering.
def by_key(cells: Iterable[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
    """Return {(side, population, window, group, outcome): cell}."""
    return {
        (c["side"], c["population"], c["window"], c["group"], c["outcome"]): c
        for c in cells
    }
