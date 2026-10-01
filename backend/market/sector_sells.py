"""Sector-aware sells S2: don't sell a downgraded name into its own peer group's rally.

`docs/research/sector-sells-plan-2026-10-01.md` registers everything here;
this module computes nothing the plan did not fix.

**The peer group** is computed from prices, point in time, never from a
sector label: at every session t, each name's daily log returns over the
60 sessions t-59..t (closes t-60..t) are regressed on SPY's (the panel's
benchmark) with an intercept, and the residuals correlated. The name's
peers P_i(t) are the k = 5 eligible names with the highest residual
correlation (ties by panel column); a peer must have a complete window, a
non-zero residual variance and be a point-in-time member at t. sigma_g(t)
is the standard deviation (ddof 1) over t-19..t of the peers' equal-weight
daily log return. Nothing after t enters t's group (`peer_groups`).

**The peer group's morning** R_g(t) is the equal-weight mean over the peers
with a complete cube session at t+1 of ln(first-bar close(t+1) / adjusted
close(t)), on the adjusted basis (`stage4_labels.cube_scale`); undefined
with fewer than 3 of the 5 priced.

**The control** is the board's sell rule as S1f priced it
(`structure_rules`): the first 15-minute bar of t+1 closing at or above
open x 1.01, else the official close. The orders are stage 4's
(`stage4_orders`: `ew-redeploy` under `graded-equal-weight/5`, executed
basis, 20 offsets, the median offset's statistics).

**The candidates**, each priced against the control on the sells in its
scope (every other sell fills as the control, g = 0):

- `G1` (`peer_rally_defer`, downgrade sells - `rotation_exit` and
  `reset_exit`): when R_g(t) > sigma_g(t) the sell is not sent in t+1; it
  is filled in t+2 by the control rule, wait 1, drift-adjusted g - mu (a
  sell that waits holds the stock); unpriced without a complete t+2.
- `G2` (`peer_rally_close`, downgrade sells): when R_g(t) > ln(1.01) the
  sell fills at the official close of t+1 instead of the pop rule.
- `G3` (`peer_rally_defer` on trims and exits graded C): G1's rule on the
  sells whose grade at t is not B; grade-B exits are the control.

Event (FOMC) sells are in no scope. A rule that does not fire leaves the
control's fill, slot and wait to the bit (`never=True` is the null test).

**Statistics and verdict** are structure-rules' (`adaptive_entry.
summarize` and `judge` through `structure_rules.Book`): REPLACES when all
six criteria hold at the median offset - (1) model window 2018-01-02..
2023-12-29 >= +2.0 bp of equity a session at Newey-West t (lag 20) >= 2;
(2) the next-bar run holds the floor; (3) 2024-2026 not negative; (4) the
deflated Sharpe at N = 3 >= 0.95 (cumulative 485 beside it); (5) the
drift-adjusted mean >= +1.0 bp at t >= 2; (6) positive at 15 of 20 offsets
- else "RECORD: real but immaterial" when the per re-timed order mean is
>= 25 bp at a clustered t >= 3 with (1) failing, else RECORD.

**Reported, never deciding:** the firing rates, the reading by grade and
by detail, every 2026 sell a rule changed, the 2026-10-01 COHR case, the
peer groups of COHR, AAOI, NVDA and OKLO on 2026-09-30, the mean peer
correlation and the peer groups' turnover.
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
from backend.market import peer_groups as pg
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market import structure_rules as sr
from backend.market.sip_cube import SessionCube

PLAN = "docs/research/sector-sells-plan-2026-10-01.md"
STUDY = "sector_sells"
SELL = "sell"
CONTROL = lab.CONTROL
PEER_DEFER = "peer_rally_defer"
PEER_CLOSE = "peer_rally_close"
RULES = (CONTROL, PEER_DEFER, PEER_CLOSE)
# The scopes: downgrade sells (graded below A at t, a rotation or reset
# exit), and every non-event sell not graded B (trims and exits to C).
DOWNGRADE = "downgrade"
NOT_B = "not_b"
DOWNGRADE_DETAILS = (so.ROTATION_EXIT, so.RESET_EXIT)
SCOPE_DETAILS = (so.ROTATION_EXIT, so.RESET_EXIT, so.TRIM)
# The three registered candidates, in the plan's order: (rule, scope).
CANDIDATES: dict[str, tuple[str, str]] = {
    "G1": (PEER_DEFER, DOWNGRADE),
    "G2": (PEER_CLOSE, DOWNGRADE),
    "G3": (PEER_DEFER, NOT_B),
}
# The plan's fixed parameters.
# They live in `peer_groups`, which the live desk imports too, so the rule
# the desk would trade is the rule priced here.
K_PEERS = pg.K_PEERS
CORR_SESSIONS = pg.CORR_SESSIONS
PEER_SIGMA_SESSIONS = pg.PEER_SIGMA_SESSIONS
MIN_PRICED_PEERS = pg.MIN_PRICED_PEERS
DIP = fill_timing.DIP
CLOSE_THRESHOLD = pg.CLOSE_THRESHOLD
# The peer-group computation, shared with the desk (`peer_groups`).
PeerGroups = pg.PeerGroups
log_returns = pg.log_returns
residuals = pg.residuals
session_peers = pg.session_peers
peer_groups = pg.peer_groups
# The criteria (structure-rules', stage 4's for one side).
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
# Three registered; cumulative 482 -> 485.
TRIALS = {"registered": 3, "cumulative": 485}
MODEL = sd.MODEL
REPORTED = sd.REPORTED
MODEL_START = sd.DEFAULT_MODEL_START
REPLACES = sd.REPLACES
RECORD = sd.RECORD
IMMATERIAL = sd.IMMATERIAL
GROUPS = ae.GROUPS
# The reported cases: the 2026-10-01 COHR sell (decided 2026-09-30) and the
# peer groups the plan names on that date.
CASE_DATE = date(2026, 9, 30)
CASE_TICKER = "COHR"
NAMED = ("COHR", "AAOI", "NVDA", "OKLO")
# The window the changed-sells list covers.
CHANGED_FROM = date(2026, 1, 1)

assert DIP == 0.01
assert TRIALS["registered"] == len(CANDIDATES)
assert (FLOOR_BP, FLOOR_T, DSR_GATE, OFFSETS, OFFSETS_POSITIVE, HAC_LAG) == (
    2.0,
    2.0,
    0.95,
    20,
    15,
    20,
)


# --- the peer groups ---------------------------------------------------------


# Each name's first-bar return of t+1 from the adjusted close of t, on the
# adjusted basis: ln(first-bar close(t+1) x scale(t+1) / adjusted close(t));
# NaN where t+1 is not a complete cube session or the name has no cube.
def first_bar_returns(
    dates: np.ndarray,
    tickers: Sequence[str],
    adj_close: np.ndarray,
    cubes: Mapping[str, SessionCube],
) -> np.ndarray:
    """Return the (T, N) first-bar log returns, indexed by the decision session t."""
    closes = np.asarray(adj_close, dtype=float)
    dates = np.asarray(dates, dtype="datetime64[D]")
    out = np.full(closes.shape, np.nan)
    for j, ticker in enumerate(tickers):
        cube = cubes.get(str(ticker))
        if cube is None or not len(cube):
            continue
        rows = lab.cube_rows(dates, cube)
        pos, on, scale = fill_timing.session_scale(cube, dates, closes[:, j])
        per = np.full(len(dates), np.nan)
        per[pos[on]] = scale[on]
        first = np.full(len(dates), np.nan)
        hit = rows >= 0
        first[hit] = cube.close[rows[hit], 0] * per[hit]
        with np.errstate(all="ignore"):
            out[:-1, j] = np.log(first[1:] / closes[:-1, j])
    return out


# R_g on every (t, name): the mean of the peers' first-bar returns of t+1
# over the peers priced, when at least MIN_PRICED_PEERS are; with the
# count of peers priced.
def peer_morning(
    groups: PeerGroups, first: np.ndarray, min_priced: int = MIN_PRICED_PEERS
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((T, N) R_g, (T, N) peers priced)."""
    length = groups.members.shape[0]
    idx = np.where(groups.members >= 0, groups.members, 0)
    values = np.asarray(first, dtype=float)[np.arange(length)[:, None, None], idx]
    values[groups.members < 0] = np.nan
    count = np.isfinite(values).sum(axis=2)
    with np.errstate(all="ignore"):
        mean = np.where(count > 0, np.nansum(values, axis=2) / np.maximum(count, 1), 0)
    ok = groups.has & (count >= min_priced)
    return np.where(ok, mean, np.nan), count


# Where each rule fires: G1/G3's deferral when R_g > sigma_g, G2's close
# when R_g > ln(1.01); `never` (the null test) fires nowhere.
def fire_masks(
    groups: PeerGroups, morning: np.ndarray, never: bool = False
) -> dict[str, np.ndarray]:
    """Return {rule: (T, N) bool}."""
    shape = np.shape(morning)
    if never:
        return {PEER_DEFER: np.zeros(shape, bool), PEER_CLOSE: np.zeros(shape, bool)}
    defer = pg.defer_fires(morning, groups.sigma)
    close = pg.close_fires(morning)
    return {PEER_DEFER: defer, PEER_CLOSE: close}


# --- the fills ---------------------------------------------------------------


# The control and the two rules for every decision session of one name, on
# the adjusted basis (`structure_rules.Fills`; `tagged` is where the rule's
# trigger held on a priced session). `defer` and `close` are the name's
# (T,) fire masks. Unfired sessions copy the control's price, reached,
# slot and wait.
def name_fills(
    series: lab.NameSeries,
    cube: SessionCube,
    defer: np.ndarray,
    close: np.ndarray,
    next_bar: bool = False,
) -> dict[str, sr.Fills]:
    """Return {rule: Fills} for one name."""
    length = len(series.dates)
    if not len(cube):
        return {rule: sr._empty(length) for rule in RULES}
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
    defer = np.asarray(defer, dtype=bool) & ok
    close = np.asarray(close, dtype=bool) & ok
    c_price, c_hit, c_slot = sr._close_rule(
        cube, SELL, fill_timing._dip_level(cube, SELL), next_bar
    )
    ones = np.ones(length, dtype=bool)
    out = {CONTROL: sr._read(c_price, c_hit, c_slot, ahead, scale1, ok, ones)}
    # G1/G3: a fired sell is re-planned for t+2 and filled there by the
    # control rule, wait 1; without t+2 it is unpriced.
    wait = sr._read(c_price, c_hit, c_slot, ahead, scale1, ok, defer, defer)
    priced2 = defer & ok2
    wait.price[defer] = np.nan
    wait.price[priced2] = c_price[ahead2[priced2]] * scale2[priced2]
    wait.reached[defer] = False
    wait.reached[priced2] = c_hit[ahead2[priced2]]
    wait.slot[defer] = -1
    wait.slot[priced2] = np.where(c_hit[ahead2[priced2]], c_slot[ahead2[priced2]], -1)
    wait.wait[priced2] = 1
    wait.active[defer & ~ok2] = False
    out[PEER_DEFER] = wait
    # G2: a fired sell fills at the official close of t+1.
    official = fill_timing._official_close(cube)
    moc = sr._read(c_price, c_hit, c_slot, ahead, scale1, ok, close, close)
    moc.price[close] = official[ahead[close]] * scale1[close]
    moc.reached[close] = False
    moc.slot[close] = -1
    out[PEER_CLOSE] = moc
    return out


@dataclass(frozen=True)
class Market:
    """Everything the engine reads besides the orders, on the panel's (T, N) grid."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    fills: sr.Grid  # bar-close fills, keyed by rule
    next_bar: sr.Grid  # next-bar fills
    oracle: np.ndarray  # (T, N) the best bar close of t+1 (a sell's), adjusted
    oracle_five: np.ndarray  # (T, N) stage 4's five-session sell oracle
    grades: np.ndarray  # (T, N) the desk grade of the report the orders came from
    closes: np.ndarray  # (T, N) adjusted closes (the drift)
    peers: PeerGroups
    morning: np.ndarray  # (T, N) R_g
    priced_peers: np.ndarray  # (T, N) peers priced at t+1
    fire: dict[str, np.ndarray]  # rule -> (T, N) the trigger held


# Every name's fills on the panel's grid for both fill modes, the sell
# oracles, the peer groups (membership `mask`, None for every name), R_g
# and the fire masks, and the coverage. `never` builds the null grids.
def fill_grids(
    panel: Any,
    cubes: Mapping[str, SessionCube],
    mask: np.ndarray | None = None,
    never: bool = False,
) -> tuple[sr.Grid, sr.Grid, dict[str, Any], dict[str, Any]]:
    """Return (bar-close grid, next-bar grid, the peer block, coverage)."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    tickers = tuple(str(t) for t in panel.tickers)
    market = tickers.index(str(panel.benchmark))
    adj = np.asarray(panel.adj_close, dtype=float)
    groups = peer_groups(dates, tickers, adj, market, mask)
    first = first_bar_returns(dates, tickers, adj, cubes)
    morning, priced = peer_morning(groups, first)
    fire = fire_masks(groups, morning, never)
    shape = (len(dates), len(tickers))
    grids = {
        mode: sr.Grid(
            next_bar=mode,
            price={r: np.full(shape, np.nan) for r in RULES},
            reached={r: np.zeros(shape, dtype=bool) for r in RULES},
            active={r: np.zeros(shape, dtype=bool) for r in RULES},
            slot={r: np.full(shape, -1, dtype=np.int64) for r in RULES},
            wait={r: np.zeros(shape, dtype=np.int64) for r in RULES},
            tagged={r: np.zeros(shape, dtype=bool) for r in RULES},
        )
        for mode in (False, True)
    }
    oracle = np.full(shape, np.nan)
    oracle_five = np.full(shape, np.nan)
    covered: list[str] = []
    for j, ticker in enumerate(tickers):
        if j == market:
            continue
        cube = cubes.get(ticker)
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
            fills = name_fills(
                series, cube, fire[PEER_DEFER][:, j], fire[PEER_CLOSE][:, j], mode
            )
            for rule, f in fills.items():
                grid.price[rule][:, j] = f.price
                grid.reached[rule][:, j] = f.reached
                grid.active[rule][:, j] = f.active
                grid.slot[rule][:, j] = f.slot
                grid.wait[rule][:, j] = f.wait
                grid.tagged[rule][:, j] = f.tagged
        oracle[:, j] = sd.oracle_prices(series, cube, 1)[SELL]
        oracle_five[:, j] = sd.oracle_prices(series, cube, lab.WINDOW)[SELL]
        covered.append(ticker)
    block = {
        "groups": groups,
        "first": first,
        "morning": morning,
        "priced": priced,
        "fire": fire,
        "oracle": oracle,
        "oracle_five": oracle_five,
    }
    coverage = {
        "names_with_cube": len(covered),
        "names_without_cube": sorted(
            t for t in tickers if t not in set(covered) and t != str(panel.benchmark)
        ),
        "first_cube_date": str(min(cubes[t].dates[0] for t in covered))
        if covered
        else None,
        "name_sessions_with_peers": int(groups.has.sum()),
        "name_sessions_with_morning": int(np.isfinite(morning).sum()),
        "never": bool(never),
    }
    return grids[False], grids[True], block, coverage


# Assemble the Market from the panel, its grades, the grids and the peer
# block of `fill_grids`.
def build_market(
    panel: Any,
    grades: np.ndarray,
    fills: sr.Grid,
    next_bar: sr.Grid,
    block: Mapping[str, Any],
) -> Market:
    """Return the Market."""
    if fills.next_bar or not next_bar.next_bar:
        raise ValueError(
            "fills must be the bar-close grid and next_bar the next-bar grid"
        )
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    if np.asarray(grades).shape != shape or np.shape(block["morning"]) != shape:
        raise ValueError("the grades and the peer block must be on the panel's grid")
    return Market(
        dates=dates,
        tickers=tuple(str(t) for t in panel.tickers),
        fills=fills,
        next_bar=next_bar,
        oracle=np.asarray(block["oracle"], dtype=float),
        oracle_five=np.asarray(block["oracle_five"], dtype=float),
        grades=np.asarray(grades),
        closes=np.asarray(panel.adj_close, dtype=float),
        peers=block["groups"],
        morning=np.asarray(block["morning"], dtype=float),
        priced_peers=np.asarray(block["priced"]),
        fire=dict(block["fire"]),
    )


# The null test on two grids: every rule's price, reached, slot and wait
# equal the control's to the bit on every cell, in both fill modes.
# Returns the list of mismatches (empty: reproduced).
def null_mismatches(fills: sr.Grid, next_bar: sr.Grid) -> list[str]:
    """Return the cells' mismatch descriptions, empty when the null holds."""
    bad: list[str] = []
    for grid in (fills, next_bar):
        mode = "next-bar" if grid.next_bar else "bar-close"
        for rule in (PEER_DEFER, PEER_CLOSE):
            for field in ("price", "reached", "slot", "wait"):
                a = getattr(grid, field)[rule]
                b = getattr(grid, field)[CONTROL]
                same = (
                    np.array_equal(a, b, equal_nan=True)
                    if field == "price"
                    else np.array_equal(a, b)
                )
                if not same:
                    bad.append(f"{mode} {rule} {field}")
    return bad


# --- pricing one candidate ---------------------------------------------------


@dataclass(frozen=True)
class Book(sr.Book):
    """The structure-rules sell Book with the rule's scope; `tagged` is fired."""

    in_scope: np.ndarray  # (K,) bool: the sell is in the candidate's scope


# The (rule, scope) of a candidate name, refused when unknown.
def rule_of(candidate: str) -> tuple[str, str]:
    """Return (rule, scope) of "G<k>"."""
    if candidate not in CANDIDATES:
        raise ValueError(
            f"unknown candidate {candidate!r}; registered: {', '.join(CANDIDATES)}"
        )
    return CANDIDATES[candidate]


# Which sells a scope covers, from their details and grades at t: the
# downgrade sells, or every non-event sell whose grade is not B.
def in_scope(scope: str, detail: np.ndarray, grade: np.ndarray) -> np.ndarray:
    """Return the (K,) scope mask."""
    detail = np.asarray(detail)
    grade = np.asarray(grade)
    if scope == DOWNGRADE:
        return np.isin(detail, DOWNGRADE_DETAILS)
    if scope == NOT_B:
        return np.isin(detail, SCOPE_DETAILS) & (grade != so.B)
    raise ValueError(f"unknown scope {scope!r}")


# Price one candidate on one run's sells: in scope its rule's fill, else
# the control's; g, the wait, the trigger and the counts. An order whose
# fill or control has no price fills as the control (g = 0), counted.
def price_book(
    orders: so.Orders, market: Market, candidate: str, next_bar: bool = False
) -> Book:
    """Return the candidate's Book on the sells."""
    rule, scope = rule_of(candidate)
    grid = market.next_bar if next_bar else market.fills
    rows = np.flatnonzero(orders.side == SELL)
    t = orders.session[rows]
    j = orders.column[rows]
    scoped = in_scope(scope, orders.detail[rows], orders.grade[rows])
    control = grid.price[CONTROL][t, j]
    price = np.where(scoped, grid.price[rule][t, j], control)
    unpriced = ~np.isfinite(control) | ~np.isfinite(price)
    gain = np.where(unpriced, 0.0, lab.gain(control, price, SELL))
    fired = scoped & grid.tagged[rule][t, j] & ~unpriced
    own = scoped & ~unpriced
    return Book(
        candidate=candidate,
        side=SELL,
        start=orders.start,
        stop=orders.stop,
        rows=rows,
        session=t,
        weight=orders.weight[rows],
        gain=gain,
        wait=np.where(own, grid.wait[rule][t, j], 0).astype(np.int64),
        acted=fired,
        unpriced=unpriced,
        no_forecast=np.zeros(len(rows), dtype=bool),
        oracle=lab.gain(control, market.oracle[t, j], SELL),
        reached=np.where(own, grid.reached[rule][t, j], grid.reached[CONTROL][t, j])
        & ~unpriced,
        slot=np.where(
            unpriced,
            -1,
            np.where(own, grid.slot[rule][t, j], grid.slot[CONTROL][t, j]),
        ).astype(np.int64),
        oracle_five=lab.gain(control, market.oracle_five[t, j], SELL),
        column=j,
        tagged=fired,
        in_scope=scoped,
    )


# --- statistics ----------------------------------------------------------------


# Structure-rules' statistics of one window (`structure_rules.summarize`),
# plus the scope: the priced sells in scope and the share of them on which
# the rule fired.
def summarize(
    book: Book,
    dates: np.ndarray,
    lo: date | None,
    hi: date | None,
    mu_bp: float,
    subset: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return the statistics of one window."""
    out = sr.summarize(book, dates, lo, hi, mu_bp, subset)
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
    scoped = inside & book.in_scope & ~book.unpriced
    fired = scoped & book.tagged
    out["in_scope"] = int(scoped.sum())
    out["fired"] = int(fired.sum())
    out["fired_share"] = float(fired.sum() / scoped.sum()) if scoped.any() else math.nan
    return out


# The same statistics per grade group and per order detail of a book's
# sells, per window.
def splits(
    book: Book,
    groups: Mapping[str, np.ndarray],
    dates: np.ndarray,
    spans: Mapping[str, tuple[date | None, date | None]],
    mus: Mapping[str, float],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return {group: {label: {window: statistics}}}."""
    values = sd.group_values(SELL)
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


# The deflated Sharpe at the plan's counts (N = 3, cumulative 485), the
# trial variance the across-candidate variance of the three model-window
# Sharpe ratios.
def deflated(excess: Mapping[str, Mapping[str, Any]], candidate: str) -> dict[str, Any]:
    """Return the deflated Sharpe record of `candidate`."""
    return ae.deflated(excess, candidate, TRIALS)


# --- what the peer groups look like (reported) ---------------------------------


# The peer group of each named ticker on `day`: the peers and their
# residual correlations, sigma_g, and (when the market carries it) R_g and
# the triggers; None for a ticker or a day the panel does not have.
def peer_report(
    groups: PeerGroups,
    names: Sequence[str],
    day: date,
    morning: np.ndarray | None = None,
    priced: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return {ticker: {"peers": [[peer, corr]], "sigma_g", ...} or None}."""
    dates = groups.dates
    where = np.flatnonzero(dates == np.datetime64(day, "D"))
    out: dict[str, Any] = {}
    for name in names:
        if not len(where) or name not in groups.tickers:
            out[name] = None
            continue
        t, j = int(where[0]), groups.tickers.index(name)
        if not groups.has[t, j]:
            out[name] = {"peers": [], "sigma_g": None}
            continue
        entry: dict[str, Any] = {
            "peers": [
                [groups.tickers[int(p)], float(c)]
                for p, c in zip(groups.members[t, j], groups.corr[t, j], strict=True)
            ],
            "mean_corr": float(np.mean(groups.corr[t, j])),
            "sigma_g": float(groups.sigma[t, j]),
        }
        if morning is not None:
            r = float(morning[t, j])
            entry["morning"] = r if math.isfinite(r) else None
            entry["priced_peers"] = int(priced[t, j]) if priced is not None else None
        out[name] = entry
    return out


# The peer groups' summary per window: the name-sessions with a group, the
# mean residual correlation of the peers, the turnover (the share of the
# previous session's peers still peers), and where each trigger held among
# the name-sessions with a defined R_g.
def peer_summary(market: Market, spans: Mapping[str, tuple[Any, Any]]) -> dict:
    """Return {window: summary}."""
    g = market.peers
    same = np.zeros(g.has.shape)
    both = g.has.copy()
    both[0] = False
    both[1:] &= g.has[:-1]
    for t in range(1, len(g.dates)):
        rows = np.flatnonzero(both[t])
        if not len(rows):
            continue
        now, before = g.members[t, rows], g.members[t - 1, rows]
        same[t, rows] = (now[:, :, None] == before[:, None, :]).any(axis=2).mean(axis=1)
    defined = np.isfinite(market.morning)
    out: dict[str, Any] = {}
    for window, (lo, hi) in spans.items():
        keep = point_in_time.window(g.dates, lo, hi)[:, None]
        has = g.has & keep
        both_w = both & keep
        d = defined & keep
        out[window] = {
            "name_sessions_with_peers": int(has.sum()),
            "mean_corr": sd._mean(g.corr[has].mean(axis=1)) if has.any() else math.nan,
            "turnover_kept": sd._mean(same[both_w]) if both_w.any() else math.nan,
            "name_sessions_with_morning": int(d.sum()),
            "fire_share": {
                rule: float((market.fire[rule] & d).sum() / d.sum())
                if d.any()
                else math.nan
                for rule in (PEER_DEFER, PEER_CLOSE)
            },
        }
    return out


# One (ticker, decision day) read off the grids whether or not the book
# traded it: the grade, the peer group, sigma_g, R_g, the triggers, and the
# control's and each rule's fill with g (bar-close); None when the panel
# lacks the ticker or the day.
def case(market: Market, ticker: str, day: date) -> dict[str, Any] | None:
    """Return the case record."""
    where = np.flatnonzero(market.dates == np.datetime64(day, "D"))
    if not len(where) or ticker not in market.tickers:
        return None
    t, j = int(where[0]), market.tickers.index(ticker)
    grid = market.fills
    report = peer_report(
        market.peers, [ticker], day, market.morning, market.priced_peers
    )[ticker]
    control = float(grid.price[CONTROL][t, j])
    out: dict[str, Any] = {
        "ticker": ticker,
        "decision": str(day),
        "execution": str(market.dates[t + 1]) if t + 1 < len(market.dates) else None,
        "grade": int(market.grades[t, j]),
        "peers": report,
        "control": {
            "fill": control if math.isfinite(control) else None,
            "slot": int(grid.slot[CONTROL][t, j]),
        },
        "rules": {},
    }
    for rule in (PEER_DEFER, PEER_CLOSE):
        price = float(grid.price[rule][t, j])
        g = float(lab.gain(np.array([control]), np.array([price]), SELL)[0])
        out["rules"][rule] = {
            "fired": bool(market.fire[rule][t, j]),
            "fill": price if math.isfinite(price) else None,
            "slot": int(grid.slot[rule][t, j]),
            "wait": int(grid.wait[rule][t, j]),
            "g_bp": g if math.isfinite(g) else None,
        }
    out["scopes"] = {
        c: bool(
            in_scope(
                scope,
                np.array([so.ROTATION_EXIT if out["grade"] < so.A else so.TRIM]),
                np.array([out["grade"]]),
            )[0]
        )
        for c, (_, scope) in CANDIDATES.items()
    }
    return out


# --- the whole test --------------------------------------------------------------


# The per-sell rows of the median offset's orders, for an independent
# recomputation: date, ticker, weight, detail, grade, the control fill,
# the peer reading (peers, sigma_g, R_g, peers priced, both triggers) and
# per candidate its fill, g (bar-close and next-bar), wait and flags.
def order_rows(
    orders: so.Orders, market: Market, books: Mapping[str, tuple[Book, Book]]
) -> dict[str, Any]:
    """Return the payload's "rows" block."""
    rows = np.flatnonzero(orders.side == SELL)
    t = orders.session[rows]
    j = orders.column[rows]
    g = market.peers
    peers = [
        [g.tickers[int(p)] for p in g.members[a, b]] if g.has[a, b] else []
        for a, b in zip(t, j, strict=True)
    ]
    out: dict[str, Any] = {
        "sessions": [str(d) for d in market.dates[orders.start : orders.stop]],
        "date": [str(d) for d in market.dates[t]],
        "ticker": orders.ticker[rows].tolist(),
        "weight": orders.weight[rows].tolist(),
        "detail": orders.detail[rows].tolist(),
        "grade": orders.grade[rows].tolist(),
        "control": market.fills.price[CONTROL][t, j].tolist(),
        "next_bar_control": market.next_bar.price[CONTROL][t, j].tolist(),
        "peers": peers,
        "sigma_g": g.sigma[t, j].tolist(),
        "morning": market.morning[t, j].tolist(),
        "priced_peers": market.priced_peers[t, j].tolist(),
        "fired": {rule: market.fire[rule][t, j].tolist() for rule in market.fire},
        "candidates": {},
    }
    for candidate, (book, nb) in books.items():
        if not np.array_equal(book.rows, rows):
            raise ValueError("the books must be priced on the same orders")
        rule, _ = rule_of(candidate)
        own = market.fills.price[rule][t, j]
        out["candidates"][candidate] = {
            "fill": np.where(book.in_scope, own, out["control"]).tolist(),
            "next_bar_fill": np.where(
                book.in_scope,
                market.next_bar.price[rule][t, j],
                out["next_bar_control"],
            ).tolist(),
            "g_bp": book.gain.tolist(),
            "next_bar_g_bp": nb.gain.tolist(),
            "wait": book.wait.tolist(),
            "in_scope": book.in_scope.tolist(),
            "acted": book.acted.tolist(),
            "unpriced": book.unpriced.tolist(),
            "slot": book.slot.tolist(),
        }
    return out


# The sells of the median offset decided on or after `since` that any
# candidate re-timed (g != 0 at bar-close fills): date, ticker, detail,
# grade, weight, the control fill and per candidate its fill and g.
def changed_sells(rows: Mapping[str, Any], since: date = CHANGED_FROM) -> list[dict]:
    """Return the list of changed sells."""
    out = []
    for k, day in enumerate(rows["date"]):
        if day < str(since):
            continue
        moved = {
            c: v for c, v in rows["candidates"].items() if v["g_bp"][k] not in (0, 0.0)
        }
        if not moved:
            continue
        out.append(
            {
                "date": day,
                "ticker": rows["ticker"][k],
                "detail": rows["detail"][k],
                "grade": rows["grade"][k],
                "weight": rows["weight"][k],
                "control": rows["control"][k],
                "peers": rows["peers"][k],
                "morning": rows["morning"][k],
                "sigma_g": rows["sigma_g"][k],
                "candidates": {
                    c: {
                        "fill": v["fill"][k],
                        "g_bp": v["g_bp"][k],
                        "wait": v["wait"][k],
                    }
                    for c, v in moved.items()
                },
            }
        )
    return out


# Price every candidate on every offset's sells and assemble the payload:
# per offset the model-window and 2024-2026 means (and the next-bar
# model-window mean); at the median offset every statistic, the next-bar
# run, the splits, the per-sell rows, the 2026 changes, the peer summary,
# the named peer groups and the COHR case; the deflated Sharpe and the
# verdict. A run over fewer than `registered` offsets is a smoke run.
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
    rows = order_rows(at_median, market, books)
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
            "side": SELL,
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
            "K_PEERS": K_PEERS,
            "CORR_SESSIONS": CORR_SESSIONS,
            "PEER_SIGMA_SESSIONS": PEER_SIGMA_SESSIONS,
            "MIN_PRICED_PEERS": MIN_PRICED_PEERS,
            "CLOSE_THRESHOLD": CLOSE_THRESHOLD,
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
        "candidates": {
            c: {"rule": r, "scope": s, "side": SELL} for c, (r, s) in CANDIDATES.items()
        },
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
        "peers": {
            "summary": peer_summary(market, spans),
            "named": {
                "date": str(CASE_DATE),
                "groups": peer_report(
                    market.peers, NAMED, CASE_DATE, market.morning, market.priced_peers
                ),
            },
        },
        "case": case(market, CASE_TICKER, CASE_DATE),
        "changed_2026": changed_sells(rows),
        "rows": rows,
    }
    payload["verdict"] = verdict(payload)
    return payload


# --- the verdict ---------------------------------------------------------------


# The plan's verdict per candidate (`adaptive_entry.judge`: the six
# criteria and the real-but-immaterial reading), one line each, and the
# headline; a smoke run's headline says it is not the registered test.
def verdict(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return {"candidates", "replaces", "immaterial", "lines", "text"}."""
    candidates = {
        c: ae.judge(payload["results"][c], payload["deflated"][c]) for c in CANDIDATES
    }
    for c, info in candidates.items():
        model = payload["results"][c]["default"][MODEL]
        info["fired_share"] = sd._f(model.get("fired_share"))
        info["in_scope"] = int(model.get("in_scope") or 0)
        info["waited_share"] = sd._f(model.get("waited_share"))
    replaces = [c for c, v in candidates.items() if v["label"] == REPLACES]
    immaterial = [c for c, v in candidates.items() if v["label"] == IMMATERIAL]
    head = ""
    offsets = payload.get("offsets") or {}
    if offsets.get("smoke"):
        head = (
            f"SMOKE RUN ({offsets.get('priced')} of {offsets.get('registered')} "
            "offsets): not the registered test. "
        )
    if replaces:
        head += (
            f"{REPLACES}: {', '.join(replaces)} clear every criterion against the "
            "board's sell rule for their scope; a live change needs a separate "
            "registration and the operator's go-ahead"
        )
    else:
        head += (
            f"{RECORD}: no candidate clears every criterion; the board keeps its "
            "sell rule"
        )
    if immaterial:
        head += f". {IMMATERIAL}: {', '.join(immaterial)} (kept for the manual book)"
    return {
        "candidates": candidates,
        "replaces": replaces,
        "immaterial": immaterial,
        "lines": [_line(c, v) for c, v in candidates.items()],
        "text": head,
    }


# One candidate's verdict line: each criterion's number, the firing, the
# label.
def _line(candidate: str, info: Mapping[str, Any]) -> str:
    """Return the candidate's verdict line."""
    signed, share = sd._signed, sd._share
    holds = "holds" if info["criteria"]["2_next_bar"] else "fails"
    rule, scope = CANDIDATES[candidate]
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
        f"per re-timed sell {signed(info['retimed_bp'], 1)} bp "
        f"(t {signed(info['retimed_t'])}) "
        f"over {info['retimed']} of {info['orders']} sells",
        f"fired on {share(info['fired_share'])} of {info['in_scope']} in scope",
        f"waited {share(info['waited_share'])}",
        f"oracle capture {share(info['capture'])}",
    ]
    return f"{candidate} ({rule}, {scope}): {'; '.join(parts)} - {info['label']}"
