"""Fill timing inside the session: the `/4` policy's orders, seven fill conventions.

The pre-registration is `docs/research/execution-timing-plan-2026-09-27.md`;
this module is that plan's engine and computes nothing the plan did not fix
in advance. The question is only *when within the next session* the orders
`graded-equal-weight/4` generates should fill, and whether a price condition
should gate them. Nothing here changes what is held or when it is decided.

What is priced
--------------
The orders are exactly the plain simulator's: `simulate.run(restricted,
since=..., allocator=policy_v4.allocator(mask), cost_bps=10, use_exits=False,
rebalance=paper.REBALANCE_EVERY)`. That run decides on session t's close
(the allocator's targets sized by `planner.plan` at the adjusted close, on
`_Book.plan`) and fills the whole order at t + 1's adjusted open; between
decisions nothing trades. `target_path` re-derives that schedule and those
targets from `policy_v4.allocator(mask)` rather than reading the journal
observer, because the plain arm has no between-decision trades (with
`use_exits=False` and no exit evidence `_Book.between` returns the held
weights, which `planner.plan` leaves alone) and no overlay; the re-derivation
is therefore exactly the observer's `desired_weights` on the decision
sessions and nothing on the others. `test_fill_timing.py` pins this by
asserting that `next_open` priced here reproduces the simulator's returns to
1e-10 on a synthetic report and store.

`price_book` then holds those share orders in the simulator's own ledger
(`simulate._Book`: the same cash budget, the same one-way cost on turnover,
the same "missing price keeps the holding") and fills every order at the
convention's price on the fill session. Fill prices come from the SIP
session cube (26 regular bars plus the closing auction, raw basis) and are
moved onto the panel's adjusted basis by the ratio of the panel's adjusted
close to the cube's own official close on the fill session (the daily
store's `close` is already split-adjusted, so `adj_close / close` would
undo dividends only), so a split never sits
between a fill and a mark. Marks are the panel's adjusted daily close - the
official close, what the cube's `auction_open` holds where present - on the
fill session and on every session after it, for every convention alike.
A name with no complete cube session on its fill day fills at the panel's
adjusted open (the simulator's price) and is counted as a fallback.

The seven conventions (`CONVENTIONS`), each one registered trial:

  next_open        bar 0's open of the fill session - the control
  first_hour_vwap  volume-weighted mean of the bar closes over slots 0-3
  session_vwap     the same over all 26 slots
  next_close       the closing auction's print, else the last bar's close
  dip_or_close     a buy fills at the first bar close at or below
                   open * (1 - DIP), else at the official close; a sell at
                   the first bar close at or above open * (1 + DIP), else
                   the official close. "The close" is the same print
                   `next_close` fills at, so the dip is isolated from the
                   last quarter hour's noise.
  late_day         VWAP over LATE_SLOTS (15:00-15:45)
  breakout_gate    the executor's band gate, isolated: a buy fills at the
                   next open when the name's daily is not rejecting its
                   upper band on the decision date (`exit.evidence(panel)
                   .signalled()`, the very function `market_daily._band_blocked`
                   and `simulate.run(block_overbought=True)` read); a
                   rejecting name is deferred one session and re-tested, up
                   to MAX_DEFERRALS times, after which it fills at the open
                   regardless. Sells never wait. Deferrals are counted.

The VWAPs are a proxy from bar closes weighted by bar volume (the store has
no per-bar VWAP), as the plan states.

Statistics (`study`)
--------------------
Per convention and per start offset (the first `offsets` sessions, the
scorecard's phases of the 20-session clock), a daily return series aligned
to the panel. Per window (`market_pit_scorecard.WINDOWS`): the median CAGR
across offsets, the count of offsets whose CAGR beats `next_open`, and at
the median offset the paired daily difference against `next_open` in basis
points with a Newey-West t at lag HAC_LAG, plus the deferral and fallback
counts. The best convention's excess is deflated against TRIALS = 7 trials
(`candidate_stats.deflated_sharpe`). `verdict` applies the plan's kill
criteria unchanged: ADOPTED only when a convention beats `next_open` by at
least ADOPT_BP a session with t >= ADOPT_T on the choosing window and is not
worse on the reported window; anything else is RECORDED, NOT ACTED ON. The
`breakout_gate` line against `next_open` is stated separately because the
plan already names what follows from it.

The entry-level trial
---------------------
`docs/research/ml-entry-level-plan-2026-09-28.md` registers four more
conventions (`LEVEL_CONVENTIONS`, described by `LEVELS`) that ask whether
the CNN's next-session volatility forecast sets a better buy/sell level
than the board's fixed 1% (`dip_or_close`). Each reads sigma = exp(F / 2),
F the forecast in the file's row (name, t) - made at t's close, for
session t + 1's log realized variance, put at the panel's row of t by
`vol_forecast.align` - and the order decided at t's close fills in session
t + 1, so the fill on session s reads panel row s - 1 (`fill_sigma`):

  vol_dip_0.5    a buy fills at the first bar close at or below
                 open * exp(-0.5 sigma), else the official close; a sell
                 at the first bar close at or above open * exp(+0.5 sigma)
  vol_dip_1.0    the same at k = 1.0
  vol_limit_0.5  a resting limit at open * exp(-0.5 sigma), filled at the
                 limit price when some bar's low is strictly below it,
                 else the official close; a sell mirrors on the highs
  trail_dip      vol_dip_0.5 with sigma from the file's trailing baseline
                 (the log mean realized variance of the 20 sessions
                 through t), on exactly the cells the forecast covers: the
                 twin that separates "the model" from "vol-scaling"

Where sigma is missing (before the first fit, or a cell the dataset has
no row for) the order fills as `dip_or_close` and is counted. With a
level convention priced, every row gains the paired difference against
`dip_or_close` and against `trail_dip`, the offsets above `dip_or_close`,
and from the median offset's orders in the window the dip fill rate (the
share filled at the level before the close), the gain over that session's
official close per dip fill and per order, and the sigma fallbacks.
`level_verdict` applies the plan's criteria: REPLACES the board's rule only
at >= REPLACE_BP a session over `dip_or_close` with t >= REPLACE_T on the
choosing window, not worse on the reported window, and above `trail_dip`
on the choosing window; passing the floors without the last is RECORD
(vol-scaling, not the model), as is `trail_dip` passing them; anything else
RECORD. LEVEL_TRIALS = 4. `study(conventions=...)` prices a subset (the CLI's
`--only`); the fill-timing verdict is judged only when all seven of its
conventions were priced.

The support/resistance trial
----------------------------
`docs/research/sr-levels-plan-2026-09-29.md` registers two more
(`SR_CONVENTIONS`) that ask whether waiting for a real level beats the
board's fixed 1%. The levels are `sr_levels.KINDS`: 22 of them, daily
structure from the prior close, volume nodes of the prior 20 cube
sessions, the opening range from 10:00 and the running VWAP through the
prior bar, each with its zone of half-width max(0.25 ATR14, 0.3% of the
prior close). They are priced only when named (`--only`), never by default:

  level_dip             a buy fills at the first bar close from slot 2 (the
                        10:15 close) that lies inside the zone of a level
                        below the prior bar's close while below the session
                        open, else the official close; a sell at the first
                        close inside the zone of a level above the prior
                        bar's close while above the open, else the close
  level_dip_confluence  the same, counting only zones whose confluence
                        (distinct level prices inside) is at least 2

The zones are computed once per run (`sr_zones`) on the panel's adjusted
basis with the same split-safe scale the fills use (`session_scale`). Rows
gain the paired difference against `dip_or_close`, and from the median
offset's orders the fill rate at a level and the gain per level fill over
that session's official close. `sr_verdict` applies the plan's criteria:
REPLACES the board's rule only at >= REPLACE_BP a session over
`dip_or_close` with t >= REPLACE_T on the choosing window and not worse on
the reported window; anything else RECORD. SR_TRIALS = 2.

The stage-3 T-I trial
---------------------
`docs/research/stage3-plan-2026-09-29.md` ("The two questions", T-I) asks
whether a model of "now or the close" beats the board's rule. A T-I
forecast (`stage3_io.Stage3Forecast`, kind "ti") holds, per (name, fill
session s, slot k = 0..23), y-hat of y = 1e4 * ln(official close / bar k's
close) in bp: above zero, buying at bar k's close beats waiting for the
close; below zero, selling now does. `stage3_io.ti_lookup` gives each
(name, fill session) its (24,) vector. Four conventions (`TI_RULES`), each
one of the plan's eight outer candidates, priced only when named:

  <family>_filter  the board's trigger with a model veto: a buy at the first
                   bar close at or below open * (1 - DIP) (slot k*, exactly
                   dip_or_close's) fills there when y-hat(k*) > 0 and at the
                   official close otherwise; a trigger at slot 24 or 25
                   (after 15:30) has no forecast and fills as dip_or_close
                   (counted, a "late trigger"); no trigger fills at the
                   close. A sell mirrors on the 1% pop and y-hat(k*) < 0.
  <family>_free    the model picks the moment: a buy fills at the close of
                   the first slot 0..23 with y-hat > 0, else the official
                   close; a sell at the first with y-hat < 0.

`<family>` is `lgbm` (M1) or `seq` (M3). An order whose (name, fill
session) has no vector, or an all-NaN one, fills exactly as dip_or_close
and is counted ("no forecast", carried in the detail's `no_sigma`). A NaN
slot inside a vector that has forecasts is no veto for the filter (the
board's fill stands) and is skipped by the free rule; the forecast files
carry all 24 slots of a name-session or none, so this is recorded
(`partial_vectors`) rather than expected.

`next_bar=True` (the CLI's `--next-bar`, the plan's robustness run) moves
every fill made at a bar close - dip_or_close, the dip-rule level
conventions (vol_dip_0.5, vol_dip_1.0, trail_dip), the SR pair and the four
T-I conventions, candidate and control alike - to the next bar's open: a
fill at close[k] becomes open[k + 1], and a fill at slot 25 goes to the
official close. The open, the VWAPs, the official close and the resting
limit are not bar-close fills and do not move. Off, every price is
byte-identical to the engine before this trial.

With a T-I convention priced the payload gains a "stage3_ti" block
(`_ti_block`): per convention and window - the model window (from the
family's first forecast session through 2023-12-29), 2016-2023 and
2024-2026 - the paired daily difference against dip_or_close at the median
offset (bp, Newey-West t at `stage3_io.HAC_LAG`), the median CAGRs and the
offsets above dip_or_close, the excess series' moments (for the deflated
Sharpe), and from the median offset's orders in the window, per side (all,
buy, sell): the share filled before the close, the gain per such fill and
per order over the session's official close, the no-forecast and
late-trigger counts, and candidate minus control in bp per order over the
orders the two fill differently, with a t clustered by fill session. The
REPLACES / RECORD verdict needs several runs (10, 16 and 25 bp, a
`--next-bar` run, five single-seed runs) and lives in `stage3_verdict`;
the block carries only this run's reading.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np

from backend.agents.trading.desk import exit as exit_analyst
from backend.agents.trading.desk import paper, policy_v4, simulate
from backend.market import (
    candidate_stats,
    session_anatomy,
    sr_levels,
    stage3_io,
    stage3_verdict,
)
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.market.vol_forecast import Aligned, sigma

if TYPE_CHECKING:
    from backend.agents.trading.desk.desk import DeskReport
    from backend.market.panel import Panel

CONVENTIONS = (
    "next_open",
    "first_hour_vwap",
    "session_vwap",
    "next_close",
    "dip_or_close",
    "late_day",
    "breakout_gate",
)
CONTROL = "next_open"
# The dip a `dip_or_close` order waits for, as a fraction of the open.
DIP = 0.01
# 15:00-15:45: the four bars where the index-level intraday momentum lives.
LATE_SLOTS = (22, 23, 24, 25)
# The first hour: slots 0-3, the anatomy study's definition.
FIRST_HOUR_SLOTS = session_anatomy.FIRST_HOUR_SLOTS
# The one cost the trial is scored at, one way on every fill.
COST_BPS = (10.0,)
# The plan's kill floors: bp a session over the control and its HAC t.
ADOPT_BP = 5.0
ADOPT_T = 2.5
# A gated buy waits at most this many sessions, then fills at the open.
MAX_DEFERRALS = 5
# Newey-West lag on the paired daily differences, the scorecard's.
HAC_LAG = 20
# Seven conventions were scored, so the best is deflated against seven.
TRIALS = len(CONVENTIONS)
WINDOWS: dict[str, tuple[date | None, date | None]] = {
    "2016-2023": (date(2016, 1, 1), date(2024, 1, 1)),
    "2024-2026": (date(2024, 1, 1), None),
    "all": (None, None),
}
CHOOSING = "2016-2023"
REPORTED = "2024-2026"
ADOPTED = "ADOPTED"
RECORDED = "RECORDED, NOT ACTED ON"
BP = 1e4

# The entry-level trial (docs/research/ml-entry-level-plan-2026-09-28.md),
# fixed before any run: four conventions whose level is k * sigma from the
# open, sigma a next-session volatility, judged against the board's rule.
LEVEL_CONVENTIONS = ("vol_dip_0.5", "vol_dip_1.0", "vol_limit_0.5", "trail_dip")
# The board's rule: what a level convention has to beat to replace it.
LEVEL_CONTROL = "dip_or_close"
# The same rule as vol_dip_0.5 fed trailing volatility: "the model" or
# merely "vol-scaling".
LEVEL_TWIN = "trail_dip"
# The fill-timing and entry-level trials' conventions, in registered order:
# what a run prices by default (the level four only with forecasts).
ALL_CONVENTIONS = CONVENTIONS + LEVEL_CONVENTIONS
# Where a level convention's sigma comes from, and how it fills.
FORECAST = "forecast"
TRAILING = "trailing"
DIP_RULE = "dip"
LIMIT_RULE = "limit"
# The plan's floors for replacing the board's rule: bp a session over
# dip_or_close and its HAC t, on the choosing window.
REPLACE_BP = 2.0
REPLACE_T = 2.0
# Four level conventions were registered, so the best is deflated against four.
LEVEL_TRIALS = len(LEVEL_CONVENTIONS)
REPLACES = "REPLACES"
RECORD = "RECORD"
VOL_SCALING = "RECORD (vol-scaling, not the model)"

assert FIRST_HOUR_SLOTS == 4
assert all(0 <= s < FULL_SESSION_SLOTS for s in LATE_SLOTS)


@dataclass(frozen=True)
class Level:
    """One registered entry-level convention: how it fills, k, and sigma's source."""

    rule: str  # DIP_RULE: first bar close past the level; LIMIT_RULE: resting limit
    k: float  # the level sits k * sigma (in log terms) from the session's open
    source: str  # FORECAST: the CNN's forecast; TRAILING: the file's trailing baseline


LEVELS: dict[str, Level] = {
    "vol_dip_0.5": Level(DIP_RULE, 0.5, FORECAST),
    "vol_dip_1.0": Level(DIP_RULE, 1.0, FORECAST),
    "vol_limit_0.5": Level(LIMIT_RULE, 0.5, FORECAST),
    "trail_dip": Level(DIP_RULE, 0.5, TRAILING),
}

# The support/resistance trial (docs/research/sr-levels-plan-2026-09-29.md),
# fixed before any run: a buy waits for a bar close inside a support zone
# while below the open, a sell for one inside a resistance zone above it.
SR_CONVENTIONS = ("level_dip", "level_dip_confluence")
# The fewest distinct level prices a zone must hold for each to fill there.
SR_MIN_CONFLUENCE: dict[str, int] = {"level_dip": 1, "level_dip_confluence": 2}
# Two SR conventions were registered, so the best is deflated against two.
SR_TRIALS = len(SR_CONVENTIONS)
SR_PLAN = "docs/research/sr-levels-plan-2026-09-29.md"
# The fill-timing, entry-level and SR trials' conventions, in registered
# order: the fill-timing and entry-level trials' (ALL_CONVENTIONS, the
# default sets) and the SR trial's, which are priced only when named.
KNOWN_CONVENTIONS = ALL_CONVENTIONS + SR_CONVENTIONS


# The stage-3 T-I trial (docs/research/stage3-plan-2026-09-29.md), fixed
# before any run: a family's forecast of 1e4 * ln(official close / bar k's
# close) either vetoes the board's 1% trigger ("filter") or picks the slot
# itself ("free"). Priced only when named, each with its family's forecast.
TI_FILTER = "filter"
TI_FREE = "free"


@dataclass(frozen=True)
class TiRule:
    """One stage-3 T-I convention: the family whose forecast it reads, its rule."""

    family: str  # stage3_io.LGBM (M1) or stage3_io.SEQ (M3)
    rule: str  # TI_FILTER: veto the board's trigger; TI_FREE: the model picks the slot


TI_RULES: dict[str, TiRule] = {
    "lgbm_filter": TiRule(stage3_io.LGBM, TI_FILTER),
    "lgbm_free": TiRule(stage3_io.LGBM, TI_FREE),
    "seq_filter": TiRule(stage3_io.SEQ, TI_FILTER),
    "seq_free": TiRule(stage3_io.SEQ, TI_FREE),
}
TI_CONVENTIONS = tuple(TI_RULES)
# The T-I families, as stage3_io registers them.
TI_FAMILIES = stage3_io.FAMILIES[stage3_io.TI]
# The plan that registered them.
STAGE3_PLAN = stage3_io.PLAN
# What a T-I convention has to beat: the board's rule.
TI_CONTROL = LEVEL_CONTROL
# The T-I block's windows: the model window runs from the family's first
# forecast session up to (not including) TI_MODEL_END, i.e. through the
# last session of 2023; the other two are the choosing and reported windows.
TI_MODEL = "model"
TI_MODEL_END = date(2024, 1, 1)
TI_WINDOWS = (TI_MODEL, "2016-2023", "2024-2026")
# Every convention `price_book` knows, in registered order.
PRICEABLE = KNOWN_CONVENTIONS + TI_CONVENTIONS
# The conventions that wait for a price, and so have a dip fill rate.
WAITING = (LEVEL_CONTROL, *LEVEL_CONVENTIONS, *SR_CONVENTIONS, *TI_CONVENTIONS)

assert tuple(LEVELS) == LEVEL_CONVENTIONS
assert LEVELS[LEVEL_TWIN] == Level(DIP_RULE, 0.5, TRAILING)
assert not set(CONVENTIONS) & set(LEVEL_CONVENTIONS)
assert not set(ALL_CONVENTIONS) & set(SR_CONVENTIONS)
assert tuple(SR_MIN_CONFLUENCE) == SR_CONVENTIONS
assert not set(KNOWN_CONVENTIONS) & set(TI_CONVENTIONS)
assert {r.family for r in TI_RULES.values()} == set(TI_FAMILIES)
assert TI_CONVENTIONS == stage3_verdict.TI_CANDIDATES
assert all(f"{r.family}_{r.rule}" == c for c, r in TI_RULES.items())
assert stage3_io.TI_SLOTS < FULL_SESSION_SLOTS
assert TI_WINDOWS[1:] == ("2016-2023", "2024-2026")


@dataclass(frozen=True)
class TargetPath:
    """The policy's desired weights on the simulator's decision sessions."""

    start: int  # the first session of the run (the `since` row)
    decisions: tuple[int, ...]  # sessions the policy decides on
    weights: np.ndarray  # (T, N): the targets on decision rows, NaN elsewhere


@dataclass(frozen=True)
class WaitDetail:
    """Per (session, name), for a convention that waits for a price: how it filled."""

    buy_hit: np.ndarray  # (T, N) bool: a buy filled at its level before the close
    sell_hit: np.ndarray  # (T, N) bool: a sell filled at its level before the close
    buy_gain_bp: np.ndarray  # (T, N) (close - fill) / close in bp, NaN off the cube
    sell_gain_bp: np.ndarray  # (T, N) (fill - close) / close in bp
    # (T, N) bool: sigma (or a T-I forecast) missing, filled as dip_or_close
    no_sigma: np.ndarray
    # The T-I filter conventions only (None elsewhere): the order's 1%
    # trigger came at slot 24 or 25, after the last forecast slot.
    buy_late: np.ndarray | None = None
    sell_late: np.ndarray | None = None


@dataclass(frozen=True)
class FillPrices:
    """One convention's raw-basis fill prices aligned to the panel, per side."""

    convention: str
    buy: np.ndarray  # (T, N) raw price, NaN where the cube has no session
    sell: np.ndarray  # (T, N)
    available: np.ndarray  # (T, N) True where the cube has the session
    detail: WaitDetail | None = None  # for the WAITING conventions only


@dataclass(frozen=True)
class OrderLog:
    """A waiting convention's cube-priced orders from one offset, one per order."""

    session: np.ndarray  # (M,) the fill session's panel row
    buy: np.ndarray  # (M,) bool, True for a buy
    hit: np.ndarray  # (M,) bool: filled at its level before the close
    gain_bp: np.ndarray  # (M,) gain over that session's official close, bp
    no_sigma: np.ndarray  # (M,) bool: sigma missing, filled as dip_or_close
    column: np.ndarray | None = None  # (M,) the name's panel column
    late: np.ndarray | None = None  # (M,) bool: a T-I filter's trigger after slot 23


@dataclass(frozen=True)
class Priced:
    """One convention's daily returns from one start offset."""

    convention: str
    start: int
    returns: np.ndarray  # (T,) aligned to the panel; NaN before start + 1
    fills: int  # orders filled
    deferrals: int  # sessions gated buys waited, summed over orders
    fallbacks: int  # fills priced at the panel's open for want of a cube session
    waits: OrderLog | None = None  # the WAITING conventions' orders, else None


# The simulator's decision schedule on the plain arm and the policy's
# targets on it: `start` is the `since` row, decisions come every
# `rebalance` sessions from it while a next session exists, exactly as
# `simulate.run`'s `next_rebalance` clock walks. Between decisions the plain
# arm trades nothing, so the observer's desired weights on the other
# sessions are the held weights and are left NaN here.
def target_path(
    report, mask: np.ndarray, since: date | None, rebalance: int = paper.REBALANCE_EVERY
) -> TargetPath:
    """Return the (T, N) target weights on the decision sessions from `since`."""
    panel = report.panel
    rows, names = panel.adj_close.shape
    start = int(np.searchsorted(panel.dates, np.datetime64(since))) if since else 0
    allocate = policy_v4.allocator(mask)
    weights = np.full((rows, names), np.nan)
    decisions: list[int] = []
    next_rebalance = start
    for t in range(start, rows - 1):
        if t >= next_rebalance:
            next_rebalance = t + rebalance
            weights[t] = allocate(report, panel, None, t)
            decisions.append(t)
    return TargetPath(start, tuple(decisions), weights)


# Whether each name is rejecting its upper band on each session: the exit
# analyst's signal, the one function the live executor (`market_daily.
# _band_blocked`) and the simulator's `block_overbought` gate both read.
def band_rejecting(panel) -> np.ndarray:
    """Return the (T, N) band-rejection flags the executor's gate reads."""
    return exit_analyst.evidence(panel).signalled()


# The official close of every cube session: the closing auction's first
# print where the partition has one, else the last regular bar's close.
def _official_close(cube: SessionCube) -> np.ndarray:
    """Return (N,) the auction print with the last bar's close as fallback."""
    last = cube.close[:, FULL_SESSION_SLOTS - 1]
    auction = np.asarray(cube.auction_open, dtype=float)
    return np.where(np.isfinite(auction), auction, last)


# The price of a fill made at bar `first` of each session: that bar's close,
# or with `next_bar` the next bar's open - what a person acting after the
# bar has closed can get - and the official close for a fill at the last
# bar. Off, exactly the close the engine has always read.
def _bar_price(
    cube: SessionCube, first: np.ndarray, next_bar: bool = False
) -> np.ndarray:
    """Return (N,) close[first], or open[first + 1] (past the last bar: the close)."""
    rows = np.arange(len(cube))
    if not next_bar:
        return cube.close[rows, first]
    later = np.asarray(first) + 1
    return np.where(
        later < FULL_SESSION_SLOTS,
        cube.open[rows, np.minimum(later, FULL_SESSION_SLOTS - 1)],
        _official_close(cube),
    )


# Whether a fill made at bar `first` happened before the official close:
# every such fill does, except that with `next_bar` a fill at the last bar
# moves to the official close itself.
def _filled_at_bar(
    reached: np.ndarray, first: np.ndarray, next_bar: bool = False
) -> np.ndarray:
    """Return (N,) True where the order filled at a bar rather than the close."""
    if not next_bar:
        return reached
    return reached & (np.asarray(first) + 1 < FULL_SESSION_SLOTS)


# The first bar close at or past a per-session level: a buy's close at or
# below it, a sell's at or above it. Returns whether any close got there
# and the first slot that did (0 where none did).
def _first_past(
    cube: SessionCube, side: str, level: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((N,) reached, (N,) first slot) for a close-triggered level."""
    if side == "buy":
        hit = cube.close <= level[:, None]
    else:
        hit = cube.close >= level[:, None]
    return hit.any(axis=1), np.argmax(hit, axis=1)


# The first bar close at or past a per-session level, else the official
# close: a buy waits for a close at or below `level`, a sell for one at or
# above it. Returns the price and whether the level was reached (the dip
# fill) for every session. Every order fills. With `next_bar` the fill
# moves to the next bar's open (`_bar_price`).
def _first_close_past(
    cube: SessionCube, side: str, level: np.ndarray, next_bar: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((N,) fill price, (N,) reached) for a close-triggered level."""
    any_hit, first = _first_past(cube, side, level)
    picked = _bar_price(cube, first, next_bar)
    return (
        np.where(any_hit, picked, _official_close(cube)),
        _filled_at_bar(any_hit, first, next_bar),
    )


# The board's 1% level per session: open * (1 - DIP) for a buy, open *
# (1 + DIP) for a sell. One expression, shared by dip_or_close and the T-I
# filter's trigger.
def _dip_level(cube: SessionCube, side: str) -> np.ndarray:
    """Return (N,) the dip (buy) or pop (sell) level of every session."""
    open0 = cube.open[:, 0]
    return open0 * (1.0 - DIP) if side == "buy" else open0 * (1.0 + DIP)


# The dip-or-close fill and whether the dip was reached: buys wait for a
# close at or below open * (1 - DIP), sells for one at or above
# open * (1 + DIP), else the official close.
def _dip_or_close_fill(
    cube: SessionCube, side: str, next_bar: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((N,) fill price, (N,) reached) for dip_or_close."""
    return _first_close_past(cube, side, _dip_level(cube, side), next_bar)


# The first bar close at or past the dip threshold per session, else the
# official close. Buys wait for a fall below open * (1 - DIP); sells for a
# rise above open * (1 + DIP). Every order fills.
def _dip_or_close(cube: SessionCube, side: str, next_bar: bool = False) -> np.ndarray:
    """Return (N,) the dip-or-close fill price for `side`."""
    return _dip_or_close_fill(cube, side, next_bar)[0]


# A resting limit at a per-session level, placed at the open: a buy fills
# at the limit price when some bar's low is strictly below it (strict, so a
# bare touch is not a fill), a sell when some bar's high is strictly above
# it; otherwise the order fills at the official close.
def _resting_limit(
    cube: SessionCube, side: str, level: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((N,) fill price, (N,) crossed) for a resting limit at `level`."""
    if side == "buy":
        hit = (cube.low < level[:, None]).any(axis=1)
    else:
        hit = (cube.high > level[:, None]).any(axis=1)
    return np.where(hit, level, _official_close(cube)), hit


# The price a level convention waits for: open * exp(-k * sigma) for a buy,
# open * exp(+k * sigma) for a sell. One expression, so a test's bar can
# sit exactly on it.
def entry_level(
    open0: np.ndarray | float, sig: np.ndarray | float, k: float, side: str
) -> np.ndarray:
    """Return the level k * sigma (log terms) below (buy) or above (sell) the open."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, not {side!r}")
    sign = -1.0 if side == "buy" else 1.0
    return np.asarray(open0, dtype=float) * np.exp(
        sign * k * np.asarray(sig, dtype=float)
    )


# The fill of an SR convention for every session of a cube, and whether it
# filled at a level before the close. A buy takes the first bar close from
# `sr_levels.FIRST_SLOT` on whose support confluence (`zones.support`: the
# largest confluence of a zone holding that close, among levels below the
# prior bar's close) reaches the convention's minimum while the close is
# below the session's open; a sell mirrors it on `zones.resistance` above
# the open. Otherwise the order fills at the official close. With
# `next_bar` the fill moves to the next bar's open (`_bar_price`).
def sr_fills(
    cube: SessionCube,
    convention: str,
    side: str,
    zones: sr_levels.CloseZones | None,
    next_bar: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ((N,) fill price, (N,) filled at a level) for an SR convention."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, not {side!r}")
    if convention not in SR_CONVENTIONS:
        raise ValueError(f"{convention!r} is not an SR convention")
    if zones is None:
        raise ValueError(f"{convention} needs the close zones of every session")
    grid = np.asarray(zones.support if side == "buy" else zones.resistance)
    if grid.shape != cube.close.shape:
        raise ValueError(
            f"close zones have shape {grid.shape}; "
            f"the cube's bars are {cube.close.shape}"
        )
    open0 = cube.open[:, :1]
    beyond = cube.close < open0 if side == "buy" else cube.close > open0
    late_enough = np.arange(FULL_SESSION_SLOTS) >= sr_levels.FIRST_SLOT
    hit = (grid >= SR_MIN_CONFLUENCE[convention]) & beyond & late_enough[None, :]
    any_hit = hit.any(axis=1)
    first = np.argmax(hit, axis=1)
    picked = _bar_price(cube, first, next_bar)
    return (
        np.where(any_hit, picked, _official_close(cube)),
        _filled_at_bar(any_hit, first, next_bar),
    )


@dataclass(frozen=True)
class TiFills:
    """A T-I convention's fill for every session of a cube, one side."""

    price: np.ndarray  # (N,) raw fill price
    hit: np.ndarray  # (N,) filled at a bar, before the official close
    no_forecast: np.ndarray  # (N,) no forecast for the (name, session): dip_or_close
    late: np.ndarray  # (N,) the filter's trigger at slot 24 or 25: dip_or_close's fill


# The fill of a T-I convention for every session of a cube, one side, from
# `yhat`, the (sessions, 24) forecast vectors of the cube's sessions (NaN
# where a slot has none). The filter takes dip_or_close's trigger k* (the
# first close at or past the 1% level, `_first_past` on `_dip_level`): at
# k* <= 23 with a finite forecast it fills at close[k*] when the forecast
# agrees (above zero for a buy, below zero for a sell) and at the official
# close when it does not; at k* 24 or 25 it fills at close[k*] as
# dip_or_close does (a late trigger); no trigger fills at the close. The
# free rule fills at the close of the first slot 0..23 whose forecast
# agrees, else at the official close. A session with no finite forecast
# fills exactly as dip_or_close; a NaN forecast at k* is no veto. With
# `next_bar` every bar fill moves to the next bar's open (`_bar_price`).
def ti_fills(
    cube: SessionCube,
    convention: str,
    side: str,
    yhat: np.ndarray | None,
    next_bar: bool = False,
) -> TiFills:
    """Return the TiFills of a T-I convention on every session of `cube`."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, not {side!r}")
    if convention not in TI_RULES:
        raise ValueError(f"{convention!r} is not a stage-3 T-I convention")
    if yhat is None:
        raise ValueError(f"{convention} needs the T-I forecast vector of every session")
    yhat = np.asarray(yhat, dtype=float)
    if yhat.shape != (len(cube), stage3_io.TI_SLOTS):
        raise ValueError(
            f"forecast vectors have shape {yhat.shape}; expected "
            f"({len(cube)}, {stage3_io.TI_SLOTS})"
        )
    base_price, base_hit = _dip_or_close_fill(cube, side, next_bar)
    no_forecast = ~np.isfinite(yhat).any(axis=1)
    rows = np.arange(len(cube))
    with np.errstate(invalid="ignore"):
        if TI_RULES[convention].rule == TI_FILTER:
            reached, first = _first_past(cube, side, _dip_level(cube, side))
            modelled = reached & (first < stage3_io.TI_SLOTS)
            at = yhat[rows, np.minimum(first, stage3_io.TI_SLOTS - 1)]
            agrees = at > 0.0 if side == "buy" else at < 0.0
            veto = modelled & np.isfinite(at) & ~agrees
            filled = reached & ~veto
            late = reached & (first >= stage3_io.TI_SLOTS)
        else:
            agrees = yhat > 0.0 if side == "buy" else yhat < 0.0
            filled = agrees.any(axis=1)
            first = np.argmax(agrees, axis=1)
            late = np.zeros(len(cube), dtype=bool)
    price = np.where(filled, _bar_price(cube, first, next_bar), _official_close(cube))
    hit = _filled_at_bar(filled, first, next_bar)
    return TiFills(
        price=np.where(no_forecast, base_price, price),
        hit=np.where(no_forecast, base_hit, hit),
        no_forecast=no_forecast,
        late=late & ~no_forecast,
    )


# The fill of a convention that waits for a price (dip_or_close, a level
# convention, an SR convention or a T-I convention) for every session of a
# cube, with whether the order filled at its level before the close and
# whether it had no sigma (for a T-I convention: no forecast). `sig` is
# (N,) per cube session for a level convention; a session whose sigma is
# missing, not finite or not positive fills exactly as dip_or_close.
# `zones` is the cube's CloseZones for an SR convention, which never lacks
# a sigma. `yhat` is the (N, 24) T-I forecast vectors for a T-I convention
# (`ti_fills`). `next_bar` moves every bar-close fill to the next bar's
# open; the resting limit is not a bar-close fill and does not move.
def waiting_fills(
    cube: SessionCube,
    convention: str,
    side: str,
    sig: np.ndarray | None = None,
    zones: sr_levels.CloseZones | None = None,
    yhat: np.ndarray | None = None,
    next_bar: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ((N,) price, (N,) reached, (N,) no sigma) for a WAITING convention."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, not {side!r}")
    if convention in SR_CONVENTIONS:
        price, hit = sr_fills(cube, convention, side, zones, next_bar)
        return price, hit, np.zeros(len(cube), dtype=bool)
    if convention in TI_RULES:
        fills = ti_fills(cube, convention, side, yhat, next_bar)
        return fills.price, fills.hit, fills.no_forecast
    base_price, base_hit = _dip_or_close_fill(cube, side, next_bar)
    if convention == LEVEL_CONTROL:
        return base_price, base_hit, np.zeros(len(cube), dtype=bool)
    if convention not in LEVELS:
        raise ValueError(f"{convention!r} does not wait for a price")
    if sig is None:
        raise ValueError(f"{convention} needs a sigma for every session")
    sig = np.asarray(sig, dtype=float)
    if sig.shape != (len(cube),):
        raise ValueError(
            f"sigma has shape {sig.shape}; the cube has {len(cube)} sessions"
        )
    spec = LEVELS[convention]
    no_sigma = ~(np.isfinite(sig) & (sig > 0))
    level = entry_level(cube.open[:, 0], np.where(no_sigma, 0.0, sig), spec.k, side)
    if spec.rule == DIP_RULE:
        price, hit = _first_close_past(cube, side, level, next_bar)
    else:
        price, hit = _resting_limit(cube, side, level)
    return (
        np.where(no_sigma, base_price, price),
        np.where(no_sigma, base_hit, hit),
        no_sigma,
    )


# One convention's fill price for every session of a cube, on the raw
# basis, for one side. The single place each convention's arithmetic lives
# (a level convention's in `waiting_fills`, with `sig` per cube session; an
# SR convention's in `sr_fills`, with the cube's `zones`; a T-I
# convention's in `ti_fills`, with the (N, 24) forecast vectors `yhat`).
# `next_bar` moves the bar-close fills (dip_or_close and the waiting
# conventions) to the next bar's open; the other conventions ignore it.
def session_prices(
    cube: SessionCube,
    convention: str,
    side: str,
    sig: np.ndarray | None = None,
    zones: sr_levels.CloseZones | None = None,
    yhat: np.ndarray | None = None,
    next_bar: bool = False,
) -> np.ndarray:
    """Return (N,) raw-basis fill prices for `convention` and `side`."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, not {side!r}")
    if len(cube) == 0:
        return np.zeros(0)
    if convention in LEVELS or convention in SR_CONVENTIONS or convention in TI_RULES:
        return waiting_fills(cube, convention, side, sig, zones, yhat, next_bar)[0]
    if convention in ("next_open", "breakout_gate"):
        return np.asarray(cube.open[:, 0], dtype=float)
    if convention == "first_hour_vwap":
        return session_anatomy._vwap(
            cube.close[:, :FIRST_HOUR_SLOTS], cube.volume[:, :FIRST_HOUR_SLOTS]
        )
    if convention == "session_vwap":
        return session_anatomy._vwap(cube.close, cube.volume)
    if convention == "next_close":
        return _official_close(cube)
    if convention == "dip_or_close":
        return _dip_or_close(cube, side, next_bar)
    if convention == "late_day":
        slots = list(LATE_SLOTS)
        return session_anatomy._vwap(cube.close[:, slots], cube.volume[:, slots])
    raise ValueError(f"unknown convention {convention!r}")


# The price one order fills at on one session, from that session's bars:
# `row` holds the session's `open`, `high`, `low`, `close`, `volume` (26,)
# and `auction_open` (a float, NaN when absent). For `breakout_gate`,
# `blocked` says whether the daily was rejecting its band on the decision
# date: a blocked buy is deferred and the price is NaN. For a level
# convention, `sig` is the volatility the order reads (NaN: dip_or_close).
# For an SR convention, `zones` holds the session's (26,) support and
# resistance confluence at each bar close. For a T-I convention, `yhat` is
# the session's (24,) forecast vector (all NaN: no forecast). `next_bar`
# moves a bar-close fill to the next bar's open.
def fill_price(
    row: dict[str, Any],
    convention: str,
    side: str,
    blocked: bool = False,
    sig: float = math.nan,
    zones: sr_levels.CloseZones | None = None,
    yhat: np.ndarray | None = None,
    next_bar: bool = False,
) -> float:
    """Return the fill price for one session, NaN when the order is deferred."""
    if convention == "breakout_gate" and side == "buy" and blocked:
        return math.nan
    cube = SessionCube(
        ticker="row",
        dates=np.array(["2000-01-03"], dtype="datetime64[D]"),
        open=np.asarray(row["open"], dtype=float)[None, :],
        high=np.asarray(row["high"], dtype=float)[None, :],
        low=np.asarray(row["low"], dtype=float)[None, :],
        close=np.asarray(row["close"], dtype=float)[None, :],
        volume=np.asarray(row["volume"], dtype=float)[None, :],
        prior_close=np.array([math.nan]),
        excluded={},
        auction_open=np.array([float(row.get("auction_open", math.nan))]),
        auction_volume=np.array([math.nan]),
    )
    per_session = np.array([sig], dtype=float) if convention in LEVELS else None
    one = None
    if zones is not None:
        one = sr_levels.CloseZones(
            support=np.asarray(zones.support).reshape(1, FULL_SESSION_SLOTS),
            resistance=np.asarray(zones.resistance).reshape(1, FULL_SESSION_SLOTS),
        )
    vector = None
    if yhat is not None:
        vector = np.asarray(yhat, dtype=float).reshape(1, stage3_io.TI_SLOTS)
    return float(
        session_prices(cube, convention, side, per_session, one, vector, next_bar)[0]
    )


# A level convention needs the (sessions, names) sigma grid, on the panel's
# shape; the other conventions read none.
def _check_sigma_grid(
    convention: str, sig: np.ndarray | None, shape: tuple[int, int]
) -> None:
    """Raise ValueError when a level convention's sigma grid is absent or misshapen."""
    if convention not in LEVELS:
        return
    if sig is None:
        raise ValueError(f"{convention} needs the (sessions, names) sigma grid")
    if np.shape(sig) != shape:
        raise ValueError(f"sigma grid {np.shape(sig)} is not the panel's {shape}")


# An SR convention needs the close zones of every name it prices
# (`sr_zones`); the other conventions read none.
def _check_zones(
    convention: str, zones: dict[str, sr_levels.CloseZones] | None
) -> None:
    """Raise ValueError when an SR convention has no close zones."""
    if convention in SR_CONVENTIONS and zones is None:
        raise ValueError(f"{convention} needs the close zones (fill_timing.sr_zones)")


# A T-I convention needs its family's forecast lookup
# (`stage3_io.ti_lookup`); the other conventions read none.
def _check_ti(convention: str, ti: Mapping[Any, Any] | None) -> None:
    """Raise ValueError when a T-I convention has no forecast lookup."""
    if convention in TI_RULES and ti is None:
        family = TI_RULES[convention].family
        raise ValueError(f"{convention} needs the {family} T-I forecast lookup")


@dataclass(frozen=True)
class TiForecast:
    """One family's T-I forecast as the engine reads it: the lookup, its origin."""

    family: str
    lookup: dict[tuple[str, np.datetime64], np.ndarray]
    identity: dict[str, Any] = field(default_factory=dict)


# A T-I forecast file's rows as the engine reads them: the family's
# (ticker, fill session) -> (24,) lookup from `stage3_io.ti_lookup`, of the
# seed ensemble or, with `seed_column`, of that single seed's column of
# `yhat_seeds` (the seed-stability runs). `identity` (the file and its
# sha256) is carried into the payload beside the seed column.
def ti_forecast(
    forecast: stage3_io.Stage3Forecast,
    seed_column: int | None = None,
    identity: dict[str, Any] | None = None,
) -> TiForecast:
    """Return the TiForecast of a T-I Stage3Forecast."""
    if forecast.kind != stage3_io.TI:
        raise ValueError(f"a T-I forecast is needed; this one is {forecast.kind!r}")
    if forecast.family not in TI_FAMILIES:
        raise ValueError(
            f"T-I family {forecast.family!r} is not one of {', '.join(TI_FAMILIES)}"
        )
    column = None
    if seed_column is not None:
        seeds = np.asarray(forecast.yhat_seeds)
        if seeds.ndim != 2 or not 0 <= int(seed_column) < seeds.shape[1]:
            raise ValueError(
                f"seed column {seed_column} is outside the file's "
                f"{seeds.shape[1] if seeds.ndim == 2 else 0} seed columns"
            )
        column = seeds[:, int(seed_column)]
    return TiForecast(
        family=forecast.family,
        lookup=stage3_io.ti_lookup(forecast, column),
        identity={
            **(identity or {}),
            "family": forecast.family,
            "seed_column": None if seed_column is None else int(seed_column),
        },
    )


# The first fill session any slot of a lookup forecasts, as a date; None
# when the lookup holds no finite forecast at all.
def ti_first_session(
    lookup: Mapping[tuple[str, np.datetime64], np.ndarray],
) -> date | None:
    """Return the earliest session whose vector has a finite forecast."""
    days = [
        np.datetime64(key[1], "D")
        for key, vector in lookup.items()
        if np.isfinite(np.asarray(vector, dtype=float)).any()
    ]
    if not days:
        return None
    first: date = min(days).astype(object)
    return first


# What a lookup covers: its (name, session) vectors, those with a forecast,
# those with a forecast in some slots and NaN in others (never expected: a
# name-session's 24 rows are predicted together), and the first and last
# forecast sessions.
def ti_coverage(
    lookup: Mapping[tuple[str, np.datetime64], np.ndarray],
) -> dict[str, Any]:
    """Return the coverage record of a T-I lookup."""
    finite = {key: np.isfinite(np.asarray(v, dtype=float)) for key, v in lookup.items()}
    covered = [key for key, f in finite.items() if f.any()]
    days = sorted(np.datetime64(key[1], "D") for key in covered)
    return {
        "vectors": len(lookup),
        "vectors_with_forecast": len(covered),
        "partial_vectors": sum(1 for f in finite.values() if f.any() and not f.all()),
        "first_forecast_session": str(days[0]) if days else None,
        "last_forecast_session": str(days[-1]) if days else None,
    }


# One ticker's forecast vectors on its cube's sessions, from a family's
# lookup keyed by (ticker, fill session): (sessions, 24), NaN where the
# lookup has no vector for that session.
def ti_grid(
    lookup: Mapping[tuple[str, np.datetime64], np.ndarray],
    ticker: str,
    dates: np.ndarray,
) -> np.ndarray:
    """Return the (len(dates), 24) forecast vectors of `ticker` on `dates`."""
    days = np.asarray(dates, dtype="datetime64[D]")
    out = np.full((len(days), stage3_io.TI_SLOTS), np.nan)
    for i, day in enumerate(days):
        vector = lookup.get((str(ticker), np.datetime64(day, "D")))
        if vector is not None:
            out[i] = np.asarray(vector, dtype=float)
    return out


# Where each cube session sits on the panel's calendar, and the ratio that
# moves its raw tape dollars onto the panel's adjusted basis: the panel's
# adjusted close over the cube's own official close of the same day (the
# closing cross, else the last regular print when the partition has no
# cross). The daily store's `close` is already split-adjusted (its
# `adj_close / close` undoes dividends only), so scaling by that ratio left
# a pre-split raw fill against a post-split mark; this ratio carries both
# splits and dividends, whatever the split calendar. Returns (pos, ok,
# scale): `scale` has one value per cube session, NaN for a session the
# panel does not hold (`ok` False) or whose official close is not positive.
def session_scale(
    cube: SessionCube, dates: np.ndarray, adj_close: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ((N,) panel rows, (N,) on the panel, (N,) adjusted/raw scale)."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    rows = len(dates)
    pos = np.searchsorted(dates, cube.dates)
    ok = (pos < rows) & (dates[np.minimum(pos, rows - 1)] == cube.dates)
    official = np.where(
        np.isfinite(cube.auction_open) & (cube.auction_open > 0),
        cube.auction_open,
        cube.close[:, -1],
    )
    scale = np.full(len(cube), np.nan)
    with np.errstate(all="ignore"):
        scale[ok] = np.where(
            official[ok] > 0, np.asarray(adj_close)[pos[ok]] / official[ok], np.nan
        )
    return pos, ok, scale


# The close zones of every panel name with a cube, for the SR conventions:
# the daily structure once for the whole panel, then per name its levels
# on the cube's sessions at the fills' own basis scale, their confluence,
# and the largest confluence of a zone holding each bar's close.
def sr_zones(
    cubes: dict[str, SessionCube], panel
) -> dict[str, sr_levels.CloseZones]:
    """Return {ticker: CloseZones} for every panel name with a cube."""
    daily = sr_levels.daily_levels(panel)
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    out: dict[str, sr_levels.CloseZones] = {}
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None or len(cube) == 0:
            continue
        pos, ok, scale = session_scale(cube, dates, panel.adj_close[:, j])
        levels = sr_levels.for_cube(cube, daily, j, pos, ok, scale)
        out[ticker] = sr_levels.close_zones(levels, sr_levels.confluence(levels))
    return out


# Every name's fill prices for one convention on the panel's calendar, raw
# basis, NaN where the name has no complete cube session that day. A level
# convention needs `sig`, the (T, N) volatility each fill session's order
# reads (`fill_sigma`); an SR convention needs `zones`, each name's close
# zones on its cube's sessions (`sr_zones`); a T-I convention needs `ti`,
# its family's (ticker, fill session) -> (24,) lookup. A WAITING
# convention's result carries, per cell, whether the order filled at its
# level before the close, its gain over the session's official close in
# bp, and whether it had no sigma (for a T-I convention: no forecast; a
# T-I filter's also whether its trigger came late). `next_bar` moves every
# bar-close fill to the next bar's open.
def cube_prices(  # noqa: C901 - one pass per name: scale, price, detail
    cubes: dict[str, SessionCube],
    panel,
    convention: str,
    sig: np.ndarray | None = None,
    zones: dict[str, sr_levels.CloseZones] | None = None,
    ti: Mapping[tuple[str, np.datetime64], np.ndarray] | None = None,
    next_bar: bool = False,
) -> FillPrices:
    """Return the FillPrices of `convention` aligned to `panel.dates`."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    rows, names = panel.adj_close.shape
    buy = np.full((rows, names), np.nan)
    sell = np.full((rows, names), np.nan)
    available = np.zeros((rows, names), dtype=bool)
    waiting = convention in WAITING
    ti_on = convention in TI_RULES
    _check_sigma_grid(convention, sig, (rows, names))
    _check_zones(convention, zones)
    _check_ti(convention, ti)
    if waiting:
        hits = {side: np.zeros((rows, names), dtype=bool) for side in ("buy", "sell")}
        gains = {side: np.full((rows, names), np.nan) for side in ("buy", "sell")}
        no_sigma = np.zeros((rows, names), dtype=bool)
        late = {side: np.zeros((rows, names), dtype=bool) for side in ("buy", "sell")}
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None or len(cube) == 0:
            continue
        pos, ok, per_session = session_scale(cube, dates, panel.adj_close[:, j])
        scale = per_session[ok]
        if not waiting:
            buy[pos[ok], j] = (
                session_prices(cube, convention, "buy", next_bar=next_bar)[ok] * scale
            )
            sell[pos[ok], j] = (
                session_prices(cube, convention, "sell", next_bar=next_bar)[ok] * scale
            )
            available[pos[ok], j] = np.isfinite(scale)
            continue
        cube_sig = None
        if convention in LEVELS:
            # The fill session's sigma, from the panel's grid onto the cube's sessions.
            cube_sig = np.full(len(cube), np.nan)
            cube_sig[ok] = np.asarray(sig, dtype=float)[pos[ok], j]
        cube_zones = None
        if convention in SR_CONVENTIONS:
            assert zones is not None  # _check_zones refused a run without them
            cube_zones = zones.get(ticker)
            if cube_zones is None:
                raise ValueError(f"{convention}: no close zones for {ticker}")
        cube_yhat = None
        if ti_on:
            assert ti is not None  # _check_ti refused a run without it
            cube_yhat = ti_grid(ti, ticker, cube.dates)
        close = _official_close(cube)
        for side, out in (("buy", buy), ("sell", sell)):
            if ti_on:
                fills = ti_fills(cube, convention, side, cube_yhat, next_bar)
                price, hit, missing = fills.price, fills.hit, fills.no_forecast
                late[side][pos[ok], j] = fills.late[ok]
            else:
                price, hit, missing = waiting_fills(
                    cube, convention, side, cube_sig, cube_zones, next_bar=next_bar
                )
            out[pos[ok], j] = price[ok] * scale
            hits[side][pos[ok], j] = hit[ok]
            with np.errstate(all="ignore"):
                better = (close - price) if side == "buy" else (price - close)
                gain = np.where(close > 0, better / close * BP, np.nan)
            gains[side][pos[ok], j] = gain[ok]
            no_sigma[pos[ok], j] |= missing[ok]
        available[pos[ok], j] = np.isfinite(scale)
    if not waiting:
        return FillPrices(convention, buy, sell, available)
    detail = WaitDetail(
        hits["buy"],
        hits["sell"],
        gains["buy"],
        gains["sell"],
        no_sigma,
        late["buy"] if ti_on else None,
        late["sell"] if ti_on else None,
    )
    return FillPrices(convention, buy, sell, available, detail)


# The forecasts must sit on the report's own grid - the panel's dates and
# names, in order - or every sigma would be read from the wrong cell.
def check_grid(aligned: Aligned, panel: Panel) -> None:
    """Raise ValueError unless `aligned` is on `panel`'s (dates, tickers) grid."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    own = np.asarray(aligned.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    if (
        own.shape != dates.shape
        or not (own == dates).all()
        or tuple(aligned.tickers) != tuple(panel.tickers)
        or np.shape(aligned.forecast) != shape
        or np.shape(aligned.baseline) != shape
    ):
        raise ValueError(
            "the forecasts are not on the report's panel grid; align them with "
            "vol_forecast.aligned_to_panel(path, report.panel)"
        )


# The volatility each order of a level convention reads, on its fill
# session's row: sigma = exp(F / 2) of the forecast row dated s - 1 for an
# order filling on session s. That row is the decision session's: the
# forecast was made at its close and targets the next session, and
# `vol_forecast.align` puts row (name, t) at the panel's row of t. Nothing
# dated s or later is read. `trail_dip` reads the trailing baseline on
# exactly the cells where the forecast exists, so it differs from
# vol_dip_0.5 only in where sigma comes from. NaN where there is nothing to
# read (the order then fills as dip_or_close); row 0 has no decision before it.
def fill_sigma(aligned: Aligned, convention: str) -> np.ndarray:
    """Return the (T, N) sigma a `convention` order filling on each session reads."""
    if convention not in LEVELS:
        raise ValueError(f"{convention!r} is not a level convention")
    forecast = np.asarray(aligned.forecast, dtype=float)
    if LEVELS[convention].source == FORECAST:
        decision = forecast
    else:
        baseline = np.asarray(aligned.baseline, dtype=float)
        decision = np.where(np.isfinite(forecast), baseline, np.nan)
    at_decision = sigma(decision)
    out = np.full(at_decision.shape, np.nan)
    out[1:] = at_decision[:-1]
    return out


# The session a gated buy decided on `t` fills on: the first session after
# `t` whose previous close was not rejecting the band, at most
# MAX_DEFERRALS sessions late. Returns (fill session, deferrals).
def _gated_fill_session(blocked: np.ndarray, t: int, j: int) -> tuple[int, int]:
    """Return (session, deferrals) for a band-gated buy decided on `t`."""
    deferrals = 0
    rows = blocked.shape[0]
    while (
        deferrals < MAX_DEFERRALS
        and t + deferrals < rows
        and bool(blocked[t + deferrals, j])
    ):
        deferrals += 1
    return t + 1 + deferrals, deferrals


# Hold the policy's targets in the simulator's ledger, filling every share
# order at the convention's price on its fill session and marking at the
# panel's adjusted close. Returns daily returns aligned to the panel; for a
# WAITING convention also the log of its cube-priced orders (session, side,
# filled at the level, gain over the close, no sigma), read and never fed
# back into a price.
def price_book(  # noqa: C901 - one ledger walk: queue, fill, mark, decide
    targets: TargetPath,
    report,
    prices: FillPrices,
    convention: str,
    cost_bps: float,
    blocked: np.ndarray | None = None,
) -> Priced:
    """Return the Priced series of `convention` for the targets."""
    if convention not in PRICEABLE:
        raise ValueError(f"unknown convention {convention!r}")
    if convention == "breakout_gate" and blocked is None:
        raise ValueError("breakout_gate needs the band-rejection flags")
    panel = report.panel
    rows, names = panel.adj_close.shape
    closes = panel.adj_close
    opens = simulate.adjusted_open(panel)
    stamps = [str(d) for d in panel.dates]
    book = simulate._Book(names, simulate.START_EQUITY, cost_bps, panel, report, stamps)
    returns = np.full(rows, np.nan)
    equity = np.full(rows, np.nan)
    start = targets.start
    decisions = set(targets.decisions)
    # Orders waiting to fill: session -> list of (column, share delta).
    pending: dict[int, list[tuple[int, float]]] = {}
    fills = deferrals = fallbacks = 0
    detail = prices.detail
    # One entry per cube-priced order of a waiting convention: (session,
    # buy, filled at the level, gain bp, no sigma, column, late trigger).
    log: list[tuple[int, bool, bool, float, bool, int, bool]] = []
    equity[start] = book.equity(closes[start])

    # Queue the share moves a decision on `t` asks for, each on its fill session.
    def decide(t: int) -> None:
        nonlocal deferrals
        order = book.plan(targets.weights[t], closes[t])
        delta = order - book.shares
        # A new decision supersedes anything still waiting, as a rebalance
        # supersedes the simulator's deferred leg.
        pending.clear()
        for j in np.flatnonzero(np.abs(delta) > 1e-12):
            session = t + 1
            if convention == "breakout_gate" and delta[j] > 0:
                session, late = _gated_fill_session(blocked, t, j)
                deferrals += late
            if session < rows:
                pending.setdefault(session, []).append((int(j), float(delta[j])))

    # Fill what is due on `s` at the convention's adjusted price, one ledger call.
    def fill(s: int) -> None:
        nonlocal fills, fallbacks
        due = pending.pop(s, None)
        if not due:
            return
        order = np.array(book.shares, dtype=float)
        price = np.full(names, np.nan)
        for j, delta in due:
            order[j] = max(book.shares[j] + delta, 0.0)
            raw = prices.buy[s, j] if delta > 0 else prices.sell[s, j]
            # `prices` are already on the panel's adjusted basis (cube_prices).
            if prices.available[s, j] and np.isfinite(raw) and raw > 0:
                price[j] = raw
                if detail is not None:
                    buying = delta > 0
                    hit = detail.buy_hit if buying else detail.sell_hit
                    gain = detail.buy_gain_bp if buying else detail.sell_gain_bp
                    missing = bool(detail.no_sigma[s, j])
                    lates = detail.buy_late if buying else detail.sell_late
                    late = bool(lates[s, j]) if lates is not None else False
                    log.append(
                        (
                            s,
                            buying,
                            bool(hit[s, j]),
                            float(gain[s, j]),
                            missing,
                            int(j),
                            late,
                        )
                    )
            else:
                price[j] = opens[s, j]
                fallbacks += 1
            fills += 1
        book.settle(order, price, s, convention)

    if start in decisions:
        decide(start)
    for s in range(start + 1, rows):
        fill(s)
        equity[s] = book.equity(closes[s])
        returns[s] = equity[s] / equity[s - 1] - 1.0 if equity[s - 1] > 0 else np.nan
        if s in decisions:
            decide(s)
    waits = None
    if detail is not None:
        waits = OrderLog(
            session=np.array([e[0] for e in log], dtype=int),
            buy=np.array([e[1] for e in log], dtype=bool),
            hit=np.array([e[2] for e in log], dtype=bool),
            gain_bp=np.array([e[3] for e in log], dtype=float),
            no_sigma=np.array([e[4] for e in log], dtype=bool),
            column=np.array([e[5] for e in log], dtype=int),
            late=np.array([e[6] for e in log], dtype=bool),
        )
    return Priced(convention, start, returns, fills, deferrals, fallbacks, waits)


# The k-th panel session as a date, the scorecard's `_since`.
def since_offset(panel, k: int) -> date:
    """Return panel session `k` as a date."""
    return panel.dates[k].astype("datetime64[D]").astype(object)


# Sessions inside [start, end) as a mask over the panel's dates.
def _window(dates: np.ndarray, start: date | None, end: date | None) -> np.ndarray:
    days = np.asarray(dates, dtype="datetime64[D]")
    keep = np.ones(len(days), dtype=bool)
    if start is not None:
        keep &= days >= np.datetime64(start, "D")
    if end is not None:
        keep &= days < np.datetime64(end, "D")
    return keep


# Annualised return of the finite entries of a daily series, NaN under two.
def _cagr(daily: np.ndarray) -> float:
    r = daily[np.isfinite(daily)]
    if len(r) < 2:
        return math.nan
    return float(np.prod(1.0 + r) ** (252.0 / len(r)) - 1.0)


# Median over finite entries, NaN when there are none.
def _nanmedian(x: np.ndarray) -> float:
    return float(np.nanmedian(x)) if np.isfinite(x).any() else math.nan


# The paired daily difference of two aligned series over a window.
def _excess(a: np.ndarray, b: np.ndarray, keep: np.ndarray) -> np.ndarray:
    diff = (a - b)[keep]
    return diff[np.isfinite(diff)]


# Mean over finite entries, NaN when there are none.
def _finite_mean(x: np.ndarray) -> float:
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    return float(v.mean()) if len(v) else math.nan


# Whether a payload number is a finite float (None, as JSON writes NaN, is not).
def _finite(x: Any) -> bool:
    return x is not None and math.isfinite(float(x))


# The conventions a run prices, in registered order. By default the seven
# fill-timing conventions, the four level conventions too when forecasts
# are given, and the T-I conventions of every family in `ti_families` (the
# families whose T-I forecast is given); the SR conventions only when
# named. With `only`, the names given plus the controls the verdicts read:
# next_open always; dip_or_close and trail_dip whenever a level convention
# is named; dip_or_close whenever an SR or T-I convention is. Refused: an
# unknown name or family, a level convention without forecasts, a T-I
# convention without its family's forecast, and a family's forecast none of
# whose conventions is priced.
def select_conventions(
    only: Iterable[str] | None,
    have_forecasts: bool,
    ti_families: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return the conventions to price, in PRICEABLE order."""
    families = {str(f).strip() for f in ti_families if str(f).strip()}
    strange = sorted(families - set(TI_FAMILIES))
    if strange:
        raise ValueError(
            f"unknown T-I family {', '.join(strange)}; registered: "
            f"{', '.join(TI_FAMILIES)}"
        )
    if only is None:
        names = set(CONVENTIONS) | (set(LEVEL_CONVENTIONS) if have_forecasts else set())
        names |= {c for c, rule in TI_RULES.items() if rule.family in families}
    else:
        names = {str(c).strip() for c in only if str(c).strip()}
        unknown = sorted(names - set(PRICEABLE))
        if unknown:
            raise ValueError(
                f"unknown convention(s) {', '.join(unknown)}; registered: "
                f"{', '.join(PRICEABLE)}"
            )
        names.add(CONTROL)
        if names & set(LEVEL_CONVENTIONS):
            names |= {LEVEL_CONTROL, LEVEL_TWIN}
        if names & set(SR_CONVENTIONS):
            names.add(LEVEL_CONTROL)
        if names & set(TI_CONVENTIONS):
            names.add(TI_CONTROL)
    if names & set(LEVEL_CONVENTIONS) and not have_forecasts:
        raise ValueError(
            "the level conventions need the volatility forecasts (--forecasts <npz>)"
        )
    without = sorted(
        c for c in names & set(TI_CONVENTIONS) if TI_RULES[c].family not in families
    )
    if without:
        raise ValueError(
            f"the T-I convention(s) {', '.join(without)} need their family's forecast "
            "(--stage3-forecast <family>=<npz>)"
        )
    priced = {TI_RULES[c].family for c in names & set(TI_RULES)}
    unused = sorted(families - priced)
    if unused:
        raise ValueError(
            f"a T-I forecast was given for {', '.join(unused)} but none of its "
            "conventions is priced"
        )
    return tuple(c for c in PRICEABLE if c in names)


# From a waiting convention's orders that fill inside the window: how many
# there were, the share filled at the level before the close (the dip fill
# rate), the mean gain over that session's official close per dip fill and
# per order (an order filled at the close gains nothing), and how many had
# no sigma and filled as dip_or_close. Rates are NaN for a convention that
# does not wait.
def _wait_fields(log: OrderLog | None, keep: np.ndarray) -> dict[str, Any]:
    """Return the dip fill and sigma fallback fields of one row."""
    if log is None:
        return {
            "dip_orders": 0,
            "dip_fills": 0,
            "dip_fill_rate": math.nan,
            "gain_bp_per_dip_fill": math.nan,
            "gain_bp_per_order": math.nan,
            "sigma_fallbacks": 0,
            "sigma_fallback_share": math.nan,
        }
    inside = keep[log.session]
    orders = int(inside.sum())
    hit = log.hit & inside
    missing = log.no_sigma & inside
    return {
        "dip_orders": orders,
        "dip_fills": int(hit.sum()),
        "dip_fill_rate": float(hit.sum() / orders) if orders else math.nan,
        "gain_bp_per_dip_fill": _finite_mean(log.gain_bp[hit]),
        "gain_bp_per_order": _finite_mean(log.gain_bp[inside]),
        "sigma_fallbacks": int(missing.sum()),
        "sigma_fallback_share": float(missing.sum() / orders) if orders else math.nan,
    }


# One convention's row against dip_or_close on one window: across offsets
# the median CAGR difference and the count above dip_or_close, and at the
# median offset the paired daily difference (bp, HAC t). Also returns that
# difference, for the deflated best. Shared by the entry-level and SR trials.
def _vs_dip_fields(
    priced: dict[str, list[Priced]],
    convention: str,
    median: int,
    keep: np.ndarray,
    cagrs: dict[str, np.ndarray],
) -> tuple[dict[str, Any], np.ndarray]:
    """Return (the vs-dip row fields, paired difference against dip_or_close)."""
    at = priced[convention][median]
    vs_dip = _excess(at.returns, priced[LEVEL_CONTROL][median].returns, keep)
    fields: dict[str, Any] = {
        "median_cagr_vs_dip": _nanmedian(cagrs[convention] - cagrs[LEVEL_CONTROL]),
        "offsets_above_dip": int(np.nansum(cagrs[convention] > cagrs[LEVEL_CONTROL])),
        "mean_daily_bp_vs_dip": float(vs_dip.mean() * BP)
        if len(vs_dip)
        else math.nan,
        "hac_t_vs_dip": candidate_stats.hac_t(vs_dip, HAC_LAG)
        if len(vs_dip) > 2
        else math.nan,
    }
    return fields, vs_dip


# The entry-level trial's fields for one convention's row on one window:
# at the median offset the paired daily difference against dip_or_close and
# against trail_dip (bp, HAC t), across offsets the median CAGR difference
# and the count above dip_or_close, and the median offset's order fields.
# Also returns the difference against dip_or_close, for the deflated best.
def _level_fields(
    priced: dict[str, list[Priced]],
    convention: str,
    median: int,
    keep: np.ndarray,
    cagrs: dict[str, np.ndarray],
) -> tuple[dict[str, Any], np.ndarray]:
    """Return (row fields, paired difference against dip_or_close)."""
    fields, vs_dip = _vs_dip_fields(priced, convention, median, keep, cagrs)
    at = priced[convention][median]
    vs_twin = _excess(at.returns, priced[LEVEL_TWIN][median].returns, keep)
    fields["mean_daily_bp_vs_twin"] = (
        float(vs_twin.mean() * BP) if len(vs_twin) else math.nan
    )
    fields["hac_t_vs_twin"] = (
        candidate_stats.hac_t(vs_twin, HAC_LAG) if len(vs_twin) > 2 else math.nan
    )
    fields.update(_wait_fields(at.waits, keep))
    return fields, vs_dip


# The SR trial's fields for one convention's row on one window: the
# comparison against dip_or_close (`_vs_dip_fields`) and the median
# offset's order fields, where the "dip" fill is a fill at a level zone.
# Also returns the difference against dip_or_close, for the deflated best.
def _sr_fields(
    priced: dict[str, list[Priced]],
    convention: str,
    median: int,
    keep: np.ndarray,
    cagrs: dict[str, np.ndarray],
) -> tuple[dict[str, Any], np.ndarray]:
    """Return (row fields, paired difference against dip_or_close)."""
    fields, vs_dip = _vs_dip_fields(priced, convention, median, keep, cagrs)
    fields.update(_wait_fields(priced[convention][median].waits, keep))
    return fields, vs_dip


# How far this engine's `next_open` sits from the simulator it stands in
# for, at one offset: the simulator's own returns against the control's,
# in basis points a day. Zero on a store whose bar-0 opens are the panel's
# opens; on the real store the SIP first print and the daily open differ.
def simulator_gap(report, mask: np.ndarray, control: Priced, cost_bps: float) -> dict:
    """Return the mean and largest absolute daily gap to `simulate.run`."""
    panel = report.panel
    sim = simulate.run(
        report,
        since=since_offset(panel, control.start),
        allocator=policy_v4.allocator(mask),
        cost_bps=cost_bps,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
    )
    ours = control.returns[control.start :]
    diff = ours - sim.returns
    finite = diff[np.isfinite(diff)]
    return {
        "offset": int(control.start),
        "sessions": int(len(finite)),
        "mean_abs_bp": float(np.abs(finite).mean() * BP) if len(finite) else math.nan,
        "max_abs_bp": float(np.abs(finite).max() * BP) if len(finite) else math.nan,
        "mean_bp": float(finite.mean() * BP) if len(finite) else math.nan,
        "nan_mismatch": int((np.isfinite(ours) != np.isfinite(sim.returns)).sum()),
    }


# Every chosen convention priced from each of the first `offsets` start
# sessions: its fill prices once (a level convention's at the sigma its
# orders read, an SR convention's on the close zones, built here once
# unless given, a T-I convention's on its family's forecast in `ti`), then
# one ledger walk per offset. The band flags are read only when
# breakout_gate is priced. `next_bar` moves every bar-close fill to the
# next bar's open. Returns the priced series and the fill prices they used.
def _price_all(
    report: DeskReport,
    cubes: dict[str, SessionCube],
    mask: np.ndarray,
    chosen: tuple[str, ...],
    forecasts: Aligned | None,
    offsets: int,
    cost: float,
    zones: dict[str, sr_levels.CloseZones] | None = None,
    ti: Mapping[str, TiForecast] | None = None,
    next_bar: bool = False,
) -> tuple[dict[str, list[Priced]], dict[str, FillPrices]]:
    """Return ({convention: [Priced per offset]}, {convention: FillPrices})."""
    panel = report.panel
    blocked = band_rejecting(panel) if "breakout_gate" in chosen else None
    if zones is None and any(c in SR_CONVENTIONS for c in chosen):
        zones = sr_zones(cubes, panel)
    prices: dict[str, FillPrices] = {}
    for c in chosen:
        sig = None
        if c in LEVELS:
            if forecasts is None:
                raise ValueError(f"{c} needs the volatility forecasts")
            sig = fill_sigma(forecasts, c)
        own_zones = zones if c in SR_CONVENTIONS else None
        own_ti = None
        if c in TI_RULES:
            family = TI_RULES[c].family
            if ti is None or family not in ti:
                raise ValueError(f"{c} needs the {family} T-I forecast")
            own_ti = ti[family].lookup
        prices[c] = cube_prices(cubes, panel, c, sig, own_zones, own_ti, next_bar)
    priced: dict[str, list[Priced]] = {c: [] for c in chosen}
    for k in range(offsets):
        targets = target_path(report, mask, since_offset(panel, k))
        for c in chosen:
            priced[c].append(price_book(targets, report, prices[c], c, cost, blocked))
    return priced, prices


# Price every convention from every offset, then score them per window.
# `conventions` narrows the set (`select_conventions`: the controls the
# verdicts read are always added); `forecasts`, the volatility forecasts on
# the report's panel grid (`vol_forecast.aligned_to_panel`), is what the
# level conventions read; `ti_forecasts`, {family: TiForecast}, is what the
# stage-3 T-I conventions read. Without any, this is the fill-timing trial
# exactly as registered. With a level convention priced, every row gains
# the entry-level fields and the payload a "level" block with its verdict;
# with a T-I convention, the payload gains the "stage3_ti" block.
# `next_bar` is the stage-3 robustness run: every bar-close fill moves to
# the next bar's open, and the payload says so.
def study(
    report,
    cubes: dict[str, SessionCube],
    mask: np.ndarray,
    offsets: int = 20,
    cost: float = COST_BPS[0],
    conventions: Iterable[str] | None = None,
    forecasts: Aligned | None = None,
    zones: dict[str, sr_levels.CloseZones] | None = None,
    ti_forecasts: Mapping[str, TiForecast] | None = None,
    next_bar: bool = False,
) -> dict[str, Any]:
    """Return the trial payload: rows per (convention, window), best, verdict."""
    if offsets < 1:
        raise ValueError("offsets must be at least 1")
    ti_forecasts = _checked_ti_forecasts(ti_forecasts)
    chosen = select_conventions(conventions, forecasts is not None, tuple(ti_forecasts))
    panel = report.panel
    if forecasts is not None:
        check_grid(forecasts, panel)
    level_on = any(c in LEVELS for c in chosen)
    sr_on = any(c in SR_CONVENTIONS for c in chosen)
    priced, prices = _price_all(
        report,
        cubes,
        mask,
        chosen,
        forecasts,
        offsets,
        cost,
        zones,
        ti_forecasts,
        next_bar,
    )
    median = offsets // 2
    rows: list[dict[str, Any]] = []
    best: dict[str, dict[str, Any]] = {}
    level_best: dict[str, dict[str, Any]] = {}
    sr_best: dict[str, dict[str, Any]] = {}
    for window, (lo, hi) in WINDOWS.items():
        keep = _window(panel.dates, lo, hi)
        cagrs = {
            c: np.array([_cagr(p.returns[keep]) for p in priced[c]])
            for c in chosen
        }
        control = priced[CONTROL][median].returns
        # The fill-timing trial's excess moments (its own seven conventions
        # only) and the entry-level trial's (the level conventions against
        # dip_or_close): each best is deflated against its own trials.
        moments: dict[str, candidate_stats.Moments] = {}
        level_moments: dict[str, candidate_stats.Moments] = {}
        sr_moments: dict[str, candidate_stats.Moments] = {}
        for c in chosen:
            at_median = priced[c][median]
            diff = _excess(at_median.returns, control, keep)
            if c in CONVENTIONS:
                moments[c] = candidate_stats.moments(diff)
            row: dict[str, Any] = {
                "convention": c,
                "window": window,
                "cost_bps": cost,
                "offsets": offsets,
                "median_cagr": _nanmedian(cagrs[c]),
                "worst_cagr": float(np.nanmin(cagrs[c]))
                if np.isfinite(cagrs[c]).any()
                else math.nan,
                "best_cagr": float(np.nanmax(cagrs[c]))
                if np.isfinite(cagrs[c]).any()
                else math.nan,
                "median_cagr_vs_open": _nanmedian(cagrs[c] - cagrs[CONTROL]),
                "offsets_above_open": int(np.nansum(cagrs[c] > cagrs[CONTROL])),
                "sessions": int(len(diff)),
                "mean_daily_bp_vs_open": float(diff.mean() * BP)
                if len(diff)
                else math.nan,
                "hac_t_vs_open": candidate_stats.hac_t(diff, HAC_LAG)
                if len(diff) > 2
                else math.nan,
                "fills": int(at_median.fills),
                "deferrals": int(at_median.deferrals),
                "fallbacks": int(at_median.fallbacks),
            }
            if level_on or sr_on:
                extra = _trial_fields(
                    priced, c, median, keep, cagrs, level_on, level_moments, sr_moments
                )
                row.update(extra)
            rows.append(row)
        best[window] = _best(rows, window, moments)
        if level_on:
            level_best[window] = _best(
                rows, window, level_moments, LEVEL_CONTROL, LEVEL_TRIALS, "dip"
            )
        if sr_on:
            sr_best[window] = _best(
                rows, window, sr_moments, LEVEL_CONTROL, SR_TRIALS, "dip"
            )
    payload: dict[str, Any] = {
        "policy": policy_v4.POLICY_VERSION,
        "conventions": list(chosen),
        "control": CONTROL,
        "cost_bps": cost,
        "offsets": offsets,
        "median_offset": median,
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "constants": {
            "DIP": DIP,
            "LATE_SLOTS": list(LATE_SLOTS),
            "FIRST_HOUR_SLOTS": FIRST_HOUR_SLOTS,
            "MAX_DEFERRALS": MAX_DEFERRALS,
            "HAC_LAG": HAC_LAG,
            "TRIALS": TRIALS,
            "ADOPT_BP": ADOPT_BP,
            "ADOPT_T": ADOPT_T,
        },
        "rows": rows,
        "best": best,
        "simulator_gap": simulator_gap(report, mask, priced[CONTROL][median], cost),
        "cube_coverage": {
            "names_with_cube": int(
                sum(1 for t in panel.tickers if t in cubes and len(cubes[t]))
            ),
            "names_in_panel": int(len(panel.tickers)),
        },
        "note": (
            "Orders are the plain simulator's on the point-in-time report; fills "
            "at the convention's SIP price scaled to the panel's adjusted basis; "
            "marks at the panel's adjusted daily close for every convention. VWAPs "
            "are bar closes weighted by bar volume, a proxy. A name without a "
            "complete cube session on its fill day fills at the panel's open and "
            "is counted as a fallback. Costs are one way on every fill."
        ),
    }
    _mark_fill_mode(payload, next_bar, bool(ti_forecasts))
    payload.update(_fill_timing_verdict(payload, chosen))
    _add_trial_blocks(payload, chosen, forecasts, level_best, sr_best)
    if ti_forecasts:
        # select_conventions priced a T-I convention for every family given.
        payload["stage3_ti"] = _ti_block(
            panel, priced, prices, chosen, ti_forecasts, offsets, median, cost, next_bar
        )
    return payload


# Record the fill mode on a run that has one to record: a next-bar run, or a
# run pricing the T-I conventions (whose verdict reads it); a registered
# fill-timing, level or SR run's payload is left as it always was.
def _mark_fill_mode(payload: dict[str, Any], next_bar: bool, stage3: bool) -> None:
    """Set payload["next_bar"] for a next-bar or stage-3 T-I run."""
    if next_bar or stage3:
        payload["next_bar"] = bool(next_bar)


# The T-I forecasts of one run, checked: each in its own family's slot, and
# all read at the same seed column (the ensemble, or one seed).
def _checked_ti_forecasts(
    ti_forecasts: Mapping[str, TiForecast] | None,
) -> dict[str, TiForecast]:
    """Return {family: TiForecast}, refusing a misfiled forecast or mixed seeds."""
    out = dict(ti_forecasts or {})
    for family, forecast in out.items():
        if forecast.family != family:
            raise ValueError(f"the {family} slot holds a {forecast.family} forecast")
    if len({f.identity.get("seed_column") for f in out.values()}) > 1:
        raise ValueError("the T-I forecasts of one run must read the same seed column")
    return out


# The entry-level and SR trials' fields for one row: the level fields
# (which include the comparison against dip_or_close) when a level
# convention is priced, else the SR fields. Each trial's own conventions
# also record their excess over dip_or_close into that trial's moments,
# for its deflated best.
def _trial_fields(
    priced: dict[str, list[Priced]],
    convention: str,
    median: int,
    keep: np.ndarray,
    cagrs: dict[str, np.ndarray],
    level_on: bool,
    level_moments: dict[str, candidate_stats.Moments],
    sr_moments: dict[str, candidate_stats.Moments],
) -> dict[str, Any]:
    """Return the row's trial fields, recording the moments of each trial's own."""
    fields_of = _level_fields if level_on else _sr_fields
    extra, vs_dip = fields_of(priced, convention, median, keep, cagrs)
    if convention in LEVELS:
        level_moments[convention] = candidate_stats.moments(vs_dip)
    if convention in SR_CONVENTIONS:
        sr_moments[convention] = candidate_stats.moments(vs_dip)
    return extra


# The payload's entry-level block when a level convention was priced and
# its SR block when an SR convention was, each with its verdict merged in.
def _add_trial_blocks(
    payload: dict[str, Any],
    chosen: tuple[str, ...],
    forecasts: Aligned | None,
    level_best: dict[str, dict[str, Any]],
    sr_best: dict[str, dict[str, Any]],
) -> None:
    """Add the "level" and "sr_level" blocks the chosen conventions call for."""
    if any(c in LEVELS for c in chosen):
        assert forecasts is not None  # select_conventions refuses levels without them
        payload["level"] = _level_block(forecasts, chosen, level_best)
        payload["level"].update(level_verdict(payload))
        _mark_next_bar(payload, payload["level"])
    if any(c in SR_CONVENTIONS for c in chosen):
        payload["sr_level"] = _sr_block(chosen, sr_best, payload["rows"])
        payload["sr_level"].update(sr_verdict(payload))
        _mark_next_bar(payload, payload["sr_level"])


# The prefix a verdict read off a `--next-bar` run carries: its fills are
# the robustness run's, not the ones the trial registered.
NEXT_BAR_READING = "next-bar robustness reading, not the registered fills: "


# In a `--next-bar` run, say so on a trial block and its verdict line; a
# run at the registered fills is left exactly as it was.
def _mark_next_bar(payload: dict[str, Any], block: dict[str, Any]) -> None:
    """Flag `block` and prefix its verdict when the payload is a next-bar run."""
    if payload.get("next_bar"):
        block["next_bar"] = True
        block["verdict"] = NEXT_BAR_READING + str(block["verdict"])


# The fill-timing verdict's fields: `verdict` when all seven of its
# conventions were priced at the registered fills; when `--only` left some
# unpriced, or the run is a `--next-bar` one, a NOT JUDGED line, since that
# trial is judged on its whole registered set at its own fills or not at all.
def _fill_timing_verdict(
    payload: dict[str, Any], chosen: tuple[str, ...]
) -> dict[str, Any]:
    """Return the fill-timing trial's verdict fields for the conventions priced."""
    if payload.get("next_bar"):
        return {
            "verdict": (
                "NOT JUDGED: a --next-bar robustness run moves every bar-close fill "
                "to the next bar's open"
            ),
            "adopted": [],
            "criteria": {},
            "breakout_gate": "breakout_gate: not judged in a --next-bar run",
        }
    if set(CONVENTIONS) <= set(chosen):
        return verdict(payload)
    priced = [c for c in CONVENTIONS if c in chosen]
    return {
        "verdict": (
            f"NOT JUDGED: {len(priced)} of the {len(CONVENTIONS)} fill-timing "
            f"conventions priced ({', '.join(priced)})"
        ),
        "adopted": [],
        "criteria": {},
        "breakout_gate": "breakout_gate: not priced in this run",
    }


# The entry-level trial's registration as the payload records it: the
# conventions priced and how each fills, the control and the twin, the
# floors, the deflated best per window, and the first session any forecast
# exists. The verdict is merged in by `study`.
def _level_block(
    forecasts: Aligned, chosen: tuple[str, ...], level_best: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Return the payload's "level" block, before its verdict."""
    finite = np.isfinite(np.asarray(forecasts.forecast, dtype=float)).any(axis=1)
    first = str(forecasts.dates[np.argmax(finite)]) if finite.any() else None
    return {
        "plan": "docs/research/ml-entry-level-plan-2026-09-28.md",
        "conventions": [c for c in chosen if c in LEVELS],
        "control": LEVEL_CONTROL,
        "twin": LEVEL_TWIN,
        "levels": {
            c: {"rule": LEVELS[c].rule, "k": LEVELS[c].k, "source": LEVELS[c].source}
            for c in chosen
            if c in LEVELS
        },
        "constants": {
            "REPLACE_BP": REPLACE_BP,
            "REPLACE_T": REPLACE_T,
            "LEVEL_TRIALS": LEVEL_TRIALS,
            "HAC_LAG": HAC_LAG,
            "DIP": DIP,
        },
        "best": level_best,
        "first_forecast_session": first,
        "note": (
            "sigma = exp(F / 2), F the file's forecast of the next session's log "
            "realized variance, read from the decision session's row: an order "
            "decided at t's close fills in t + 1 and reads row t. trail_dip reads "
            "the file's trailing baseline on exactly the cells the forecast "
            "covers. A missing sigma fills as dip_or_close and is counted "
            "(sigma_fallbacks). Gains are against that session's official close, "
            "in bp, positive when better for the trader; the order fields are the "
            "median offset's orders filling in the window."
        ),
    }


# The convention whose excess over the control is largest on the window,
# with its deflated Sharpe against `trials` trials from the excess series'
# own moments. Candidates are the conventions `moments` holds (one trial's
# own), other than the control. The trial variance is the spread of the
# per-period excess Sharpes across the conventions scored; the control's
# own excess is identically zero and has no Sharpe, so it drops out of the
# spread. `versus` names the row fields read: "open" for the fill-timing
# trial against next_open, "dip" for the entry-level trial against
# dip_or_close.
def _best(
    rows: list[dict],
    window: str,
    moments: dict[str, candidate_stats.Moments],
    control: str = CONTROL,
    trials: int = TRIALS,
    versus: str = "open",
) -> dict[str, Any]:
    """Return the window's best convention against the control, deflated."""
    bp_key, t_key = f"mean_daily_bp_vs_{versus}", f"hac_t_vs_{versus}"
    candidates = [
        r
        for r in rows
        if r["window"] == window
        and r["convention"] in moments
        and r["convention"] != control
        and np.isfinite(r[bp_key])
    ]
    if not candidates:
        return {"convention": None, "deflated_sharpe": math.nan, "trials": trials}
    top = max(candidates, key=lambda r: r[bp_key])
    sharpes = np.array([m.sharpe for m in moments.values() if np.isfinite(m.sharpe)])
    variance = float(sharpes.var(ddof=1)) if len(sharpes) > 1 else 0.0
    mom = moments[top["convention"]]
    return {
        "convention": top["convention"],
        bp_key: top[bp_key],
        t_key: top[t_key],
        "excess_sharpe": mom.sharpe,
        "trial_variance": variance,
        "trials": trials,
        "deflated_sharpe": candidate_stats.deflated_sharpe(
            mom.sharpe, mom.length, mom.skew, mom.kurtosis, trials, variance
        ),
    }


# The plan's kill criteria on the payload's rows, and the separate
# statement about the band gate. Returns the fields `study` merges in.
# Only the fill-timing trial's own conventions are judged here; the level
# conventions have their own plan and `level_verdict`.
def verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return {"verdict", "adopted", "criteria", "breakout_gate"} for the payload."""
    rows = payload["rows"]

    def row(convention: str, window: str) -> dict | None:
        for r in rows:
            if r["convention"] == convention and r["window"] == window:
                return r
        return None

    adopted: list[str] = []
    criteria: dict[str, dict[str, Any]] = {}
    for c in payload["conventions"]:
        if c == payload.get("control", CONTROL) or c not in CONVENTIONS:
            continue
        choose = row(c, CHOOSING) or {}
        report = row(c, REPORTED) or {}
        bp = choose.get("mean_daily_bp_vs_open", math.nan)
        t = choose.get("hac_t_vs_open", math.nan)
        later = report.get("mean_daily_bp_vs_open", math.nan)
        passes_choosing = bool(
            np.isfinite(bp) and np.isfinite(t) and bp >= ADOPT_BP and t >= ADOPT_T
        )
        not_worse = bool(np.isfinite(later) and later >= 0.0)
        criteria[c] = {
            "choosing_bp": bp,
            "choosing_t": t,
            "reported_bp": later,
            "passes_choosing": passes_choosing,
            "not_worse_reported": not_worse,
        }
        if passes_choosing and not_worse:
            adopted.append(c)
    gate = row("breakout_gate", CHOOSING) or {}
    gate_bp = gate.get("mean_daily_bp_vs_open", math.nan)
    gate_t = gate.get("hac_t_vs_open", math.nan)
    if not np.isfinite(gate_bp):
        gate_line = (
            "breakout_gate vs next_open: not measured on the choosing window"
        )
    elif gate_bp < 0:
        gate_line = (
            f"breakout_gate loses to next_open on {CHOOSING} ({gate_bp:+.2f} "
            f"bp/session, t {gate_t:.2f}): the prior holds and the band gate is "
            f"removed from the /4 executor path as a separate, already-measured change"
        )
    else:
        gate_line = (
            f"breakout_gate does not lose to next_open on {CHOOSING} ({gate_bp:+.2f} "
            f"bp/session, t {gate_t:.2f}): the band gate stays until re-tested on "
            f"{REPORTED}"
        )
    if adopted:
        text = (
            f"{ADOPTED}: {', '.join(adopted)} beat next_open by at least "
            f"{ADOPT_BP:g} bp a session with t >= {ADOPT_T:g} on {CHOOSING} and are "
            f"not worse on {REPORTED}"
        )
    else:
        text = (
            f"{RECORDED}: no convention beats next_open by {ADOPT_BP:g} bp a session "
            f"with t >= {ADOPT_T:g} on {CHOOSING} while not worse on {REPORTED}"
        )
    return {
        "verdict": text,
        "adopted": adopted,
        "criteria": criteria,
        "breakout_gate": gate_line,
    }


# The entry-level plan's criteria on the payload's rows, fixed before the
# run. A level convention REPLACES the board's rule only when (1) it beats
# dip_or_close by REPLACE_BP a session with t >= REPLACE_T on the choosing
# window, (2) its paired difference against dip_or_close on the reported
# window is not negative, and (3) its paired difference against trail_dip
# on the choosing window is above zero. (1) and (2) without (3) is
# VOL_SCALING; so is trail_dip passing (1) and (2), since it cannot beat
# itself and the question is the model's. Anything else is RECORD. Also
# states the model against trailing volatility at the same rule
# (vol_dip_0.5 - trail_dip). Returns the fields `study` merges into the
# payload's "level" block.
def level_verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return {"verdict", "replaces", "criteria", "twin_line"} for the payload."""
    rows: list[dict[str, Any]] = payload["rows"]

    # The payload's row for a convention and window, empty when absent.
    def row(convention: str, window: str) -> dict[str, Any]:
        for r in rows:
            if r["convention"] == convention and r["window"] == window:
                return r
        return {}

    criteria: dict[str, dict[str, Any]] = {
        c: _level_criteria(c, row(c, CHOOSING), row(c, REPORTED))
        for c in payload["conventions"]
        if c in LEVELS
    }
    replaces = [c for c, v in criteria.items() if v["label"] == REPLACES]
    scaling = [c for c, v in criteria.items() if v["label"] == VOL_SCALING]
    if replaces:
        text = (
            f"{REPLACES}: {', '.join(replaces)} beat {LEVEL_CONTROL} by at least "
            f"{REPLACE_BP:g} bp a session with t >= {REPLACE_T:g} on {CHOOSING}, are "
            f"not worse on {REPORTED} and beat {LEVEL_TWIN}; the board's rule changes "
            f"only as a separate, registered change"
        )
    elif scaling:
        text = (
            f"{RECORD}: no model convention clears every criterion; vol-scaling, "
            f"not the model, clears the floors against {LEVEL_CONTROL}: "
            f"{', '.join(scaling)}"
        )
    else:
        text = (
            f"{RECORD}: no level convention beats {LEVEL_CONTROL} by {REPLACE_BP:g} bp "
            f"a session with t >= {REPLACE_T:g} on {CHOOSING} while not worse on "
            f"{REPORTED}; the board keeps {LEVEL_CONTROL}"
        )
    model, twin = "vol_dip_0.5", LEVEL_TWIN
    if model in payload["conventions"] and twin in payload["conventions"]:
        a, b = row(model, CHOOSING), row(model, REPORTED)
        twin_line = (
            f"the model against trailing volatility at the same rule ({model} - "
            f"{twin}): {_signed(a.get('mean_daily_bp_vs_twin'))} bp/session "
            f"(t {_signed(a.get('hac_t_vs_twin'))}) on {CHOOSING}, "
            f"{_signed(b.get('mean_daily_bp_vs_twin'))} "
            f"(t {_signed(b.get('hac_t_vs_twin'))}) on {REPORTED}"
        )
    else:
        twin_line = f"{model} against {twin}: not priced in this run"
    return {
        "verdict": text,
        "replaces": replaces,
        "criteria": criteria,
        "twin_line": twin_line,
    }


# One level convention against the plan's three criteria, from its rows on
# the choosing and reported windows, with the label they give: REPLACES
# when all three hold, VOL_SCALING when the floors and the reported window
# hold without the twin (always so for trail_dip), else RECORD. A missing
# number (NaN, or None as JSON writes it) passes nothing.
def _level_criteria(
    convention: str, choose: dict[str, Any], later_row: dict[str, Any]
) -> dict[str, Any]:
    """Return the criteria record, label included, for one level convention."""
    bp = choose.get("mean_daily_bp_vs_dip", math.nan)
    t = choose.get("hac_t_vs_dip", math.nan)
    later = later_row.get("mean_daily_bp_vs_dip", math.nan)
    is_twin = convention == LEVEL_TWIN
    twin_bp = math.nan if is_twin else choose.get("mean_daily_bp_vs_twin", math.nan)
    passes_choosing = bool(
        _finite(bp) and _finite(t) and bp >= REPLACE_BP and t >= REPLACE_T
    )
    not_worse = bool(_finite(later) and later >= 0.0)
    beats_twin = bool(not is_twin and _finite(twin_bp) and twin_bp > 0.0)
    label = RECORD
    if passes_choosing and not_worse:
        label = REPLACES if beats_twin else VOL_SCALING
    return {
        "label": label,
        "choosing_bp_vs_dip": bp,
        "choosing_t_vs_dip": t,
        "reported_bp_vs_dip": later,
        "choosing_bp_vs_twin": twin_bp,
        "passes_choosing": passes_choosing,
        "not_worse_reported": not_worse,
        "beats_twin": beats_twin,
    }


# The SR trial's registration as the payload records it: the conventions
# priced and the confluence each needs, the control, the floors, the level
# rule's constants, the deflated best per window, and per window the order
# fields of dip_or_close and each SR convention under their own names (the
# rows call a fill at a level a "dip" fill). The verdict is merged in by
# `study`.
def _sr_block(
    chosen: tuple[str, ...],
    sr_best: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the payload's "sr_level" block, before its verdict."""
    shown = [c for c in chosen if c == LEVEL_CONTROL or c in SR_CONVENTIONS]
    fills: dict[str, dict[str, dict[str, Any]]] = {c: {} for c in shown}
    for r in rows:
        if r["convention"] in fills:
            fills[r["convention"]][r["window"]] = {
                "orders": r.get("dip_orders", 0),
                "level_fills": r.get("dip_fills", 0),
                "level_fill_rate": r.get("dip_fill_rate", math.nan),
                "gain_bp_per_level_fill": r.get("gain_bp_per_dip_fill", math.nan),
                "gain_bp_per_order": r.get("gain_bp_per_order", math.nan),
            }
    return {
        "plan": SR_PLAN,
        "conventions": [c for c in chosen if c in SR_CONVENTIONS],
        "control": LEVEL_CONTROL,
        "min_confluence": {
            c: SR_MIN_CONFLUENCE[c] for c in chosen if c in SR_CONVENTIONS
        },
        "constants": {
            "REPLACE_BP": REPLACE_BP,
            "REPLACE_T": REPLACE_T,
            "SR_TRIALS": SR_TRIALS,
            "HAC_LAG": HAC_LAG,
            "FIRST_SLOT": sr_levels.FIRST_SLOT,
            "ATR_SHARE": sr_levels.ATR_SHARE,
            "ATR_SESSIONS": sr_levels.ATR_SESSIONS,
            "MIN_WIDTH": sr_levels.MIN_WIDTH,
            "LEVELS": list(sr_levels.KINDS),
        },
        "best": sr_best,
        "fills": fills,
        "note": (
            "A buy fills at the first bar close from slot 2 (10:15) inside the "
            "zone of a level below the prior bar's close while below the session "
            "open, else at the official close; sells mirror above the open. Zones "
            "are max(0.25 ATR14, 0.3% of the prior close) around 22 point-in-time "
            "levels on the fills' own adjusted basis. level_fill_rate is the share "
            "of the median offset's orders filled at a level before the close; "
            "gains are against that session's official close in bp, positive when "
            "better for the trader."
        ),
    }


# The SR plan's criteria on the payload's rows, fixed before the run: an SR
# convention REPLACES the board's rule only when it beats dip_or_close by
# REPLACE_BP a session with t >= REPLACE_T on the choosing window and its
# paired difference on the reported window is not negative. Anything else
# is RECORD. Returns the fields `study` merges into the "sr_level" block.
def sr_verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return {"verdict", "replaces", "criteria"} for the payload."""
    rows: list[dict[str, Any]] = payload["rows"]

    # The payload's row for a convention and window, empty when absent.
    def row(convention: str, window: str) -> dict[str, Any]:
        for r in rows:
            if r["convention"] == convention and r["window"] == window:
                return r
        return {}

    criteria = {
        c: _sr_criteria(row(c, CHOOSING), row(c, REPORTED))
        for c in payload["conventions"]
        if c in SR_CONVENTIONS
    }
    replaces = [c for c, v in criteria.items() if v["label"] == REPLACES]
    if replaces:
        text = (
            f"{REPLACES}: {', '.join(replaces)} beat {LEVEL_CONTROL} by at least "
            f"{REPLACE_BP:g} bp a session with t >= {REPLACE_T:g} on {CHOOSING} and "
            f"are not worse on {REPORTED}; the board's rule changes only as a "
            f"separate, registered change"
        )
    else:
        text = (
            f"{RECORD}: no level convention beats {LEVEL_CONTROL} by {REPLACE_BP:g} bp "
            f"a session with t >= {REPLACE_T:g} on {CHOOSING} while not worse on "
            f"{REPORTED}; the board keeps {LEVEL_CONTROL}"
        )
    return {"verdict": text, "replaces": replaces, "criteria": criteria}


# One SR convention against the plan's two criteria, from its rows on the
# choosing and reported windows: REPLACES when both hold, else RECORD. A
# missing number (NaN, or None as JSON writes it) passes nothing.
def _sr_criteria(choose: dict[str, Any], later_row: dict[str, Any]) -> dict[str, Any]:
    """Return the criteria record, label included, for one SR convention."""
    bp = choose.get("mean_daily_bp_vs_dip", math.nan)
    t = choose.get("hac_t_vs_dip", math.nan)
    later = later_row.get("mean_daily_bp_vs_dip", math.nan)
    passes_choosing = bool(
        _finite(bp) and _finite(t) and bp >= REPLACE_BP and t >= REPLACE_T
    )
    not_worse = bool(_finite(later) and later >= 0.0)
    return {
        "label": REPLACES if passes_choosing and not_worse else RECORD,
        "choosing_bp_vs_dip": bp,
        "choosing_t_vs_dip": t,
        "reported_bp_vs_dip": later,
        "passes_choosing": passes_choosing,
        "not_worse_reported": not_worse,
    }


# A signed number to two decimals for a verdict line, "n/a" when absent.
def _signed(x: Any) -> str:
    return f"{float(x):+.2f}" if _finite(x) else "n/a"


# The t statistic of the mean of `values` with its variance clustered by
# `clusters` (here: the fill session, so the orders of one day, which share
# that day's market move, count as one draw): the sandwich variance of a
# mean, sum over clusters of the squared sum of residuals over n^2, with the
# G / (G - 1) small-sample factor. NaN under two finite values or two
# clusters. One order per cluster is the ordinary t.
def clustered_t(values: np.ndarray, clusters: np.ndarray) -> float:
    """Return mean(values) / its cluster-robust standard error; NaN when undefined."""
    v = np.asarray(values, dtype=float)
    c = np.asarray(clusters)
    keep = np.isfinite(v)
    v, c = v[keep], c[keep]
    n = len(v)
    if n < 2:
        return math.nan
    _, group = np.unique(c, return_inverse=True)
    group = np.asarray(group).ravel()
    count = int(group.max()) + 1
    if count < 2:
        return math.nan
    residual = v - v.mean()
    sums = np.bincount(group, weights=residual, minlength=count)
    variance = count / (count - 1.0) * float(sums @ sums) / (n * n)
    if not variance > 0:
        return math.nan
    return float(v.mean() / math.sqrt(variance))


# A window bound as the payload writes it: the date, or None when unbounded.
def _day(bound: date | None) -> str | None:
    """Return `bound` as an ISO date string, None for None."""
    return str(bound) if bound is not None else None


# The T-I block's windows for a family whose first forecast session is
# `first`: the model window from it through 2023 (the plan's choosing
# window for a model decision), and 2016-2023 and 2024-2026 beside it.
def ti_windows(first: date | None) -> dict[str, tuple[date | None, date | None]]:
    """Return {window: (start, end)} of the T-I block."""
    return {
        TI_MODEL: (first, TI_MODEL_END),
        "2016-2023": WINDOWS["2016-2023"],
        "2024-2026": WINDOWS["2024-2026"],
    }


# A T-I window as a mask over the panel's sessions; the model window of a
# family with no forecast at all is empty rather than unbounded.
def _ti_keep(
    dates: np.ndarray, window: str, bounds: tuple[date | None, date | None]
) -> np.ndarray:
    """Return the (T,) session mask of one T-I window."""
    lo, hi = bounds
    if window == TI_MODEL and lo is None:
        return np.zeros(len(dates), dtype=bool)
    return _window(dates, lo, hi)


# What one convention's orders did inside a window, per side (all, buy,
# sell), from the median offset's order log: the orders, how many filled
# at a bar before the official close and that share, the mean gain over
# the session's official close per such fill and per order (an order
# filled at the close gains nothing), and the no-forecast and late-trigger
# counts.
def _ti_order_fields(
    log: OrderLog | None, keep: np.ndarray
) -> dict[str, dict[str, Any]]:
    """Return {side: order fields} for a waiting convention's log in the window."""
    out: dict[str, dict[str, Any]] = {}
    for side in ("all", "buy", "sell"):
        if log is None:
            out[side] = {
                "orders": 0,
                "filled_before_close": 0,
                "before_close_share": math.nan,
                "gain_bp_per_fill": math.nan,
                "gain_bp_per_order": math.nan,
                "no_forecast": 0,
                "late_triggers": 0,
            }
            continue
        inside = keep[log.session]
        if side != "all":
            inside = inside & (log.buy if side == "buy" else ~log.buy)
        orders = int(inside.sum())
        filled = log.hit & inside
        late = log.late if log.late is not None else np.zeros(len(inside), dtype=bool)
        out[side] = {
            "orders": orders,
            "filled_before_close": int(filled.sum()),
            "before_close_share": float(filled.sum() / orders) if orders else math.nan,
            "gain_bp_per_fill": _finite_mean(log.gain_bp[filled]),
            "gain_bp_per_order": _finite_mean(log.gain_bp[inside]),
            "no_forecast": int((log.no_sigma & inside).sum()),
            "late_triggers": int((late & inside).sum()),
        }
    return out


# Candidate minus control per order, per side, over the candidate's orders
# in the window at the median offset: each order's gain over the session's
# official close minus what the control's fill of the same (session, name,
# side) would have gained, in bp - so positive is a cheaper buy or a dearer
# sell than dip_or_close's. Read over the orders the two fill differently
# (the plan's "per order where the two differ"), with the t clustered by
# fill session, and over every order beside it.
def _ti_versus(
    log: OrderLog | None,
    candidate: FillPrices,
    control: FillPrices,
    keep: np.ndarray,
) -> dict[str, dict[str, Any]]:
    """Return {side: per-order difference fields} against the control's fills."""
    empty = {
        "orders": 0,
        "differing": 0,
        "differing_share": math.nan,
        "differing_sessions": 0,
        "bp_per_differing_order": math.nan,
        "clustered_t": math.nan,
        "bp_per_order": math.nan,
    }
    if (
        log is None
        or log.column is None
        or candidate.detail is None
        or control.detail is None
    ):
        return {side: dict(empty) for side in ("all", "buy", "sell")}
    s, j, buying = log.session, log.column, log.buy
    ours = np.where(buying, candidate.buy[s, j], candidate.sell[s, j])
    theirs = np.where(buying, control.buy[s, j], control.sell[s, j])
    gain = np.where(
        buying, candidate.detail.buy_gain_bp[s, j], candidate.detail.sell_gain_bp[s, j]
    )
    base = np.where(
        buying, control.detail.buy_gain_bp[s, j], control.detail.sell_gain_bp[s, j]
    )
    diff = gain - base
    valid = np.isfinite(diff) & np.isfinite(ours) & np.isfinite(theirs)
    differs = valid & (ours != theirs)
    out: dict[str, dict[str, Any]] = {}
    for side in ("all", "buy", "sell"):
        inside = keep[s] & valid
        if side != "all":
            inside = inside & (buying if side == "buy" else ~buying)
        chosen = inside & differs
        orders = int(inside.sum())
        out[side] = {
            "orders": orders,
            "differing": int(chosen.sum()),
            "differing_share": float(chosen.sum() / orders) if orders else math.nan,
            "differing_sessions": int(len(np.unique(s[chosen]))),
            "bp_per_differing_order": _finite_mean(diff[chosen]),
            "clustered_t": clustered_t(diff[chosen], s[chosen]),
            "bp_per_order": _finite_mean(diff[inside]),
        }
    return out


# One T-I convention's row on one window: at the median offset the paired
# daily difference against dip_or_close (bp, Newey-West t at the plan's
# lag) and the excess series' moments; across offsets the median CAGRs,
# the count of offsets above dip_or_close and the spread of the per-offset
# paired means; and the median offset's order fields, for the candidate,
# for the control, and candidate minus control per order.
def _ti_row(
    convention: str,
    window: str,
    bounds: tuple[date | None, date | None],
    keep: np.ndarray,
    priced: dict[str, list[Priced]],
    prices: dict[str, FillPrices],
    median: int,
    cost: float,
    next_bar: bool,
) -> dict[str, Any]:
    """Return the stage-3 T-I row of `convention` on `window`."""
    rule = TI_RULES[convention]
    at = priced[convention][median]
    base = priced[TI_CONTROL][median]
    diff = _excess(at.returns, base.returns, keep)
    mom = candidate_stats.moments(diff)
    ours = np.array([_cagr(p.returns[keep]) for p in priced[convention]])
    theirs = np.array([_cagr(p.returns[keep]) for p in priced[TI_CONTROL]])
    by_offset = np.array(
        [
            _finite_mean(_excess(a.returns, b.returns, keep)) * BP
            for a, b in zip(priced[convention], priced[TI_CONTROL], strict=True)
        ]
    )
    lo, hi = bounds
    finite_offsets = by_offset[np.isfinite(by_offset)]
    return {
        "convention": convention,
        "family": rule.family,
        "rule": rule.rule,
        "window": window,
        "start": str(lo) if lo is not None else None,
        "end": str(hi) if hi is not None else None,
        "cost_bps": cost,
        "next_bar": bool(next_bar),
        "sessions": int(len(diff)),
        "median_cagr": _nanmedian(ours),
        "control_median_cagr": _nanmedian(theirs),
        "median_cagr_vs_dip": _nanmedian(ours - theirs),
        "offsets_above_dip": int(np.nansum(ours > theirs)),
        "mean_daily_bp_vs_dip": float(diff.mean() * BP) if len(diff) else math.nan,
        "hac_t_vs_dip": candidate_stats.hac_t(diff, stage3_io.HAC_LAG)
        if len(diff) > 2
        else math.nan,
        "bp_vs_dip_across_offsets": {
            "offsets": int(len(finite_offsets)),
            "positive": int((finite_offsets > 0).sum()),
            "median": _nanmedian(by_offset),
            "min": float(finite_offsets.min()) if len(finite_offsets) else math.nan,
            "max": float(finite_offsets.max()) if len(finite_offsets) else math.nan,
        },
        "excess": {
            "sharpe": mom.sharpe,
            "skew": mom.skew,
            "kurtosis": mom.kurtosis,
            "length": mom.length,
        },
        "orders": _ti_order_fields(at.waits, keep),
        "control_orders": _ti_order_fields(base.waits, keep),
        "versus_control": _ti_versus(
            at.waits, prices[convention], prices[TI_CONTROL], keep
        ),
    }


# The payload's "stage3_ti" block: the conventions priced and their rules,
# the run's cost, fill mode and seed column, each family's forecast (file
# identity, coverage, first session) and windows, the rows per (convention,
# window), the deflated Sharpe of each model-window excess at N = 8 against
# the spread of the candidates priced here, and this run's reading of the
# floors. The REPLACES verdict reads several runs (`stage3_verdict`).
def _ti_block(
    panel: Panel,
    priced: dict[str, list[Priced]],
    prices: dict[str, FillPrices],
    chosen: tuple[str, ...],
    ti_forecasts: Mapping[str, TiForecast],
    offsets: int,
    median: int,
    cost: float,
    next_bar: bool,
) -> dict[str, Any]:
    """Return the payload's "stage3_ti" block."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    conventions = [c for c in chosen if c in TI_RULES]
    families: dict[str, dict[str, Any]] = {}
    windows: dict[str, dict[str, tuple[date | None, date | None]]] = {}
    for family, forecast in ti_forecasts.items():
        families[family] = {**forecast.identity, **ti_coverage(forecast.lookup)}
        windows[family] = ti_windows(ti_first_session(forecast.lookup))
    rows: list[dict[str, Any]] = []
    for c in conventions:
        for window, bounds in windows[TI_RULES[c].family].items():
            keep = _ti_keep(dates, window, bounds)
            rows.append(
                _ti_row(c, window, bounds, keep, priced, prices, median, cost, next_bar)
            )
    excess = {r["convention"]: r["excess"] for r in rows if r["window"] == TI_MODEL}
    seeds = {f.identity.get("seed_column") for f in ti_forecasts.values()}
    return {
        "plan": STAGE3_PLAN,
        "conventions": conventions,
        "control": TI_CONTROL,
        "rules": {
            c: {"family": TI_RULES[c].family, "rule": TI_RULES[c].rule}
            for c in conventions
        },
        "cost_bps": cost,
        "next_bar": bool(next_bar),
        "seed_column": next(iter(seeds)) if len(seeds) == 1 else None,
        "offsets": offsets,
        "median_offset": median,
        "hac_lag": stage3_io.HAC_LAG,
        "families": families,
        "windows": {
            family: {w: [_day(lo), _day(hi)] for w, (lo, hi) in spans.items()}
            for family, spans in windows.items()
        },
        "constants": {
            "DIP": DIP,
            "TI_SLOTS": stage3_io.TI_SLOTS,
            "FLOOR_BP": stage3_io.FLOOR_BP,
            "FLOOR_T": stage3_io.FLOOR_T,
            "HAC_LAG": stage3_io.HAC_LAG,
            "OUTER_CANDIDATES": stage3_io.OUTER_CANDIDATES,
            "DEFLATED_SHARPE_GATE": stage3_io.DEFLATED_SHARPE_GATE,
            "IMMATERIAL_BP_PER_ORDER": stage3_io.IMMATERIAL_BP_PER_ORDER,
            "IMMATERIAL_T": stage3_io.IMMATERIAL_T,
        },
        "rows": rows,
        "deflated": {c: stage3_verdict.deflated(excess, c) for c in excess},
        "reading": stage3_verdict.ti_reading(rows),
        "note": (
            "Candidates are paired against dip_or_close, the board's rule, on the same "
            "orders: the /4 policy's plain-simulator orders, filled from the SIP cube "
            "and marked at the panel's adjusted close. The model window runs from the "
            "family's first forecast session through 2023-12-29. Order fields are the "
            "median offset's orders filling in the window; gains are against that "
            "session's official close in bp, positive when better for the trader; "
            "versus_control is candidate minus dip_or_close on the same (session, "
            "name, side), its t clustered by fill session. A (name, session) with no "
            "forecast fills as dip_or_close (no_forecast); a filter trigger after "
            "15:30 fills as dip_or_close (late_triggers). deflated is this run's "
            "reading at N = 8 against the candidates priced here; the verdict "
            "(stage3_verdict.ti_verdict) reads the 10/16/25 bp runs, the next-bar run "
            "and five single-seed runs."
        ),
    }
