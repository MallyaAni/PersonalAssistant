"""Stage 5: buying at the decision day's close, decided at 15:30 - the engine.

`docs/research/stage5-plan-2026-09-29.md` registers everything here; the
timing audit (`docs/research/stage5-timing-audit-2026-09-29.md`, sections
3-5) built the proxy this module ports. Where the plan is silent the choice
is named below (**Choices**) and goes into the plan's addendum.

**The control.** Stage 4's control executor (`ew-redeploy`: the live
options plus the redeploy of idle cash) under `graded-equal-weight/5`
(`policy_v5.allocator(mask)`), from each of 20 start offsets, on the
executed basis (`stage4_orders.extract_orders`), read at the median offset.
Every buy fills by the board's `dip_or_close` in session t + 1
(`stage4_labels.name_fills`' control, adjusted by `cube_scale`).

**The candidate.** Every eligible buy is decided from the 15:30 proxy of
session t and fills at t's official close (the auction print, else the last
bar, times `fill_timing.session_scale`: that is `adj_close[t]`). Eligible:
reset buys, deferred retries, rotation buys, band entries and redeploy buys.
Not eligible (filling as the control): FOMC restorations (every buy of an
event decision), every buy on a 13:00 early-close session, and names with
no 15:15-15:30 bar. Sells are unchanged.

**The 15:30 proxy** (`proxy_grid`) keeps every row before t final and
replaces row t:

- the close of the 15:15-15:30 bar (slot 23), the high and low of slots
  0-23 with the day's open, each moved onto the panel's bases by that
  session's scale (the adjusted close, and the split-adjusted close, over the
  cube's official close); a name with no bar carries t - 1's close;
- the SIP volume through 15:15 (slots 0-22) times the name's trailing-20
  median of full-day over through-15:15 volume;
- filings strictly before t (`point_in_time_levels(strict_publication=True)`
  for the value analyst; the fundamental stance is already strict), and the
  release tone with a 15:30 acceptance cutoff (a release accepted in
  [15:30, 16:00) on its reaction day reacts one day later, `tone_cutoff`);
- the expectations gap at t - 1;
- one step of every stance's persistence from the final t - 1 state, the
  rotation gate and the grade rule (`grading.grade_stances`);
- the executor's band blocker and band z on the partial bar;
- then the planner on the control's own book at t (`plan_decision`).

The one step mirrors the analysts operation for operation, so with row t set
to the final row it reproduces the report exactly: the **null test**
(`null_check`, and `replay` against the control's journal), registered and
run before any fill is read.

**The comparison** (`account`), per (session, name), on the plans made at
15:30 and at 19:30 on the control's book at t:

- matched: the smaller of the two buys, the candidate fill against the
  control fill;
- missed: what the 19:30 decision wants beyond it, g = 0;
- extra: what the 15:30 decision buys beyond the 19:30 one, a round trip
  bought at t's close and sold in t + 1 by the board's sell rule
  (`dip_or_close` sell), charged `EXTRA_COST_BPS` each way.

**The statistics** (`summarize`): per eligible buy g = `stage4_labels.gain`
(control, candidate, "buy") times its matched share, the mean with its t
clustered by decision date; the book's session series (weight x g plus the
extra round trips' weight x P&L, bp of equity) with a Newey-West t at lag 20.
Windows by decision date: deciding 2016-01-04 to 2017-12-26, replication
2018-2023 and 2024-01-01 to the end. Reported beside them: the `next_open`
control, the 15:45 decision, the legs, the drift-adjusted reading and a full
ledger walk of the candidate executor (`walk`).

**The verdict** (`verdict`): PASS when the plan's criteria 1-4 all hold,
else RECORD.

**Choices** where the plan is silent (the addendum):

1. The sizes are compared on the submitted units of the two plans (the
   audit's section 4); the control's own execution ratio (executed over
   submitted units of the name, or of the whole decision for a name the
   19:30 plan does not buy) turns them into executed units, so a matched
   order's candidate part is its matched share of the executed order.
2. The per-buy g of a partly matched buy is its matched share times the
   gain of the candidate fill over the control fill (the missed part has
   g = 0); a fully missed eligible buy enters the mean at 0. A buy whose
   control or candidate fill cannot be priced (no cube session in t + 1)
   has g NaN: out of the mean and the t, zero in the session series,
   counted.
3. Extra round trips are not buys of the per-buy mean; they enter the
   session series and are reported on their own. An extra's P&L is
   1e4 ln(sell fill / t's close) - 2 x 25 bp.
4. The legs: a reset decision's buys are resets; a mid-cycle buy takes the
   leg of the planner's own funded order for the name, retry > band entry >
   rotation > redeploy when it has several; an event decision's buys are
   FOMC restorations.
5. `next_open` is the t + 1 cube's first-bar open times that session's scale
   (`fill_timing`'s `next_open`).
6. The drift adjustment subtracts the window's A/A+ drift (one session,
   `stage4_decisions.drift`) from each matched buy and each extra round
   trip, in proportion to its size.
7. Early closes are the calendar's published 13:00 sessions
   (`calendar.session_close`).
8. A name with no bar at t carries t - 1's close in the proxy row, with its
   high and low at that close and no volume (the audit's rule); its buys are
   not eligible, but it stays in the cross-section the ranks read. A
   through-15:15 volume ratio that is not finite and positive is skipped by
   the trailing median.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np

from backend.agents.trading.desk import (
    entry,
    grading,
    opinions,
    paper,
    point_in_time,
    policy_v5,
    regime,
    simulate,
)
from backend.agents.trading.desk import exit as exit_analyst
from backend.agents.trading.desk import sentiment as sentiment_analyst
from backend.agents.trading.desk import technical as technical_analyst
from backend.agents.trading.desk import value as value_analyst
from backend.agents.trading.desk.opinions import stances_from_ranks
from backend.cli.market_pit_scorecard import _since
from backend.market import (
    bands,
    baselines,
    calendar,
    candidate_stats,
    challenger,
    language,
    profit_taking,
    technical,
)
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market.fill_timing import clustered_t
from backend.market.midcycle_ew import EVENT, MIDCYCLE, REBALANCE
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.market.universe import AI_SIDE, SOFTWARE_SIDE

if TYPE_CHECKING:
    from backend.agents.trading.desk.desk import DeskReport

PLAN = "docs/research/stage5-plan-2026-09-29.md"
AUDIT = "docs/research/stage5-timing-audit-2026-09-29.md"
STUDY = "stage5_close"
POLICY = policy_v5.POLICY_VERSION
# The control executor and the cost its run is simulated at, as stage 4's.
CONTROL = so.CONTROL
COST_BPS = so.COST_BPS
# What an extra round trip pays, each way.
EXTRA_COST_BPS = 25.0
OFFSETS = 20
HAC_LAG = 20
BP = 1e4
# Criterion 1's floor on the deciding window's clustered t.
CRITERION_T = 2.0
PASS = "PASS"
RECORD = "RECORD"
# The plan's trial count: one registered variant, 451 -> 452.
TRIALS = {"registered_variants": 1, "cumulative": 452}


@dataclass(frozen=True)
class DecisionTime:
    """When the proxy decides: the bar it reads, its volume and its tone cutoff."""

    label: str
    # The bar whose close is the proxy's close (slot k starts 09:30 + 15k).
    slot: int
    # The last bar whose volume the free SIP plan serves by then.
    volume_slot: int
    # A release accepted at or after this, before 16:00, reacts a day later.
    tone_cutoff: time


# The registered decision (the 15:15-15:30 bar, SIP volume through 15:15)
# and the reported 15:45 variant (the 15:30-15:45 bar, volume through 15:30).
AT_1530 = DecisionTime("15:30", 23, 22, time(15, 30))
AT_1545 = DecisionTime("15:45", 24, 23, time(15, 45))
REGISTERED = AT_1530
VARIANT = AT_1545
# The windows, by decision date, end exclusive.
DECIDING = "deciding"
REPLICATION_A = "2018-2023"
REPLICATION_B = "2024-2026"
WINDOWS: dict[str, tuple[date | None, date | None]] = {
    DECIDING: (date(2016, 1, 4), date(2017, 12, 27)),
    REPLICATION_A: (date(2018, 1, 1), date(2024, 1, 1)),
    REPLICATION_B: (date(2024, 1, 1), None),
}
# The first session the proxy is built for (the deciding window's first).
PROXY_START = date(2016, 1, 4)
# Rows of history the one step needs before its session (the width rank's year).
MIN_HISTORY = bands.WIDTH_HISTORY
# The legs of a buy, and the priority when a name has several in one plan.
RESET = "reset"
RETRY = "retry"
ROTATION = "rotation"
BAND_ENTRY = "band_entry"
REDEPLOY = "redeploy"
FOMC = "fomc_restoration"
OTHER = "other"
UNREPLAYED = "not_replayed"
LEGS = (RESET, RETRY, ROTATION, BAND_ENTRY, REDEPLOY)
LEG_PRIORITY = (RETRY, BAND_ENTRY, ROTATION, REDEPLOY)
# The planner's own reason for each leg's buy orders, by prefix: the retry
# (`paper._deferred_orders`), the band entry (`paper._entry_orders`), the
# rotation's buys (`paper._rotation_orders`) and the redeploy
# (`simulate._redeploy_orders`).
LEG_REASONS = (
    ("deferred buy", RETRY),
    ("price entry", BAND_ENTRY),
    ("redeploying", ROTATION),
    ("redeploy:", REDEPLOY),
)
# Why a control buy is or is not eligible.
ELIGIBLE = "eligible"
NOT_EVENT = "fomc_restoration"
NOT_EARLY = "early_close"
NOT_BAR = "no_bar"
NOT_PROXY = "outside_proxy"
STATUSES = (ELIGIBLE, NOT_EVENT, NOT_EARLY, NOT_BAR, NOT_PROXY)
# The stances the proxy steps, and the grade's letters.
STEPPED = ("technical", "value", "rotation", "sentiment")
GRADE_C = grading.ORDINAL[grading.C]
GRADE_A = grading.ORDINAL[grading.A]

# The rules the one step mirrors; a change to any of them must change it too.
assert (opinions.PERSISTENCE, opinions.STANCE_FRACTION) == (3, 0.3)
assert technical_analyst.STRETCH_LEG == "band"
assert (
    regime.PARTICIPATION_SHORT,
    regime.PARTICIPATION_LONG,
    regime.ROTATION_SESSIONS,
    regime.HISTORY_SESSIONS,
) == (20, 250, 60, 500)
assert (bands.WINDOW, bands.SIGMA, bands.WIDTH_HISTORY) == (20, 2.0, 250)
assert (exit_analyst.NEAR_TOP, exit_analyst.WIDE, exit_analyst.UPPER_FIFTH) == (
    0.95,
    0.90,
    0.80,
)
assert FULL_SESSION_SLOTS == 26
assert CONTROL == profit_taking.CONTROL


# --- 1. the /5 control -------------------------------------------------------


class Journal(so.OrderJournal):
    """Stage 4's order journal that also keeps each decision's deferred units."""

    # Start empty, with the deferred units per decision session.
    def __init__(self) -> None:
        super().__init__()
        self.deferred_units: dict[int, dict[str, float]] = {}

    # Keep the decision as stage 4's journal does, and the units it defers
    # to the next decision's retry.
    def decision(
        self,
        session: Any,
        submitted_units: Any,
        desired_weights: Any,
        reason: Any,
        metadata: dict[str, Any] | None,
    ) -> int:
        handle = super().decision(
            session, submitted_units, desired_weights, reason, metadata
        )
        units = (metadata or {}).get("deferred_units") or {}
        self.deferred_units[int(session)] = {str(s): float(q) for s, q in units.items()}
        return handle


# Stage 4's control executor from `since` under `/5`: `simulate.run` on the
# restricted report with `profit_taking.control_options` and
# `policy_v5.allocator(mask)`, with a Journal; its orders on `basis`.
def run_control(
    restricted: DeskReport,
    mask: np.ndarray,
    since: date | None,
    cost_bps: float = COST_BPS,
    basis: str = so.EXECUTED,
) -> so.ControlRun:
    """Return the ControlRun of one offset under `/5`."""
    panel = restricted.panel
    options = profit_taking.control_options(panel)
    journal = Journal()
    journal.exposure = options.get("event_exposure")
    result = simulate.run(
        restricted,
        since=since,
        cost_bps=cost_bps,
        allocator=policy_v5.allocator(mask),
        journal=journal,
        **options,
    )
    orders = so.extract_orders(journal, restricted.graded.grades, basis)
    return so.ControlRun(
        since, orders, journal, np.asarray(result.returns, dtype=float)
    )


# The `/5` control from each of the first `offsets` sessions (the
# scorecard's start phases, as stage 4 ran them).
def run_offsets(
    restricted: DeskReport,
    mask: np.ndarray,
    offsets: int,
    cost_bps: float = COST_BPS,
    basis: str = so.EXECUTED,
    log: Callable[[str], None] | None = None,
) -> list[so.ControlRun]:
    """Return [ControlRun per offset]."""
    if offsets < 1:
        raise ValueError("offsets must be at least 1")
    out: list[so.ControlRun] = []
    for k in range(int(offsets)):
        run = run_control(
            restricted, mask, _since(restricted.panel, k), cost_bps, basis
        )
        out.append(run)
        if log is not None:
            log(
                f"  offset {k}: {len(run.orders)} orders "
                f"from session {run.orders.start}"
            )
    return out


# --- 2. the final history the one step reads ---------------------------------


@dataclass(frozen=True)
class Final:
    """The report's final (19:30) history, in the form the one step reads it."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    benchmark: int  # the benchmark's column
    sides: dict[str, str]
    is_ai: np.ndarray  # (N,) bool
    is_sw: np.ndarray  # (N,) bool
    side: np.ndarray  # (N,) +1 AI, -1 software, NaN otherwise (the rotation's sign)
    open: np.ndarray  # (T, N) split-adjusted, as the store's
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    adj: np.ndarray  # (T, N) adjusted close
    high_adj: np.ndarray  # (T, N) the high on the adjusted basis (`levels`)
    low_adj: np.ndarray
    e21_state: np.ndarray  # (T, N) the 21-session EMA's running state and count
    e21_count: np.ndarray
    e50_state: np.ndarray
    e50_count: np.ndarray
    e21: np.ndarray  # (T, N) `technical.ema(adj, 21)`
    week_end: np.ndarray  # (T,) bool: the backtest's week-end sessions
    week_index: np.ndarray  # (T,) the week-end's index among them, -1 elsewhere
    weekly_state: np.ndarray  # (W, N) the weekly 21 EMA's state and count
    weekly_count: np.ndarray
    w21: np.ndarray  # (T, N) `technical._weekly_ema(panel, adj, 21)`
    momentum: np.ndarray  # (T, N) residual momentum (reads no row t)
    cum_adj: np.ndarray  # (T + 1, N) the SMA's running sums and counts
    count_adj: np.ndarray
    width: np.ndarray  # (T, N) `bands.width(adj)`
    dollar: np.ndarray  # (T, N) log dollar volume (`regime.participation`)
    cai: np.ndarray  # (T + 1,) running sums of the AI and software residual
    csw: np.ndarray  # baskets and of the AI basket with the market
    cx: np.ndarray
    ai_part: np.ndarray  # (T,) the AI basket's participation
    raw: dict[str, np.ndarray]  # stepped analyst -> (T, N) raw stance
    held: dict[str, np.ndarray]  # -> (T, N) persisted stance (before the gate)
    runs: dict[str, np.ndarray]  # -> (T, N) the raw stance's run length
    resets: dict[str, np.ndarray | None]
    fundamental: np.ndarray  # (T, N) the fundamental stance, final
    gap: np.ndarray | None  # (T, N) the expectations gap, None without it
    grades: np.ndarray  # (T, N) the report's grades, unrestricted
    stances: dict[str, np.ndarray]  # the report's graded stances
    gate: np.ndarray  # (T,) bool: the rotation gated off
    technical_score: np.ndarray  # (T, N)
    value_score: np.ndarray  # (T, N)
    blocked: np.ndarray  # (T, N) the executor's band blocker
    z: np.ndarray  # (T, N) the band z (`entry.bollinger_z`)


# One EMA step as `technical.ema` takes it: a name's first known value
# starts the state, a known value moves it, an unknown one resets it.
def _ema_advance(
    state: np.ndarray, count: np.ndarray, x: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return the (state, count) after one row."""
    known = np.isfinite(x)
    fresh = known & ~np.isfinite(state)
    state = np.where(fresh, x, state)
    cont = known & ~fresh
    state = np.where(cont, alpha * x + (1 - alpha) * state, state)
    count = np.where(known, count + 1, 0)
    state = np.where(known, state, np.nan)
    return state, count


# The EMA's state and count after every row of `values`, (rows, N) each.
def _ema_states(values: np.ndarray, span: int) -> tuple[np.ndarray, np.ndarray]:
    """Return ((rows, N) states, (rows, N) counts) of `technical.ema`."""
    alpha = 2.0 / (span + 1.0)
    rows, cols = values.shape
    states = np.full((rows, cols), np.nan)
    counts = np.zeros((rows, cols), dtype=int)
    state = np.full(cols, np.nan)
    count = np.zeros(cols, dtype=int)
    for t in range(rows):
        state, count = _ema_advance(state, count, values[t], alpha)
        states[t] = state
        counts[t] = count
    return states, counts


# The EMA's output at one new row from the previous state: NaN until
# `span` known values in a row, as `technical.ema`.
def _ema_step(
    state: np.ndarray, count: np.ndarray, x: np.ndarray, span: int
) -> np.ndarray:
    """Return the (N,) EMA value after the row `x`."""
    state, count = _ema_advance(state, count, x, 2.0 / (span + 1.0))
    return np.where(count >= span, state, np.nan)


# The backtest's week-end sessions (`technical._weekly_ema`): a Friday, or
# a session whose next session starts a new week.
def week_ends(dates: np.ndarray) -> np.ndarray:
    """Return the (T,) week-end flags."""
    days = np.asarray(dates, dtype="datetime64[D]").astype(int)
    weeks = (days + 3) // 7
    friday = (days + 3) % 7 == 4
    rows = len(days)
    return np.array(
        [
            bool(friday[t]) or (t + 1 < rows and weeks[t + 1] != weeks[t])
            for t in range(rows)
        ],
        dtype=bool,
    )


# The run length of each raw stance as `opinions.persist` counts it,
# restarting on a reset.
def _runs(raw: np.ndarray, resets: np.ndarray | None) -> np.ndarray:
    """Return the (T, N) run lengths."""
    out = np.ones(raw.shape, dtype=int)
    for t in range(1, raw.shape[0]):
        out[t] = np.where(raw[t] == raw[t - 1], out[t - 1] + 1, 1)
        if resets is not None:
            out[t] = np.where(resets[t], 1, out[t])
    return out


# One row of stances from scores, as an analyst's `ranks` and
# `stances_from_ranks` make them.
def _stance_row(scores: np.ndarray) -> np.ndarray:
    """Return the (N,) raw stances of one row of scores."""
    ranks = baselines.percentile_rank(np.asarray(scores, dtype=float)[None, :])
    return stances_from_ranks(ranks, opinions.STANCE_FRACTION)[0]


# The final history of the desk's report - unrestricted: the grades the
# null test compares are the rule's own, and the planner restricts them
# to the book's members when it reads them - the panel's rows, the
# indicators' running states, the analysts' raw and persisted stances and
# the arrays the null test compares against. A signed rotation (a research
# arm the one step does not mirror) is refused.
def final_state(report: DeskReport) -> Final:
    """Return the report's Final."""
    if getattr(report.regime.rotation, "signed", False):
        raise ValueError("the one step mirrors the unsigned rotation of the desk")
    panel = report.panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    tickers = tuple(str(t) for t in panel.tickers)
    sides = {str(k): str(v) for k, v in report.sides.items()}
    is_ai = np.array([sides.get(t) == AI_SIDE for t in tickers], dtype=bool)
    is_sw = np.array([sides.get(t) == SOFTWARE_SIDE for t in tickers], dtype=bool)
    adj = np.asarray(panel.adj_close, dtype=float)
    close = np.asarray(panel.close, dtype=float)
    with np.errstate(all="ignore"):
        factor = np.where(close > 0, adj / close, np.nan)
        volume = np.where(panel.volume > 0, panel.volume, np.nan)
        dollar = np.log(volume * panel.close)
    e21_state, e21_count = _ema_states(adj, 21)
    e50_state, e50_count = _ema_states(adj, 50)
    ends = week_ends(dates)
    rows = np.flatnonzero(ends)
    weekly_state, weekly_count = _ema_states(adj[rows], 21)
    week_index = np.full(len(dates), -1, dtype=int)
    week_index[rows] = np.arange(len(rows))
    known = np.isfinite(adj)
    zero = np.zeros((1, adj.shape[1]))
    cum_adj = np.vstack([zero, np.cumsum(np.where(known, adj, 0.0), axis=0)])
    count_adj = np.vstack([zero, np.cumsum(known, axis=0)])
    bench = panel.benchmark_returns()
    bench = np.where(np.isfinite(bench), bench, 0.0)
    ai = regime.residual_basket(panel, is_ai)
    sw = regime.residual_basket(panel, is_sw)
    technical_opinion = report.opinions[technical_analyst.NAME]
    value_opinion = report.opinions[value_analyst.NAME]
    stepped = {
        "technical": technical_opinion,
        "value": value_opinion,
        "rotation": report.regime.rotation,
        "sentiment": report.opinions[sentiment_analyst.NAME],
    }
    raw = {
        name: stances_from_ranks(o.ranks(), opinions.STANCE_FRACTION)
        for name, o in stepped.items()
    }
    resets = {name: o.stance_resets for name, o in stepped.items()}
    gap = value_opinion.evidence.get("expectations_gap")
    blocked, z = signals(panel)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        width = bands.width(adj)
    return Final(
        dates=dates,
        tickers=tickers,
        benchmark=panel.index(panel.benchmark),
        sides=sides,
        is_ai=is_ai,
        is_sw=is_sw,
        side=np.where(is_ai, 1.0, np.where(is_sw, -1.0, np.nan)),
        open=np.asarray(panel.open, dtype=float),
        high=np.asarray(panel.high, dtype=float),
        low=np.asarray(panel.low, dtype=float),
        close=close,
        adj=adj,
        high_adj=panel.high * factor,
        low_adj=panel.low * factor,
        e21_state=e21_state,
        e21_count=e21_count,
        e50_state=e50_state,
        e50_count=e50_count,
        e21=technical.ema(adj, 21),
        week_end=ends,
        week_index=week_index,
        weekly_state=weekly_state,
        weekly_count=weekly_count,
        w21=technical._weekly_ema(panel, adj, 21),
        momentum=np.asarray(
            technical_opinion.evidence["residual_momentum_120"], dtype=float
        ),
        cum_adj=cum_adj,
        count_adj=count_adj,
        width=width,
        dollar=dollar,
        cai=np.concatenate([[0.0], np.cumsum(ai)]),
        csw=np.concatenate([[0.0], np.cumsum(sw)]),
        cx=np.concatenate([[0.0], np.cumsum(ai + bench)]),
        ai_part=np.array(
            [s.ai_participation for s in report.regime.states], dtype=float
        ),
        raw=raw,
        held={name: o.stances() for name, o in stepped.items()},
        runs={name: _runs(raw[name], resets[name]) for name in stepped},
        resets=resets,
        fundamental=np.asarray(report.graded.stances["fundamental"]),
        gap=None if gap is None else np.asarray(gap, dtype=float),
        grades=np.asarray(report.graded.grades),
        stances={k: np.asarray(v) for k, v in report.graded.stances.items()},
        gate=np.isnan(np.asarray(report.regime.rotation.scores, dtype=float)).all(
            axis=1
        ),
        technical_score=np.asarray(technical_opinion.scores, dtype=float),
        value_score=np.asarray(value_opinion.scores, dtype=float),
        blocked=np.asarray(blocked, dtype=bool),
        z=np.asarray(z, dtype=float),
    )


# --- 3. the intraday bars ------------------------------------------------------


@dataclass(frozen=True)
class Bars:
    """Every (session, name)'s intraday reading at one decision time, raw basis."""

    when: DecisionTime
    close: np.ndarray  # (T, N) the decision bar's close
    high: np.ndarray  # (T, N) the highest high of slots 0..slot
    low: np.ndarray  # (T, N) the lowest low of slots 0..slot
    volume: np.ndarray  # (T, N) the volume of slots 0..volume_slot
    official: np.ndarray  # (T, N) the official close (`session_scale`'s rule)
    have: np.ndarray  # (T, N) bool: a bar at the decision time
    ratio: np.ndarray  # (T, N) trailing-20 median of full-day over through volume


# A cube's official close per session by `fill_timing.session_scale`'s own
# rule: the auction print when finite and positive, else the last bar.
def official_close(cube: SessionCube) -> np.ndarray:
    """Return the (sessions,) official close on the raw basis."""
    auction = np.asarray(cube.auction_open, dtype=float)
    return np.where(
        np.isfinite(auction) & (auction > 0),
        auction,
        cube.close[:, FULL_SESSION_SLOTS - 1],
    )


# The trailing median of the full day's volume over the volume through the
# decision time, per name, over the `sessions` sessions before t (t
# excluded); a ratio that is not finite and positive is skipped.
def volume_ratio(
    volume: np.ndarray,
    close: np.ndarray,
    through: np.ndarray,
    official: np.ndarray,
    sessions: int = 20,
) -> np.ndarray:
    """Return the (T, N) ratios."""
    with np.errstate(all="ignore"):
        # The day's raw shares: the store's dollar volume over the raw close.
        ratio = (
            np.asarray(volume, float) * np.asarray(close, float) / official / through
        )
    ratio = np.where(np.isfinite(ratio) & (ratio > 0), ratio, np.nan)
    out = np.full(ratio.shape, np.nan)
    rows = ratio.shape[0]
    if rows <= sessions:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(ratio, sessions, axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        out[sessions:] = np.nanmedian(windows[: rows - sessions], axis=-1)
    return out


# The cubes' readings at one decision time on the panel's grid: the bar's
# close, the high and low through it, the volume through the volume slot
# and the official close; `have` where the bar, the official close and the
# panel's close all exist.
def bars(panel: Any, cubes: Mapping[str, SessionCube], when: DecisionTime) -> Bars:
    """Return the Bars of `when`."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    grids = {
        k: np.full(shape, np.nan)
        for k in ("close", "high", "low", "volume", "official")
    }
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(str(ticker))
        if cube is None or not len(cube):
            continue
        rows = lab.cube_rows(dates, cube)
        on = rows >= 0
        r = rows[on]
        grids["close"][on, j] = cube.close[r, when.slot]
        grids["high"][on, j] = cube.high[r, : when.slot + 1].max(axis=1)
        grids["low"][on, j] = cube.low[r, : when.slot + 1].min(axis=1)
        grids["volume"][on, j] = cube.volume[r, : when.volume_slot + 1].sum(axis=1)
        grids["official"][on, j] = official_close(cube)[r]
    adj = np.asarray(panel.adj_close, dtype=float)
    with np.errstate(invalid="ignore"):
        have = (
            np.isfinite(grids["close"])
            & np.isfinite(grids["official"])
            & (grids["official"] > 0)
            & np.isfinite(adj)
        )
    return Bars(
        when=when,
        have=have,
        ratio=volume_ratio(
            panel.volume, panel.close, grids["volume"], grids["official"]
        ),
        **grids,
    )


# The 13:00 early-close sessions of the calendar.
def early_closes(dates: np.ndarray) -> np.ndarray:
    """Return the (T,) flags of the published early closes."""
    days = np.asarray(dates, dtype="datetime64[D]")
    return np.array(
        [
            calendar.session_close(d.astype(object)) != calendar.REGULAR_CLOSE
            for d in days
        ],
        dtype=bool,
    )


# --- 4. the release tone at the decision time ---------------------------------


# Each ticker's release acceptance times by accession, from its EDGAR
# record's events.
def acceptance_times(records: Mapping[str, Any]) -> dict[str, dict[str, datetime]]:
    """Return {ticker: {accession: accepted}}."""
    return {
        str(ticker): {str(e.accession): e.accepted for e in record.events}
        for ticker, record in records.items()
    }


# A stored date as a `date`: a date, a datetime's day, or an ISO string's.
def _as_date(value: Any) -> date:
    """Return `value` as a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# How many tone records carry a known, zoned acceptance time (the cutoff
# can move only those), of how many.
def tone_coverage(
    records: Mapping[str, Sequence[language.ToneRecord]],
    acceptance: Mapping[str, Mapping[str, datetime]],
) -> dict[str, int]:
    """Return {"records", "with_time"}."""
    total = timed = 0
    for ticker, rows in records.items():
        accepted = acceptance.get(str(ticker), {})
        for record in rows:
            total += 1
            when = accepted.get(str(record.accession))
            timed += int(when is not None and when.tzinfo is not None)
    return {"records": total, "with_time": timed}


# The tone records as the desk would read them at `cutoff`: a release
# accepted at or after the cutoff and before the 16:00 close on its reaction
# day reacts one day later (`edgar`'s rule, with the cutoff for the close).
# A release without a known, zoned acceptance time is left as it is. Returns
# the records and one row per release moved.
def tone_cutoff(
    records: Mapping[str, Sequence[language.ToneRecord]],
    acceptance: Mapping[str, Mapping[str, datetime]],
    cutoff: time,
) -> tuple[dict[str, tuple[language.ToneRecord, ...]], list[dict[str, str]]]:
    """Return ({ticker: records}, [moved release])."""
    out: dict[str, tuple[language.ToneRecord, ...]] = {}
    moved: list[dict[str, str]] = []
    for ticker, rows in records.items():
        accepted = acceptance.get(str(ticker), {})
        kept = []
        for record in rows:
            when = accepted.get(str(record.accession))
            if when is not None and when.tzinfo is not None:
                local = when.astimezone(calendar.NEW_YORK)
                late = cutoff <= local.time() < calendar.REGULAR_CLOSE
                day = _as_date(record.reaction_date)
                if local.date() == day and late:
                    record = replace(record, reaction_date=day + timedelta(days=1))
                    moved.append(
                        {
                            "ticker": str(ticker),
                            "accession": str(record.accession),
                            "accepted": local.isoformat(),
                        }
                    )
            kept.append(record)
        out[str(ticker)] = tuple(kept)
    return out, moved


# The sentiment analyst's raw stances from tone records (`desk.run`'s
# `load_tone_features` then `sentiment.opine`).
def sentiment_raw(panel: Any, records: Mapping[str, Sequence[Any]]) -> np.ndarray:
    """Return the (T, N) raw sentiment stances."""
    tone = language.tone_features(panel, records)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        opinion = sentiment_analyst.opine(tone)
    return stances_from_ranks(opinion.ranks(), opinions.STANCE_FRACTION)


# --- 5. the one step -------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """Row t as the decision sees it."""

    adj: np.ndarray  # (N,) adjusted close
    close: np.ndarray  # (N,) split-adjusted close (the store's basis)
    high: np.ndarray  # (N,) split-adjusted high
    low: np.ndarray  # (N,) split-adjusted low
    dollar: np.ndarray  # (N,) log dollar volume
    have: np.ndarray  # (N,) bool: the decision time's bar exists


# Row t exactly as the report read it: the null test's row.
def final_row(final: Final, t: int) -> Row:
    """Return the final Row of session t."""
    return Row(
        adj=final.adj[t].copy(),
        close=final.close[t].copy(),
        high=final.high[t].copy(),
        low=final.low[t].copy(),
        dollar=final.dollar[t].copy(),
        have=np.isfinite(final.adj[t]),
    )


# Row t at the decision time: the bar's close and the high and low through
# it with the day's open, moved onto the panel's two bases by the
# session's scale; the volume through the volume slot times the trailing
# ratio. A name with no bar carries t - 1's close with no volume.
def intraday_row(final: Final, bars_: Bars, t: int) -> Row:
    """Return the proxy Row of session t."""
    have = bars_.have[t]
    c, off = bars_.close[t], bars_.official[t]
    with np.errstate(all="ignore"):
        adj = np.where(have, c * final.adj[t] / off, final.adj[t - 1])
        close = np.where(have, c * final.close[t] / off, final.close[t - 1])
        high = np.where(
            have, np.maximum(bars_.high[t] * final.close[t] / off, final.open[t]), close
        )
        low = np.where(
            have, np.minimum(bars_.low[t] * final.close[t] / off, final.open[t]), close
        )
        dollar = np.where(
            have & (bars_.volume[t] > 0),
            np.log(bars_.volume[t] * bars_.ratio[t] * c),
            np.nan,
        )
    return Row(adj, close, high, low, dollar, have.copy())


@dataclass(frozen=True)
class Step:
    """What the desk and the executor read at session t from one row."""

    raw: dict[str, np.ndarray]  # stepped analyst -> (N,) raw stance
    held: dict[str, np.ndarray]  # -> (N,) persisted stance; rotation after the gate
    gate: bool  # the rotation gated off
    grade: np.ndarray  # (N,) the grade, unrestricted
    blocked: np.ndarray  # (N,) the executor's band blocker
    z: np.ndarray  # (N,) the band z
    technical_score: np.ndarray
    value_score: np.ndarray
    ai_trend: float


# A residual basket return on one row, as `regime.residual_basket`: the
# mean of the known members' log returns less the market's; zero for an
# empty basket.
def _basket(returns: np.ndarray, mask: np.ndarray, bench: float) -> float:
    """Return the row's residual basket return."""
    if not mask.any():
        return 0.0
    block = returns[mask]
    known = np.isfinite(block)
    total = np.where(known, block, 0.0).sum()
    return float(total / max(int(known.sum()), 1) - bench)


# One stance's persistence at t from the final state at t - 1
# (`opinions.persist`, one iteration).
def _persist_step(final: Final, name: str, t: int, raw_now: np.ndarray) -> np.ndarray:
    """Return the (N,) persisted stance at t."""
    raw, run, held = final.raw[name], final.runs[name], final.held[name]
    resets = final.resets[name]
    run_now = np.where(raw_now == raw[t - 1], run[t - 1] + 1, 1)
    previous = held[t - 1]
    if resets is not None:
        run_now = np.where(resets[t], 1, run_now)
        previous = np.where(resets[t], opinions.NEUTRAL, previous)
    return np.where(run_now >= opinions.PERSISTENCE, raw_now, previous)


# Session t's grade, blocker and band z from row t and the final history
# before it: the regime's baskets, trend, spread and participation gate;
# the technical score (weekly and daily trend, momentum, and the range or
# the band fade by the AI trend); the value score at the row's close with
# `levels` and blended with `gap_row`; `sentiment_row` as given; one step
# of persistence each; the grade rule; the blocker and the band z.
def one_step(
    final: Final,
    t: int,
    row: Row,
    levels: Mapping[str, np.ndarray],
    gap_row: np.ndarray | None,
    sentiment_row: np.ndarray,
) -> Step:
    """Return the Step of session t."""
    if not MIN_HISTORY <= t < len(final.dates):
        raise ValueError(f"session {t} needs {MIN_HISTORY} rows of history")
    adj, ap, b = final.adj, row.adj, final.benchmark
    # The regime: the baskets' returns into t, the AI trend, the spread.
    with np.errstate(all="ignore"):
        returns = np.log(ap / adj[t - 1])
    returns = np.where(np.isfinite(returns), returns, np.nan)
    bench = float(returns[b]) if np.isfinite(returns[b]) else 0.0
    ai = _basket(returns, final.is_ai, bench)
    sw = _basket(returns, final.is_sw, bench)
    n = regime.ROTATION_SESSIONS
    ai_trend = float((final.cx[t] + (ai + bench)) - final.cx[t - n + 1])
    spread = float(
        ((final.cai[t] + ai) - final.cai[t - n + 1])
        - ((final.csw[t] + sw) - final.csw[t - n + 1])
    )
    # Participation, its percentile against the last two years, the gate.
    short, long_ = regime.PARTICIPATION_SHORT, regime.PARTICIPATION_LONG
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        recent = np.nanmean(
            np.vstack([final.dollar[t - short + 1 : t], row.dollar[None, :]]), axis=0
        )
        year = np.nanmean(
            np.vstack([final.dollar[t - long_ + 1 : t], row.dollar[None, :]]), axis=0
        )
        part = float(np.nanmedian(np.where(final.is_ai, recent - year, np.nan)))
    history = final.ai_part.copy()
    history[t] = part
    percentile = regime._trailing_percentile(history, t, regime.HISTORY_SESSIONS)
    confidence, _, _ = regime._judge(percentile, math.nan, math.nan, math.nan, False)
    gate = bool(confidence < 1.0)
    rotation = np.full(len(ap), np.nan) if gate else spread * final.side
    # The technical legs.
    e21 = _ema_step(final.e21_state[t - 1], final.e21_count[t - 1], ap, 21)
    e50 = _ema_step(final.e50_state[t - 1], final.e50_count[t - 1], ap, 50)
    if final.week_end[t]:
        k = int(final.week_index[t])
        state = final.weekly_state[k - 1] if k >= 1 else np.full(len(ap), np.nan)
        count = final.weekly_count[k - 1] if k >= 1 else np.zeros(len(ap), dtype=int)
        w21 = _ema_step(state, count, ap, 21)
    else:
        w21 = final.w21[t]
    window = bands.WINDOW
    piece = np.vstack([adj[t - window + 1 : t], ap[None, :]])
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        middle = np.nanmean(piece, axis=0)
        spread20 = np.nanstd(piece, axis=0)
        e21_slope = (e21 - final.e21[t - 5]) / np.abs(final.e21[t - 5])
        daily = np.where(
            (e21 > e50) & (e21_slope > 0),
            1.0,
            np.where((e21 < e50) & (e21_slope < 0), -1.0, 0.0),
        )
        daily = np.where(np.isfinite(e50), daily, np.nan)
        w_slope = (w21 - final.w21[t - 5]) / np.abs(final.w21[t - 5])
        weekly = np.where(
            (ap > w21) & (w_slope > 0),
            1.0,
            np.where((ap < w21) & (w_slope < 0), -1.0, 0.0),
        )
        weekly = np.where(np.isfinite(w_slope), weekly, np.nan)
        width = 2.0 * 2.0 * spread20
        position = (ap - (middle - 2.0 * spread20)) / width
        band = np.where(np.isfinite(width) & (width > 0), position, np.nan)
        factor = np.where(row.close > 0, ap / row.close, np.nan)
        high60 = np.nanmax(
            np.vstack([final.high_adj[t - 59 : t], (row.high * factor)[None, :]]),
            axis=0,
        )
        low60 = np.nanmin(
            np.vstack([final.low_adj[t - 59 : t], (row.low * factor)[None, :]]), axis=0
        )
        range60 = (ap - low60) / (high60 - low60)
    filled = technical_analyst._fill_with_the_most_stretched(band[None, :], ap[None, :])
    fade = -filled[0]
    fourth = range60 if (np.isfinite(ai_trend) and ai_trend > 0) else fade
    technical_score = baselines.rank_blend(
        weekly[None, :], daily[None, :], final.momentum[t][None, :], fourth[None, :]
    )[0].copy()
    technical_score[b] = np.nan
    # The value analyst at the row's close, blended with the gap.
    one: Any = SimpleNamespace(
        close=row.close[None, :], dates=final.dates[t : t + 1], tickers=final.tickers
    )
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        plain = value_analyst.opine(
            one, {k: np.asarray(v)[t : t + 1] for k, v in levels.items()}, final.sides
        )
        if gap_row is None:
            value_score = np.asarray(plain.scores[0], dtype=float)
        else:
            value_score = np.asarray(
                challenger.with_gap({"value": plain}, np.asarray(gap_row)[None, :])[
                    "value"
                ].scores[0],
                dtype=float,
            )
    raw = {
        "technical": _stance_row(technical_score),
        "value": _stance_row(value_score),
        "rotation": _stance_row(rotation),
        "sentiment": np.asarray(sentiment_row, dtype=int),
    }
    held = {name: _persist_step(final, name, t, raw[name]) for name in STEPPED}
    held["rotation"] = np.where(gate, 0, held["rotation"])
    grade = grading.grade_stances(
        final.fundamental[t][None, :],
        held["technical"][None, :],
        held["sentiment"][None, :],
        held["rotation"][None, :],
        held["value"][None, :],
        None,
        grading.ANALYST_WEIGHTS,
    ).grades[0]
    # The executor's band blocker (`exit.evidence(...).signalled()`).
    with np.errstate(all="ignore"):
        span = 2.0 * bands.SIGMA * spread20
        at = np.where(span > 0, (ap - (middle - bands.SIGMA * spread20)) / span, np.nan)
        width_now = np.where(middle > 0, 2.0 * bands.SIGMA * spread20 / middle, np.nan)
        past = final.width[t - bands.WIDTH_HISTORY : t]
        known = np.isfinite(past).sum(axis=0)
        below = (past < width_now).sum(axis=0)
        rank = np.where(
            np.isfinite(width_now) & (known >= bands.WIDTH_HISTORY // 2),
            below / np.maximum(known, 1),
            np.nan,
        )
        o, h, lo, c = final.open[t], row.high, row.low, row.close
        prev_o, prev_c = final.open[t - 1], final.close[t - 1]
        body = np.abs(c - o)
        rng = h - lo
        upper = h - np.maximum(o, c)
        lower = np.minimum(o, c) - lo
        star = (body <= 0.35 * rng) & (upper >= 2 * body) & (lower <= 0.25 * rng)
        engulf = (c < o) & (prev_c > prev_o) & (c <= prev_o) & (o >= prev_c)
        seen = np.isfinite(o) & np.isfinite(h) & np.isfinite(lo) & np.isfinite(c)
        seen_prev = seen & np.isfinite(prev_o) & np.isfinite(prev_c)
        bearish = (np.where(seen, star.astype(float), np.nan) > 0) | (
            np.where(seen_prev, engulf.astype(float), np.nan) > 0
        )
        bearish = np.where(np.isfinite(ap), bearish, False)
        blocked = ((at >= exit_analyst.NEAR_TOP) & bearish) | (
            (rank >= exit_analyst.WIDE) & (at >= exit_analyst.UPPER_FIFTH)
        )
        # The band z (`entry.bollinger_z`: the complete-window SMA, nanstd).
        now = np.isfinite(ap)
        first = t - window + 1
        count = (final.count_adj[t] + now) - final.count_adj[first]
        total = (final.cum_adj[t] + np.where(now, ap, 0.0)) - final.cum_adj[first]
        mean = np.where(count == window, total / window, np.nan)
        z = (ap - mean) / (2 * spread20)
    return Step(
        raw=raw,
        held=held,
        gate=gate,
        grade=np.asarray(grade, dtype=int),
        blocked=np.asarray(blocked, dtype=bool),
        z=np.asarray(z, dtype=float),
        technical_score=technical_score,
        value_score=value_score,
        ai_trend=ai_trend,
    )


@dataclass(frozen=True)
class Grid:
    """The one step at every proxy session on the panel's grid; final rows elsewhere."""

    mode: str  # "null", or the decision time's label
    start: int  # the first session stepped
    stop: int  # one past the last
    computed: np.ndarray  # (T,) bool
    adj: np.ndarray  # (T, N) the row's adjusted close
    have: np.ndarray  # (T, N) bool: the decision time's bar exists
    grade: np.ndarray  # (T, N) unrestricted
    blocked: np.ndarray
    z: np.ndarray
    gate: np.ndarray  # (T,)
    raw: dict[str, np.ndarray]
    held: dict[str, np.ndarray]
    technical_score: np.ndarray
    value_score: np.ndarray
    ai_trend: np.ndarray  # (T,)
    meta: dict[str, Any] = field(default_factory=dict)


# The one step at every session in [start, stop): `row_of(t)` gives the
# row, `gap_of(t)` the gap row (None without a gap), `sentiment` the (T, N)
# raw sentiment the rows read.
def run_grid(
    final: Final,
    mode: str,
    start: int,
    stop: int,
    row_of: Callable[[int], Row],
    levels: Mapping[str, np.ndarray],
    gap_of: Callable[[int], np.ndarray | None],
    sentiment: np.ndarray,
    meta: dict[str, Any] | None = None,
) -> Grid:
    """Return the Grid."""
    rows = len(final.dates)
    if start < MIN_HISTORY or stop > rows or start > stop:
        raise ValueError(f"cannot step sessions {start}..{stop} of {rows}")
    grade = final.grades.copy()
    blocked = final.blocked.copy()
    z = final.z.copy()
    adj = final.adj.copy()
    have = np.zeros(final.adj.shape, dtype=bool)
    gate = final.gate.copy()
    raw = {k: final.raw[k].copy() for k in STEPPED}
    held = {k: final.held[k].copy() for k in STEPPED}
    held["rotation"] = np.where(final.gate[:, None], 0, held["rotation"])
    technical_score = final.technical_score.copy()
    value_score = final.value_score.copy()
    ai_trend = np.full(rows, np.nan)
    computed = np.zeros(rows, dtype=bool)
    for t in range(start, stop):
        row = row_of(t)
        step = one_step(final, t, row, levels, gap_of(t), sentiment[t])
        adj[t] = row.adj
        have[t] = row.have
        grade[t] = step.grade
        blocked[t] = step.blocked
        z[t] = step.z
        gate[t] = step.gate
        for k in STEPPED:
            raw[k][t] = step.raw[k]
            held[k][t] = step.held[k]
        technical_score[t] = step.technical_score
        value_score[t] = step.value_score
        ai_trend[t] = step.ai_trend
        computed[t] = True
    return Grid(
        mode=mode,
        start=int(start),
        stop=int(stop),
        computed=computed,
        adj=adj,
        have=have,
        grade=grade,
        blocked=blocked,
        z=z,
        gate=gate,
        raw=raw,
        held=held,
        technical_score=technical_score,
        value_score=value_score,
        ai_trend=ai_trend,
        meta=dict(meta or {}),
    )


# The first session the proxy is built for - `start` (2016-01-04), or the
# first with MIN_HISTORY rows before it if that is later - and one past
# the last decision session (the last row has no next session to fill in).
def proxy_span(dates: np.ndarray, start: date = PROXY_START) -> tuple[int, int]:
    """Return (start row, stop row)."""
    days = np.asarray(dates, dtype="datetime64[D]")
    first = max(int(np.searchsorted(days, np.datetime64(start, "D"))), MIN_HISTORY)
    return min(first, max(len(days) - 1, 0)), max(len(days) - 1, 0)


# The null grid: row t is the final row, the value analyst reads the
# report's own levels, the gap at t, the sentiment `sentiment` (the tone as
# the report read it). It must reproduce the report exactly.
def null_grid(
    final: Final,
    levels: Mapping[str, np.ndarray],
    sentiment: np.ndarray,
    start: int,
    stop: int,
) -> Grid:
    """Return the null Grid."""
    return run_grid(
        final,
        "null",
        start,
        stop,
        lambda t: final_row(final, t),
        levels,
        lambda t: None if final.gap is None else final.gap[t],
        sentiment,
    )


# The proxy grid at a decision time: row t from the bars, the value
# analyst on levels filed strictly before t, the gap at t - 1, the
# sentiment with the decision time's tone cutoff.
def proxy_grid(
    final: Final,
    bars_: Bars,
    levels: Mapping[str, np.ndarray],
    sentiment: np.ndarray,
    start: int,
    stop: int,
    meta: dict[str, Any] | None = None,
) -> Grid:
    """Return the proxy Grid of `bars_.when`."""
    return run_grid(
        final,
        bars_.when.label,
        start,
        stop,
        lambda t: intraday_row(final, bars_, t),
        levels,
        lambda t: None if final.gap is None else final.gap[t - 1],
        sentiment,
        meta,
    )


# The cells of two arrays that differ, a NaN matching a NaN.
def _differs(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return the Boolean mask of differing cells."""
    a = np.asarray(a)
    b = np.asarray(b)
    if a.dtype.kind == "f" or b.dtype.kind == "f":
        a = a.astype(float)
        b = b.astype(float)
        return ~((a == b) | (np.isnan(a) & np.isnan(b)))
    return a != b


# The null test's first half: on every stepped session, the null grid's
# raw and persisted stances, gate, grades, blocker, band z and scores
# against the report's, cell for cell (a NaN must meet a NaN). Passes only
# when nothing differs.
def null_check(final: Final, grid: Grid) -> dict[str, Any]:
    """Return {"passes", "sessions", "mismatches", "max_abs_diff"}."""
    rows = grid.computed
    report_held = dict(final.stances)
    pairs: dict[str, tuple[np.ndarray, np.ndarray]] = {
        "grade": (grid.grade, final.grades),
        "blocked": (grid.blocked, final.blocked),
        "z": (grid.z, final.z),
        "technical_score": (grid.technical_score, final.technical_score),
        "value_score": (grid.value_score, final.value_score),
    }
    for name in STEPPED:
        pairs[f"raw_{name}"] = (grid.raw[name], final.raw[name])
        pairs[f"held_{name}"] = (grid.held[name], report_held[name])
    mismatches = {
        name: int(_differs(a[rows], b[rows]).sum()) for name, (a, b) in pairs.items()
    }
    mismatches["gate"] = int((grid.gate[rows] != final.gate[rows]).sum())
    largest: dict[str, float] = {}
    for name in ("z", "technical_score", "value_score"):
        a, b = pairs[name]
        with np.errstate(invalid="ignore"):
            diff = np.abs(a[rows].astype(float) - b[rows].astype(float))
        diff = diff[np.isfinite(diff)]
        largest[name] = float(diff.max()) if len(diff) else 0.0
    return {
        "passes": not any(mismatches.values()),
        "sessions": int(rows.sum()),
        "first": str(final.dates[grid.start]) if rows.any() else None,
        "last": str(final.dates[grid.stop - 1]) if rows.any() else None,
        "mismatches": mismatches,
        "max_abs_diff": largest,
    }


# --- 6. the planner at t ------------------------------------------------------


@dataclass(frozen=True)
class Planned:
    """One decision's plan: the units it wants held, each buy's leg, what it defers."""

    wanted: np.ndarray  # (N,) units the plan wants held after the fills
    legs: dict[int, str]  # column -> the leg of its buy (by LEG_PRIORITY)
    unfunded: dict[str, float]  # the buy units it defers to the next decision


# The leg of one of the planner's buy orders, by the reason it carries.
def leg_of(reason: str) -> str:
    """Return the leg named by `reason`, OTHER when none is."""
    for prefix, leg in LEG_REASONS:
        if str(reason).startswith(prefix):
            return leg
    return OTHER


# The leg of a name bought by several legs in one plan: retry, then band
# entry, then rotation, then redeploy (the audit's priority).
def pick_leg(legs: set[str]) -> str:
    """Return the name's leg."""
    for leg in LEG_PRIORITY:
        if leg in legs:
            return leg
    return OTHER


# The mid-cycle variant the control runs (`simulate.run` with
# `profit_taking.control_options`): breakout entries, no sweep, the
# redeploy at the options' buffer, rotation exits on; `today` and
# `at_rebalance` are the allocator's weights now and at the last reset.
def control_variant(
    options: Mapping[str, Any],
    today: dict[str, float],
    at_rebalance: dict[str, float],
) -> simulate.MidcycleVariant:
    """Return the control's MidcycleVariant."""
    if not options.get("midcycle_redeploy") or not options.get("live_midcycle"):
        raise ValueError("the control runs the live mid-cycle plan with the redeploy")
    return simulate.MidcycleVariant(
        options.get("midcycle_entries", simulate.MIDCYCLE_BREAKOUT),
        bool(options.get("midcycle_sweep", False)),
        float(options.get("redeploy_buffer", simulate.REDEPLOY_BUFFER)),
        bool(options.get("midcycle_exits", True)),
        today,
        at_rebalance,
    )


# The executor's plan at decision t on `book`, read from `report` (its
# grades and prices at row t), `blocked` and `bands_z` (the band blocker and
# z, row t), exactly as `simulate.run` makes it for the control: on a reset
# the allocator's targets, gated by the blocker and scaled by the event
# path, sized by the shared planner (the unpaid rest deferred); between
# resets the live mid-cycle plan (`simulate._live_midcycle` with the
# control's variant, retrying `carried`). The legs come from the planner's
# own funded orders; the plan they add up to must be `_live_midcycle`'s to
# the bit, or the attribution is refused.
def plan_decision(
    book: Any,
    report: Any,
    t: int,
    kind: str,
    carried: Mapping[str, float],
    at_rebalance: dict[str, float],
    blocked: np.ndarray,
    bands_z: np.ndarray,
    allocate: Callable[..., np.ndarray],
    options: Mapping[str, Any],
) -> Planned:
    """Return the Planned decision."""
    panel = report.panel
    tickers = list(panel.tickers)
    prices = panel.adj_close[t]
    if kind == REBALANCE:
        target = allocate(report, panel, None, t)
        total = book.equity(prices)
        weights = (
            (book.shares * prices) / total if total > 0 else np.zeros(len(tickers))
        )
        target = simulate._gated_targets(target, None, blocked, weights, t)
        ceiling = options.get("event_exposure")
        if ceiling is not None:
            target = target * float(ceiling[t])
        wanted = book.plan(target, prices)
        legs = {int(j): RESET for j in np.flatnonzero(wanted > book.shares)}
        return Planned(wanted, legs, simulate._unpaid_buys(book, wanted, prices))
    if kind != MIDCYCLE:
        raise ValueError(
            f"the planner makes reset and mid-cycle decisions, not {kind!r}"
        )
    today = simulate._weights_by_symbol(allocate(report, panel, None, t), tickers)
    variant = control_variant(options, today, at_rebalance)
    held_prices, held, grades, finished, excluded = simulate._paper_inputs(  # type: ignore[no-untyped-call]
        book, report, t, blocked
    )
    entries = {
        s: float(bands_z[t, j])
        for j, s in enumerate(tickers)
        if s != panel.benchmark and np.isfinite(bands_z[t, j])
    }
    equity = book.equity(prices)
    session = str(panel.dates[t])
    retry, _unpaid = paper._fund_buys(
        paper._deferred_orders(
            dict(carried),
            held,
            held_prices,
            equity,
            grades,
            finished,
            excluded,
            session,
            paper.PaperState(),
            whole_shares=False,
        ),
        book.cash,
        held_prices,
        whole_shares=False,
    )
    spent = sum(o.qty * held_prices[o.symbol] for o in retry)
    reserved = dict(held)
    for order in retry:
        reserved[order.symbol] = reserved.get(order.symbol, 0.0) + order.qty
    unfunded: dict[str, float] = {}
    planned = simulate._variant_midcycle_orders(
        session,
        equity,
        reserved,
        held_prices,
        grades,
        finished,
        entries,
        excluded,
        book.cash - spent,
        variant.entries,
        variant.sweep,
        variant.today,
        variant.at_rebalance,
        unfunded=unfunded,
        redeploy=variant.redeploy,
        exits=variant.exits,
    )
    wanted = book.shares.copy()
    bought: dict[int, set[str]] = {}
    for order in retry + planned:
        j = panel.index(order.symbol)
        wanted[j] += order.qty * (1 if order.side == "buy" else -1)
        if order.side == "buy" and order.qty > 0:
            bought.setdefault(j, set()).add(leg_of(order.reason))
    reference = simulate._live_midcycle(  # type: ignore[no-untyped-call]
        book,
        report,
        t,
        bands_z,
        blocked,
        deferred=dict(carried) or None,
        unfunded={},
        variant=variant,
    )
    if not np.array_equal(wanted, reference):
        raise ValueError(
            f"session {t}: the legs' orders do not add up to the executor's plan"
        )
    legs = {
        j: pick_leg(found) for j, found in bought.items() if wanted[j] > book.shares[j]
    }
    return Planned(wanted, legs, unfunded)


# The executor's own signals on the report's panel, as `simulate.run`
# reads them for the control: the band blocker (`block_overbought`) and the
# band z of the mid-cycle entries (`live_midcycle`).
def signals(panel: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return ((T, N) blocked, (T, N) band z)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        blocked = np.asarray(exit_analyst.evidence(panel).signalled(), dtype=bool)
        bands_z = np.asarray(entry.bollinger_z(panel.adj_close), dtype=float)
    return blocked, bands_z


class Swapped:
    """The restricted report, with row t of prices, grades, blocker and z swappable."""

    # Working copies of the arrays the planner reads (`given` holds the
    # executor's signals when already computed), and a report and a scratch
    # book that read them.
    def __init__(
        self,
        restricted: Any,
        mask: np.ndarray,
        cost_bps: float = COST_BPS,
        given: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> None:
        panel = restricted.panel
        blocked, bands_z = given if given is not None else signals(panel)
        self.mask = np.asarray(mask, dtype=bool)
        self.adj = np.array(panel.adj_close, dtype=float, copy=True)
        self.grades = np.array(restricted.graded.grades, copy=True)
        self.blocked = np.array(blocked, dtype=bool, copy=True)
        self.bands = np.array(bands_z, dtype=float, copy=True)
        self.panel = replace(panel, adj_close=self.adj)
        self.report = replace(
            restricted,
            panel=self.panel,
            graded=replace(restricted.graded, grades=self.grades),
        )
        self.book = simulate._Book(
            len(panel.tickers),
            simulate.START_EQUITY,
            cost_bps,
            self.panel,
            self.report,
            [str(d) for d in panel.dates],
        )
        self._saved: dict[int, tuple[np.ndarray, ...]] = {}

    # Put the grid's row t in place (the grade restricted to the members).
    def swap(self, t: int, grid: Grid) -> None:
        self._saved[t] = (
            self.adj[t].copy(),
            self.grades[t].copy(),
            self.blocked[t].copy(),
            self.bands[t].copy(),
        )
        self.adj[t] = grid.adj[t]
        self.grades[t] = np.where(self.mask[t], grid.grade[t], GRADE_C)
        self.blocked[t] = grid.blocked[t]
        self.bands[t] = grid.z[t]

    # Put the report's own row t back.
    def restore(self, t: int) -> None:
        adj, grades, blocked, z = self._saved.pop(t)
        self.adj[t], self.grades[t], self.blocked[t], self.bands[t] = (
            adj,
            grades,
            blocked,
            z,
        )

    # Plan decision t on the given book state with the grid's row t, then
    # put the report's row back.
    def plan(
        self,
        grid: Grid,
        t: int,
        kind: str,
        shares: np.ndarray,
        cash: float,
        carried: Mapping[str, float],
        at_rebalance: dict[str, float],
        allocate: Callable[..., np.ndarray],
        options: Mapping[str, Any],
    ) -> Planned:
        """Return the Planned decision."""
        self.book.shares = np.array(shares, dtype=float, copy=True)
        self.book.cash = float(cash)
        self.swap(t, grid)
        try:
            return plan_decision(
                self.book,
                self.report,
                t,
                kind,
                {} if kind == REBALANCE else carried,
                at_rebalance,
                self.blocked,
                self.bands,
                allocate,
                options,
            )
        finally:
            self.restore(t)


@dataclass(frozen=True)
class Replay:
    """One offset's decisions planned again on the control's own book at each t."""

    mode: str  # the grid's mode
    sessions: tuple[int, ...]  # the decision sessions planned
    wanted: dict[int, np.ndarray]  # session -> (N,) units the plan wants held
    legs: dict[int, dict[int, str]]  # session -> column -> leg of its buy
    checked: int  # sessions compared with the journal
    mismatched: tuple[int, ...]  # sessions whose plan differs from the journal's units
    max_abs_diff: float  # the largest difference from the journal's units
    skipped: dict[str, int]  # decisions not planned, by reason


# Plan every decision of one control run again, on the run's own book at t
# (the journal's mark before the decision), with row t of the report, the
# blocker and the band z replaced by the grid's (the grade restricted to
# the book's members): the executor's own planner, the run's deferred
# units carried between decisions, the allocator's weights at the last
# reset. Event decisions are the FOMC lifecycle, not the planner, and are
# skipped; so are sessions outside the grid and, when `early` is given,
# the early closes. With `compare`, each plan's units are held against the
# journal's submitted units (the null test: they must be equal). `given`
# holds the executor's signals (`signals`) when they are already computed.
def replay(
    run: so.ControlRun,
    restricted: Any,
    mask: np.ndarray,
    grid: Grid,
    early: np.ndarray | None = None,
    compare: bool = False,
    cost_bps: float = COST_BPS,
    given: tuple[np.ndarray, np.ndarray] | None = None,
) -> Replay:
    """Return the Replay of `run` under `grid`."""
    journal = run.journal
    if not isinstance(journal, Journal):
        raise ValueError(
            "a replay needs the run's stage-5 Journal (its deferred units)"
        )
    panel = restricted.panel
    tickers = list(panel.tickers)
    allocate = policy_v5.allocator(mask)
    options = profit_taking.control_options(panel)
    work = Swapped(restricted, mask, cost_bps, given)
    carried: dict[str, float] = {}
    at_rebalance: dict[str, float] = {}
    sessions: list[int] = []
    wanted: dict[int, np.ndarray] = {}
    legs: dict[int, dict[int, str]] = {}
    mismatched: list[int] = []
    largest = 0.0
    skipped = {"event": 0, "outside_grid": 0, "early_close": 0}
    for t in sorted(journal.submitted):
        kind = journal.kinds[t]
        if kind == EVENT:
            skipped["event"] += 1
            continue
        if kind == REBALANCE:
            at_rebalance = simulate._weights_by_symbol(
                allocate(restricted, panel, None, t), tickers
            )
        if not grid.computed[t]:
            skipped["outside_grid"] += 1
        elif early is not None and early[t]:
            skipped["early_close"] += 1
        else:
            cash, shares, _nav, _ = journal.marks[t]
            planned = work.plan(
                grid, t, kind, shares, cash, carried, at_rebalance, allocate, options
            )
            sessions.append(int(t))
            wanted[int(t)] = planned.wanted
            legs[int(t)] = planned.legs
            if compare:
                submitted = journal.submitted[t]
                diff = np.abs(planned.wanted - submitted)
                diff = diff[np.isfinite(diff)]
                largest = max(largest, float(diff.max()) if len(diff) else 0.0)
                if not np.array_equal(planned.wanted, submitted):
                    mismatched.append(int(t))
        carried = dict(journal.deferred_units.get(t, {}))
    return Replay(
        mode=grid.mode,
        sessions=tuple(sessions),
        wanted=wanted,
        legs=legs,
        checked=len(sessions) if compare else 0,
        mismatched=tuple(mismatched),
        max_abs_diff=largest,
        skipped=skipped,
    )


# The null test: the null grid reproduces the report (`null_check`) and,
# at every offset, the plans made from it reproduce the control journal's
# submitted units on every decision it steps.
def null_test(check: Mapping[str, Any], replays: Sequence[Replay]) -> dict[str, Any]:
    """Return {"passes", "report", "journal"}."""
    journal = [
        {
            "offset": k,
            "checked": r.checked,
            "mismatched": len(r.mismatched),
            "first_mismatches": list(r.mismatched[:5]),
            "max_abs_diff": r.max_abs_diff,
            "skipped": dict(r.skipped),
        }
        for k, r in enumerate(replays)
    ]
    ok = (
        bool(check.get("passes"))
        and all(r.checked > 0 and not r.mismatched for r in replays)
        and bool(replays)
    )
    return {"passes": ok, "report": dict(check), "journal": journal}


# --- 7. the fills ------------------------------------------------------------------


@dataclass(frozen=True)
class Fills:
    """The fills the comparison reads, on the panel's grid; row t is the decision."""

    candidate: np.ndarray  # (T, N) t's official close x its scale (adj_close[t])
    control_buy: np.ndarray  # (T, N) the board's dip_or_close buy in t + 1
    control_sell: np.ndarray  # (T, N) the board's dip_or_close sell in t + 1
    next_open: np.ndarray  # (T, N) t + 1's first-bar open x its scale
    coverage: dict[str, Any]


# Every name's fills on the panel's adjusted basis (`stage4_labels`): the
# candidate at t's official close, the control's dip_or_close in t + 1 for
# each side, and t + 1's opening print; NaN where a session has no cube.
def fill_grid(panel: Any, cubes: Mapping[str, SessionCube]) -> Fills:
    """Return the Fills."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    out = {
        k: np.full(shape, np.nan)
        for k in ("candidate", "control_buy", "control_sell", "next_open")
    }
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
        scale = lab.cube_scale(series, cube)
        rows = lab.cube_rows(dates, cube)
        on = rows >= 0
        out["candidate"][on, j] = official_close(cube)[rows[on]] * scale[on]
        fills = lab.name_fills(series, cube)
        out["control_buy"][:, j] = fills[(lab.CONTROL, "buy")].price
        out["control_sell"][:, j] = fills[(lab.CONTROL, "sell")].price
        ahead = np.full(len(dates), -1, dtype=np.int64)
        ahead[:-1] = rows[1:]
        next_scale = np.full(len(dates), np.nan)
        next_scale[:-1] = scale[1:]
        ok = ahead >= 0
        out["next_open"][ok, j] = cube.open[ahead[ok], 0] * next_scale[ok]
        covered.append(str(ticker))
    return Fills(
        coverage={
            "names_with_cube": len(covered),
            "names_without_cube": sorted(
                str(t) for t in panel.tickers if str(t) not in set(covered)
            ),
        },
        **out,
    )


# --- 8. matched, missed and extra -------------------------------------------------


@dataclass(frozen=True)
class Account:
    """One offset's executed control buys, the candidate's part of each, the extras."""

    when: str  # the decision time's label
    start: int  # the run's first decision session
    stop: int  # one past its last
    session: np.ndarray  # (K,) the decision session t of each executed buy
    column: np.ndarray  # (K,)
    ticker: np.ndarray  # (K,)
    weight: np.ndarray  # (K,) executed notional over equity at t
    kind: np.ndarray  # (K,) the Ledger's kind of the decision
    detail: np.ndarray  # (K,) stage 4's detail
    leg: np.ndarray  # (K,) the buy's leg
    status: np.ndarray  # (K,) ELIGIBLE or why not
    matched: np.ndarray  # (K,) the matched share of the order (0 unless eligible)
    cause: np.ndarray  # (K,) why the 15:30 plan bought less ("" when it matched)
    gain: np.ndarray  # (K,) the candidate fill's gain over dip_or_close, bp
    gain_next_open: np.ndarray  # (K,) the same over next_open
    g: np.ndarray  # (K,) matched share x gain: 0 when nothing matched, NaN unpriced
    g_next_open: np.ndarray  # (K,)
    extra_session: np.ndarray  # (X,) the extra round trips
    extra_column: np.ndarray
    extra_ticker: np.ndarray
    extra_weight: np.ndarray  # (X,) its notional over equity at t
    extra_leg: np.ndarray  # (X,) the 15:30 plan's leg for the name
    extra_cause: np.ndarray  # (X,)
    # (X,) bp of its notional, bought at t's close and sold in t + 1.
    extra_gross: np.ndarray
    extra_pnl: np.ndarray  # (X,) after EXTRA_COST_BPS each way
    decisions: int  # decision sessions the 15:30 plan was made on


# An extra round trip's gross return, bp of its notional: bought at `buy`
# (t's close), sold at `sell` (the board's sell rule in t + 1); NaN when
# either price is missing.
def round_trip_bp(buy: np.ndarray, sell: np.ndarray) -> np.ndarray:
    """Return 1e4 * ln(sell / buy)."""
    with np.errstate(all="ignore"):
        out = BP * np.log(np.asarray(sell, dtype=float) / np.asarray(buy, dtype=float))
    return np.where(np.isfinite(out), out, np.nan)


# Why the 15:30 plan and the 19:30 plan differ on a name at t, in the
# audit's order: the name's A/A+ status, then its blocker, then its band
# entry trigger, else the rest (the count, the cash, the trade floor).
def _cause(final: Grid, proxy: Grid, mask: np.ndarray, t: int, j: int) -> str:
    """Return "grade", "blocker", "band" or "other"."""
    a_final = bool(mask[t, j] and final.grade[t, j] >= GRADE_A)
    a_proxy = bool(mask[t, j] and proxy.grade[t, j] >= GRADE_A)
    if a_final != a_proxy:
        return "grade"
    if bool(final.blocked[t, j]) != bool(proxy.blocked[t, j]):
        return "blocker"
    with np.errstate(invalid="ignore"):
        fires = bool(final.z[t, j] >= paper.ENTRY_BAND_Z)
        fires_proxy = bool(proxy.z[t, j] >= paper.ENTRY_BAND_Z)
    if fires != fires_proxy:
        return "band"
    return "other"


# The comparison at one decision time for one offset. Per replayed
# decision t, on the control's book at t: the 19:30 plan's buy units (the
# journal's submitted units less the holdings), the 15:30 plan's, and the
# control's executed buys (the next mark less the holdings); the smaller
# of the two plans is matched, the 19:30 plan's rest missed, the 15:30
# plan's rest extra, each in executed units by the control's own execution
# ratio (Choice 1). Every executed control buy then gets its status, leg,
# matched share and gains; every extra its round trip. `null` is the
# null replay (the 19:30 plans' legs), `final_grid` the null grid (for
# the causes).
def account(
    run: so.ControlRun,
    restricted: Any,
    mask: np.ndarray,
    proxy: Grid,
    proxy_replay: Replay,
    null: Replay,
    final_grid: Grid,
    fills: Fills,
    early: np.ndarray,
) -> Account:
    """Return the Account of one offset at the proxy's decision time."""
    journal = run.journal
    orders = run.orders
    adj = np.asarray(restricted.panel.adj_close, dtype=float)
    replayed = set(proxy_replay.sessions)
    matched_units: dict[int, np.ndarray] = {}
    extras: list[tuple[int, int, float, str, str]] = []
    for t in proxy_replay.sessions:
        _, before, nav, _ = journal.marks[t]
        _, after, _, _ = journal.marks[t + 1]
        final_buy = np.maximum(journal.submitted[t] - before, 0.0)
        proxy_buy = np.maximum(proxy_replay.wanted[t] - before, 0.0)
        executed = np.maximum(after - before, 0.0)
        price = np.where(np.isfinite(adj[t]), adj[t], 0.0)
        wanted_value = float((final_buy * price).sum())
        overall = (
            float((executed * price).sum()) / wanted_value if wanted_value > 0 else 1.0
        )
        with np.errstate(all="ignore"):
            ratio = np.where(final_buy > 0, executed / final_buy, overall)
        bar = proxy.have[t]
        matched_units[t] = np.where(bar, np.minimum(final_buy, proxy_buy) * ratio, 0.0)
        extra = np.where(bar, np.maximum(proxy_buy - final_buy, 0.0) * ratio, 0.0)
        for j in np.flatnonzero(extra > 0):
            weight = float(extra[j] * adj[t, j] / nav) if nav > 0 else math.nan
            if not weight > so.DUST:
                continue
            leg = proxy_replay.legs.get(t, {}).get(int(j), OTHER)
            extras.append(
                (
                    int(t),
                    int(j),
                    weight,
                    leg,
                    _cause(final_grid, proxy, mask, t, int(j)),
                )
            )
    buys = np.flatnonzero(orders.side == "buy")
    session = orders.session[buys]
    column = orders.column[buys]
    count = len(buys)
    status = np.empty(count, dtype=object)
    leg = np.empty(count, dtype=object)
    cause = np.full(count, "", dtype=object)
    matched = np.zeros(count)
    for i, (t, j, kind) in enumerate(
        zip(session.tolist(), column.tolist(), orders.kind[buys].tolist(), strict=True)
    ):
        legs = null.legs.get(t)
        if kind == EVENT:
            status[i], leg[i] = NOT_EVENT, FOMC
            continue
        leg[i] = (
            legs.get(j, OTHER)
            if legs is not None
            else (RESET if kind == REBALANCE else UNREPLAYED)
        )
        if early[t]:
            status[i] = NOT_EARLY
        elif t not in replayed:
            status[i] = NOT_PROXY
        elif not proxy.have[t, j]:
            status[i] = NOT_BAR
        else:
            status[i] = ELIGIBLE
            executed = float(orders.executed[buys[i]])
            share = matched_units[t][j] / executed if executed > 0 else 0.0
            matched[i] = min(max(share, 0.0), 1.0)
            if matched[i] < 1.0 - 1e-12:
                cause[i] = _cause(final_grid, proxy, mask, t, j)
    gain = lab.gain(
        fills.control_buy[session, column], fills.candidate[session, column], "buy"
    )
    gain_open = lab.gain(
        fills.next_open[session, column], fills.candidate[session, column], "buy"
    )
    on = (status == ELIGIBLE) & (matched > 0)
    g = np.where(on, matched * gain, 0.0)
    g_open = np.where(on, matched * gain_open, 0.0)
    x_session = np.array([e[0] for e in extras], dtype=np.int64)
    x_column = np.array([e[1] for e in extras], dtype=np.int64)
    gross = round_trip_bp(
        fills.candidate[x_session, x_column], fills.control_sell[x_session, x_column]
    )
    return Account(
        when=proxy.mode,
        start=orders.start,
        stop=orders.stop,
        session=session,
        column=column,
        ticker=orders.ticker[buys],
        weight=orders.weight[buys],
        kind=orders.kind[buys],
        detail=orders.detail[buys],
        leg=leg.astype(str),
        status=status.astype(str),
        matched=matched,
        cause=cause.astype(str),
        gain=gain,
        gain_next_open=gain_open,
        g=g,
        g_next_open=g_open,
        extra_session=x_session,
        extra_column=x_column,
        extra_ticker=np.array(
            [str(restricted.panel.tickers[j]) for j in x_column.tolist()], dtype=str
        ),
        extra_weight=np.array([e[2] for e in extras], dtype=float),
        extra_leg=np.array([e[3] for e in extras], dtype=str),
        extra_cause=np.array([e[4] for e in extras], dtype=str),
        extra_gross=np.asarray(gross, dtype=float),
        extra_pnl=np.asarray(gross, dtype=float) - 2.0 * EXTRA_COST_BPS,
        decisions=len(proxy_replay.sessions),
    )


# --- 9. statistics -----------------------------------------------------------------


# The book's gain series over the run's decision sessions, bp of equity:
# per session the orders' weight x value plus the extras' weight x value,
# a missing value counting zero.
def book_series(
    acc: Account, values: np.ndarray, extra_values: np.ndarray
) -> np.ndarray:
    """Return the (stop - start,) series."""
    length = max(acc.stop - acc.start, 0)
    v = np.where(np.isfinite(values), values, 0.0)
    out = np.bincount(
        acc.session - acc.start, weights=acc.weight * v, minlength=length
    )[:length].astype(float)
    if len(acc.extra_session):
        x = np.where(np.isfinite(extra_values), extra_values, 0.0)
        out += np.bincount(
            acc.extra_session - acc.start,
            weights=acc.extra_weight * x,
            minlength=length,
        )[:length]
    return out


# A mean over finite values, NaN when there are none.
def _mean(x: np.ndarray) -> float:
    """Return the finite mean, NaN when empty."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else math.nan


# Per-buy statistics of `values` over the selected buys with a finite
# value: the count, the mean in bp with its t clustered by decision date,
# the notional-weighted mean, and the sessions they span.
def per_buy(
    values: np.ndarray, sessions: np.ndarray, weights: np.ndarray, keep: np.ndarray
) -> dict[str, Any]:
    """Return {"buys", "mean_bp", "t", "weighted_bp", "sessions"}."""
    keep = np.asarray(keep, dtype=bool) & np.isfinite(values)
    v, s, w = values[keep], sessions[keep], weights[keep]
    return {
        "buys": int(keep.sum()),
        "mean_bp": float(v.mean()) if len(v) else math.nan,
        "t": clustered_t(v, s) if len(v) else math.nan,
        "weighted_bp": float((w * v).sum() / w.sum())
        if len(v) and w.sum() > 0
        else math.nan,
        "sessions": int(len(np.unique(s))),
    }


# A session series' mean and Newey-West t at HAC_LAG.
def per_session(series: np.ndarray) -> dict[str, Any]:
    """Return {"sessions", "mean_bp", "hac_t"}."""
    n = len(series)
    return {
        "sessions": int(n),
        "mean_bp": float(series.mean()) if n else math.nan,
        "hac_t": candidate_stats.hac_t(series, HAC_LAG) if n > 2 else math.nan,
    }


# One window's reading of an Account: the control's buys and their
# statuses; the eligible buys' matched, partial and missed counts and
# notional; the per-buy g against dip_or_close and against next_open and
# drift-adjusted; the book's session series three ways; the extra round
# trips; and the per-buy g by leg. `mu_bp` is the window's A/A+ drift.
def summarize(
    acc: Account, dates: np.ndarray, lo: date | None, hi: date | None, mu_bp: float
) -> dict[str, Any]:
    """Return the statistics of one window."""
    run_dates = np.asarray(dates)[acc.start : acc.stop]
    inside = point_in_time.window(run_dates, lo, hi)
    order_in = (
        inside[acc.session - acc.start] if len(acc.session) else np.zeros(0, bool)
    )
    extra_in = (
        inside[acc.extra_session - acc.start]
        if len(acc.extra_session)
        else np.zeros(0, bool)
    )
    eligible = order_in & (acc.status == ELIGIBLE)
    mu = float(mu_bp) if math.isfinite(mu_bp) else math.nan
    # Without a drift (no A/A+ name-day in the window) the reading is
    # missing throughout, not the missed buys' zeros alone.
    drift_g = (
        np.where(acc.matched > 0, acc.g - mu * acc.matched, acc.g)
        if math.isfinite(mu)
        else np.full(len(acc.g), np.nan)
    )
    drift_pnl = acc.extra_pnl - mu
    series = book_series(acc, acc.g, acc.extra_pnl)[inside]
    open_series = book_series(acc, acc.g_next_open, acc.extra_pnl)[inside]
    drift_series = (
        book_series(acc, drift_g, drift_pnl)[inside]
        if math.isfinite(mu)
        else np.full(int(inside.sum()), np.nan)
    )
    weight = acc.weight
    notional = float(weight[eligible].sum())
    matched_notional = float((weight * acc.matched)[eligible].sum())
    extra_notional = float(acc.extra_weight[extra_in].sum())
    statuses = {s: int((order_in & (acc.status == s)).sum()) for s in STATUSES}
    priced = eligible & np.isfinite(acc.g)
    causes = [c for c in acc.cause[eligible & (acc.matched < 1.0 - 1e-12)]]
    return {
        "control_buys": int(order_in.sum()),
        "control_notional": float(weight[order_in].sum()),
        "status": statuses,
        "eligible": {
            "buys": int(eligible.sum()),
            "notional": notional,
            "matched": int((eligible & (acc.matched >= 1.0 - 1e-12)).sum()),
            "partial": int(
                (eligible & (acc.matched > 0) & (acc.matched < 1.0 - 1e-12)).sum()
            ),
            "missed": int((eligible & (acc.matched == 0)).sum()),
            "matched_share_of_notional": matched_notional / notional
            if notional > 0
            else math.nan,
            "unpriced": int((eligible & ~np.isfinite(acc.g)).sum()),
            "priced": int(priced.sum()),
            "causes": {
                c: causes.count(c) for c in ("grade", "blocker", "band", "other")
            },
        },
        "per_buy": per_buy(acc.g, acc.session, weight, eligible),
        "per_buy_next_open": per_buy(acc.g_next_open, acc.session, weight, eligible),
        "per_buy_drift": per_buy(drift_g, acc.session, weight, eligible),
        "matched_gain": per_buy(
            acc.gain, acc.session, weight, eligible & (acc.matched > 0)
        ),
        "session": per_session(series),
        "session_next_open": per_session(open_series),
        "session_drift": per_session(drift_series),
        "extras": {
            "count": int(extra_in.sum()),
            "notional": extra_notional,
            "share_of_eligible_notional": extra_notional / notional
            if notional > 0
            else math.nan,
            "gross_bp": _mean(acc.extra_gross[extra_in]),
            "pnl_bp": _mean(acc.extra_pnl[extra_in]),
            "pnl_t": clustered_t(acc.extra_pnl[extra_in], acc.extra_session[extra_in])
            if extra_in.sum() > 1
            else math.nan,
            "unpriced": int((extra_in & ~np.isfinite(acc.extra_pnl)).sum()),
            "by_leg": {
                leg: int((extra_in & (acc.extra_leg == leg)).sum())
                for leg in (*LEGS, OTHER)
                if (extra_in & (acc.extra_leg == leg)).any()
            },
            "causes": {
                c: int((extra_in & (acc.extra_cause == c)).sum())
                for c in ("grade", "blocker", "band", "other")
            },
        },
        "by_leg": {
            leg: per_buy(acc.g, acc.session, weight, eligible & (acc.leg == leg))
            for leg in LEGS
        },
        "drift_bp": mu,
    }


# The mean of a window's drift for the drift-adjusted reading: the A/A+
# name-days' mean one-session log return (`stage4_decisions.drift`).
def window_drift(restricted: Any, lo: date | None, hi: date | None) -> dict[str, Any]:
    """Return {"mu", "mu_bp", "name_days"}."""
    market: Any = SimpleNamespace(
        closes=np.asarray(restricted.panel.adj_close, dtype=float),
        dates=np.asarray(restricted.panel.dates, dtype="datetime64[D]"),
        grades=np.asarray(restricted.graded.grades),
    )
    return sd.drift(market, lo, hi)


# --- 10. the full ledger walk ------------------------------------------------------

# The control's options, which the walk mirrors one by one; any other
# option is refused rather than silently ignored.
WALK_OPTIONS = {
    "use_exits": False,
    "event_lifecycle": True,
    "block_overbought": True,
    "exit_at_close": True,
    "green_day_skip": True,
    "live_midcycle": True,
    "deferred_buys": True,
    "midcycle_redeploy": True,
}


@dataclass(frozen=True)
class Walk:
    """The control executor walked as an account, with or without buys at t's close."""

    since: date | None
    moc: bool  # whether the 15:30 plan's buys filled at t's close
    start: int
    returns: np.ndarray  # (T - start,) daily returns, as `SimResult.returns`
    equity: np.ndarray  # (T - start,)
    fills: int  # names bought at t's close
    notional: float  # their notional over equity at t, summed
    unwanted: int  # of those, names the 19:30 plan did not buy (kept to the rules)


# The control executor as `simulate.run` walks it under the control's
# options (`profit_taking.control_options`, `/5`), line for line - the FOMC
# lifecycle, the reset with the band gate, the live mid-cycle plan with the
# redeploy and the retry of deferred buys, buys at t + 1's open and sells
# at its close with the green-day skip - plus, with `moc`, the candidate
# executor: on every session the grid steps (not an early close, not in
# the FOMC lifecycle), the 15:30 plan on the book at t buys at t's close
# (`adj_close[t]`, the official close) the names with a bar, from the cash
# after t's closing sells, before the 19:30 plan fills. The 19:30 plan is
# the control's on the book before those buys; its buys count what was
# bought at the close, its sells include it, and a name bought at the close
# that the 19:30 plan does not buy is kept to the executor's own rules.
# Without `moc` the walk is the control run itself, to the bit. `given`
# holds the executor's signals (`signals`) when they are already computed.
def walk(
    restricted: Any,
    mask: np.ndarray,
    since: date | None,
    grid: Grid,
    early: np.ndarray,
    cost_bps: float = COST_BPS,
    moc: bool = True,
    given: tuple[np.ndarray, np.ndarray] | None = None,
) -> Walk:
    """Return the Walk from `since`."""
    panel = restricted.panel
    options = profit_taking.control_options(panel)
    expected = set(WALK_OPTIONS) | {"rebalance", "event_exposure", "redeploy_buffer"}
    if set(options) != expected or any(
        options[k] != v for k, v in WALK_OPTIONS.items()
    ):
        raise ValueError(
            f"the walk mirrors the control's options, not {sorted(options)}"
        )
    allocate = policy_v5.allocator(mask)
    rows, names = panel.adj_close.shape
    tickers = list(panel.tickers)
    event_exposure = simulate._event_path(options["event_exposure"], rows)
    blocked, live_bands = given if given is not None else signals(panel)
    every = int(options["rebalance"])
    start = int(np.searchsorted(panel.dates, np.datetime64(since))) if since else 0
    opens = simulate.adjusted_open(panel)
    closes = panel.adj_close
    book = simulate._Book(
        names,
        simulate.START_EQUITY,
        cost_bps,
        panel,
        restricted,
        [str(d) for d in panel.dates],
    )
    work = Swapped(restricted, mask, cost_bps, (blocked, live_bands)) if moc else None
    returns = np.full(rows, np.nan)
    equity = np.full(rows, np.nan)
    equity[start] = book.equity(closes[start])
    previous_scale = 1.0
    baseline = sold = None
    pending: dict[str, float] = {}
    at_rebalance: dict[str, float] = {}
    next_rebalance = start
    fills = unwanted = 0
    notional = 0.0
    for t in range(start, rows - 1):
        scale = float(event_exposure[t]) if event_exposure is not None else 1.0
        if scale < 1 or baseline is not None:
            baseline, sold = simulate._settle_event(  # type: ignore[no-untyped-call]
                book, baseline, sold, scale, opens[t + 1], t + 1
            )
            equity[t + 1] = book.equity(closes[t + 1])
            returns[t + 1] = equity[t + 1] / equity[t] - 1 if equity[t] > 0 else np.nan
            continue
        rebalanced = t >= next_rebalance
        if rebalanced:
            next_rebalance = t + every
            target = allocate(restricted, panel, None, t)
            at_rebalance = simulate._weights_by_symbol(target, tickers)
            total = book.equity(closes[t])
            weights = (
                (book.shares * closes[t]) / total if total > 0 else np.zeros(names)
            )
            target = simulate._gated_targets(target, None, blocked, weights, t)
            reason = "rebalanced out"
        else:
            target, reason = book.between(
                None, closes[t], t, simulate.REDEPLOY, exit_analyst.GRACE, None, 1.0
            )
        target, previous_scale, reason, changed = simulate._event_target(  # type: ignore[no-untyped-call]
            target, event_exposure, t, rebalanced, previous_scale, reason, "FOMC"
        )
        if changed:
            raise ValueError(f"session {t}: an event change outside the FOMC lifecycle")
        order = book.plan(target, closes[t])
        carried = {} if rebalanced else pending
        if rebalanced:
            pending = simulate._unpaid_buys(book, order, closes[t])
        else:
            unfunded: dict[str, float] = {}
            variant = control_variant(
                options,
                simulate._weights_by_symbol(
                    allocate(restricted, panel, None, t), tickers
                ),
                at_rebalance,
            )
            order = simulate._live_midcycle(  # type: ignore[no-untyped-call]
                book,
                restricted,
                t,
                live_bands,
                blocked,
                deferred=carried or None,
                unfunded=unfunded,
                variant=variant,
            )
            pending = unfunded
        if work is not None and grid.computed[t] and not early[t]:
            before = book.shares.copy()
            planned = work.plan(
                grid,
                t,
                REBALANCE if rebalanced else MIDCYCLE,
                before,
                book.cash,
                carried,
                at_rebalance,
                allocate,
                options,
            )
            buy = np.where(grid.have[t], np.maximum(planned.wanted - before, 0.0), 0.0)
            if (buy > 0).any():
                nav = book.equity(closes[t])
                book._fill(before + buy, closes[t], session=t, phase="close")
                bought = np.maximum(book.shares - before, 0.0)
                fills += int((bought > 0).sum())
                notional += (
                    float((bought * np.nan_to_num(closes[t])).sum() / nav)
                    if nav > 0
                    else 0.0
                )
                unwanted += int(((bought > 0) & (order <= before)).sum())
                order = np.where(order < before, order, np.maximum(order, book.shares))
        up_at_open = (
            (opens[t + 1] > closes[t])
            & np.isfinite(opens[t + 1])
            & np.isfinite(closes[t])
        )
        skip = (order < book.shares) & up_at_open
        order = np.where(skip, book.shares, order)
        book.settle_split(
            order, opens[t + 1], closes[t + 1], t + 1, reason, sell_at_close=True
        )
        equity[t + 1] = book.equity(closes[t + 1])
        returns[t + 1] = (
            equity[t + 1] / equity[t] - 1.0 if equity[t] > 0 else float("nan")
        )
    return Walk(
        since=since,
        moc=bool(moc),
        start=start,
        returns=returns[start:],
        equity=equity[start:],
        fills=fills,
        notional=notional,
        unwanted=unwanted,
    )


# The walk's reading per window (by the return's session): the candidate
# walk's daily excess over the control walk in bp with its Newey-West t,
# and each walk's compounded annual return; plus whether the control walk
# is the simulator's control run to the bit.
def walk_reading(
    control: Walk,
    candidate: Walk,
    reference: np.ndarray,
    dates: np.ndarray,
    spans: Mapping[str, tuple[date | None, date | None]],
) -> dict[str, Any]:
    """Return the walk block of the payload."""
    days = np.asarray(dates, dtype="datetime64[D]")[control.start :]
    excess = (candidate.returns - control.returns) * BP
    out: dict[str, Any] = {
        "control_is_the_simulator": bool(
            np.array_equal(control.returns, np.asarray(reference), equal_nan=True)
        ),
        "fills_at_the_close": candidate.fills,
        "notional_at_the_close": candidate.notional,
        "unwanted_at_19_30": candidate.unwanted,
        "windows": {},
    }
    for w, (lo, hi) in spans.items():
        keep = point_in_time.window(days, lo, hi) & np.isfinite(excess)
        series = excess[keep]
        out["windows"][w] = {
            **per_session(series),
            "control_cagr": _cagr(control.returns[keep]),
            "candidate_cagr": _cagr(candidate.returns[keep]),
        }
    return out


# The compounded annual return of a daily series (252 sessions a year).
def _cagr(daily: np.ndarray) -> float:
    """Return the CAGR, NaN when empty."""
    daily = np.asarray(daily, dtype=float)
    daily = daily[np.isfinite(daily)]
    if not len(daily):
        return math.nan
    return float(np.prod(1.0 + daily) ** (252.0 / len(daily)) - 1.0)


# --- 11. the whole test ----------------------------------------------------------


# The median offset's rows for the payload: every executed control buy
# with its status, leg, matched share and gains, and every extra round trip.
def account_rows(acc: Account, dates: np.ndarray) -> dict[str, list[dict[str, Any]]]:
    """Return {"buys": [...], "extras": [...]}."""
    days = np.asarray(dates, dtype="datetime64[D]")
    buys = [
        {
            "date": str(days[t]),
            "ticker": str(acc.ticker[i]),
            "kind": str(acc.kind[i]),
            "detail": str(acc.detail[i]),
            "leg": str(acc.leg[i]),
            "status": str(acc.status[i]),
            "weight": float(acc.weight[i]),
            "matched": float(acc.matched[i]),
            "cause": str(acc.cause[i]),
            "gain_bp": float(acc.gain[i]),
            "gain_next_open_bp": float(acc.gain_next_open[i]),
            "g_bp": float(acc.g[i]),
        }
        for i, t in enumerate(acc.session.tolist())
    ]
    extras = [
        {
            "date": str(days[t]),
            "ticker": str(acc.extra_ticker[i]),
            "leg": str(acc.extra_leg[i]),
            "cause": str(acc.extra_cause[i]),
            "weight": float(acc.extra_weight[i]),
            "gross_bp": float(acc.extra_gross[i]),
            "pnl_bp": float(acc.extra_pnl[i]),
        }
        for i, t in enumerate(acc.extra_session.tolist())
    ]
    return {"buys": buys, "extras": extras}


@dataclass(frozen=True)
class Context:
    """What every offset's comparison reads besides its own run."""

    restricted: Any  # the point-in-time report the control ran on
    mask: np.ndarray  # (T, N) the book's membership
    final_grid: Grid  # the null grid: the 19:30 inputs (for the causes)
    fills: Fills
    early: np.ndarray  # (T,) the early closes
    cost_bps: float = COST_BPS
    given: tuple[np.ndarray, np.ndarray] | None = None  # the executor's signals


# One offset's comparison at a grid's decision time: its decisions planned
# again under the grid on the control's book, then the Account.
def compare(run: so.ControlRun, null: Replay, grid: Grid, context: Context) -> Account:
    """Return the Account of `run` at the grid's decision time."""
    planned = replay(
        run,
        context.restricted,
        context.mask,
        grid,
        context.early,
        cost_bps=context.cost_bps,
        given=context.given,
    )
    return account(
        run,
        context.restricted,
        context.mask,
        grid,
        planned,
        null,
        context.final_grid,
        context.fills,
        context.early,
    )


# Every offset's comparison at the registered time, read per window (the
# per-buy mean and t, the session mean, the next_open per-buy mean);
# returns those readings and the median offset's Account.
def _per_offset(
    runs: Sequence[so.ControlRun],
    null_replays: Sequence[Replay],
    grid: Grid,
    context: Context,
    spans: Mapping[str, tuple[date | None, date | None]],
    mus: Mapping[str, float],
    log: Callable[[str], None] | None,
) -> tuple[dict[str, dict[str, list[float]]], Account]:
    """Return ({window: {reading: [per offset]}}, the median offset's Account)."""
    dates = np.asarray(context.restricted.panel.dates, dtype="datetime64[D]")
    median = len(runs) // 2
    readings: dict[str, dict[str, list[float]]] = {
        w: {"per_buy_bp": [], "per_buy_t": [], "session_bp": [], "next_open_bp": []}
        for w in spans
    }
    chosen: Account | None = None
    for k, run in enumerate(runs):
        acc = compare(run, null_replays[k], grid, context)
        for w, (lo, hi) in spans.items():
            s = summarize(acc, dates, lo, hi, mus[w])
            readings[w]["per_buy_bp"].append(s["per_buy"]["mean_bp"])
            readings[w]["per_buy_t"].append(s["per_buy"]["t"])
            readings[w]["session_bp"].append(s["session"]["mean_bp"])
            readings[w]["next_open_bp"].append(s["per_buy_next_open"]["mean_bp"])
        if k == median:
            chosen = acc
        if log is not None:
            log(f"  offset {k}: {acc.decisions} decisions at {grid.mode}")
    assert chosen is not None
    return readings, chosen


# The full ledger walk at one offset: the control walked without and with
# the close buys, and the reading of the difference.
def _walk_block(
    run: so.ControlRun,
    grid: Grid,
    context: Context,
    spans: Mapping[str, tuple[date | None, date | None]],
) -> dict[str, Any]:
    """Return the walk block of the payload."""
    control, candidate = (
        walk(
            context.restricted,
            context.mask,
            run.since,
            grid,
            context.early,
            context.cost_bps,
            moc=moc,
            given=context.given,
        )
        for moc in (False, True)
    )
    dates = np.asarray(context.restricted.panel.dates, dtype="datetime64[D]")
    return walk_reading(control, candidate, run.returns, dates, spans)


# The payload's description of what was run: the plan, the policy and
# control, the decision times, the eligibility, the offsets, the windows
# and the constants the criteria read.
def _describe(
    runs: Sequence[so.ControlRun],
    grids: Mapping[str, Grid],
    context: Context,
    registered: int,
    spans: Mapping[str, tuple[date | None, date | None]],
) -> dict[str, Any]:
    """Return the payload's head."""
    dates = np.asarray(context.restricted.panel.dates, dtype="datetime64[D]")
    median = len(runs) // 2
    return {
        "study": STUDY,
        "plan": PLAN,
        "audit": AUDIT,
        "asof": str(dates[-1]) if len(dates) else None,
        "policy": POLICY,
        "control": {
            "executor": CONTROL,
            "fills": "dip_or_close",
            "basis": runs[median].orders.basis,
            "cost_bps": float(context.cost_bps),
        },
        "decision": {
            "registered": {
                "time": REGISTERED.label,
                "slot": REGISTERED.slot,
                "volume_slot": REGISTERED.volume_slot,
                "tone_cutoff": REGISTERED.tone_cutoff.isoformat(),
            },
            "reported": [label for label in grids if label != REGISTERED.label],
        },
        "eligible_legs": list(LEGS),
        "not_eligible": [NOT_EVENT, NOT_EARLY, NOT_BAR],
        "extra_cost_bps_each_way": EXTRA_COST_BPS,
        "offsets": {
            "registered": int(registered),
            "priced": len(runs),
            "median": median,
            "smoke": len(runs) < int(registered),
            "starts": [int(r.orders.start) for r in runs],
        },
        "windows": {
            w: [str(lo) if lo else None, str(hi) if hi else None]
            for w, (lo, hi) in spans.items()
        },
        "hac_lag": HAC_LAG,
        "criterion_t": CRITERION_T,
        "trials": TRIALS,
        "grids": {
            label: {
                "start": str(dates[g.start]),
                "stop": str(dates[g.stop - 1]),
                **g.meta,
            }
            for label, g in grids.items()
        },
    }


# The registered test from the offsets' control runs, their null replays
# and the null test's result: per offset the 15:30 comparison and each
# window's per-buy and session readings; at the median offset every
# statistic, the other decision times (the 15:45 variant, reported), the
# rows and the full ledger walk; then the verdict. `registered` is the
# plan's offset count (fewer is a smoke run); `spans` replaces the
# registered windows (tests).
def evaluate(
    runs: Sequence[so.ControlRun],
    null_replays: Sequence[Replay],
    null_result: Mapping[str, Any],
    grids: Mapping[str, Grid],
    context: Context,
    registered: int = OFFSETS,
    spans: Mapping[str, tuple[date | None, date | None]] | None = None,
    with_walk: bool = True,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Return the payload."""
    if not runs:
        raise ValueError("no offsets were priced")
    if len(null_replays) != len(runs):
        raise ValueError("every offset needs its null replay")
    if REGISTERED.label not in grids:
        raise ValueError(f"the registered {REGISTERED.label} grid is missing")
    spans = dict(spans or WINDOWS)
    dates = np.asarray(context.restricted.panel.dates, dtype="datetime64[D]")
    median = len(runs) // 2
    drifts = {
        w: window_drift(context.restricted, lo, hi) for w, (lo, hi) in spans.items()
    }
    mus = {w: float(d["mu_bp"]) for w, d in drifts.items()}
    main = grids[REGISTERED.label]
    per_offset, chosen = _per_offset(runs, null_replays, main, context, spans, mus, log)
    accounts = {REGISTERED.label: chosen}
    for label, grid in grids.items():
        if label != REGISTERED.label:
            accounts[label] = compare(runs[median], null_replays[median], grid, context)
    payload = _describe(runs, grids, context, registered, spans)
    payload.update(
        {
            "null_test": dict(null_result),
            "drift": drifts,
            "orders": {"per_offset": [so.order_counts(r.orders) for r in runs]},
            "per_offset": per_offset,
            "across_offsets": {
                w: sd._across(v["per_buy_bp"]) for w, v in per_offset.items()
            },
            "results": {
                label: {
                    w: summarize(acc, dates, lo, hi, mus[w])
                    for w, (lo, hi) in spans.items()
                }
                for label, acc in accounts.items()
            },
            "walk": _walk_block(runs[median], main, context, spans)
            if with_walk
            else None,
            "rows": account_rows(chosen, dates),
        }
    )
    payload["verdict"] = verdict(payload)
    return payload


# --- 12. the verdict ----------------------------------------------------------------


# A payload number as a float: None (a NaN written to JSON) reads NaN.
def _f(value: Any) -> float:
    """Return `value` as a float, NaN for None."""
    return math.nan if value is None else float(value)


# Strictly above zero and finite.
def _positive(value: Any) -> bool:
    """Return True when `value` is a finite number above zero."""
    v = _f(value)
    return bool(math.isfinite(v) and v > 0)


# The plan's four criteria on the registered decision at the median offset.
def criteria_of(payload: Mapping[str, Any]) -> dict[str, bool]:
    """Return {criterion: holds}."""
    main = payload["results"][REGISTERED.label]
    deciding = main[DECIDING]
    t = _f(deciding["per_buy"]["t"])
    return {
        "1_deciding_per_buy_and_session": bool(
            _positive(deciding["per_buy"]["mean_bp"])
            and math.isfinite(t)
            and t >= CRITERION_T
            and _positive(deciding["session"]["mean_bp"])
        ),
        "2_replication_per_buy": bool(
            _positive(main[REPLICATION_A]["per_buy"]["mean_bp"])
            and _positive(main[REPLICATION_B]["per_buy"]["mean_bp"])
        ),
        "3_deciding_next_open": _positive(deciding["per_buy_next_open"]["mean_bp"]),
        "4_null_test": bool(payload["null_test"].get("passes")),
    }


# A signed number for a verdict line, "n/a" when missing.
def _signed(x: Any, digits: int = 1) -> str:
    """Return `x` with its sign, "n/a" when missing."""
    v = _f(x)
    return f"{v:+.{digits}f}" if math.isfinite(v) else "n/a"


# One window's per-buy and session reading as text.
def _reading(
    s: Mapping[str, Any], per_buy: str = "per_buy", session: str = "session"
) -> str:
    """Return "g X bp a buy (t Y, N buys); Z bp a session (t W)"."""
    b, q = s[per_buy], s[session]
    return (
        f"g {_signed(b['mean_bp'])} bp a buy (clustered t {_signed(b['t'], 2)}, "
        f"{b['buys']} buys); {_signed(q['mean_bp'], 2)} bp of equity a session "
        f"(Newey-West t {_signed(q['hac_t'], 2)})"
    )


# A criterion's word in a verdict line.
def _holds(ok: bool) -> str:
    """Return "holds" or "fails"."""
    return "holds" if ok else "fails"


# The null test's verdict line: the report cells and the journal decisions
# that differ, over every offset priced.
def _null_line(null: Mapping[str, Any], ok: bool) -> str:
    """Return the null test's line."""
    report = null.get("report", {})
    journal = null.get("journal", [])
    cells = sum((report.get("mismatches") or {}).values())
    differ = sum(j["mismatched"] for j in journal)
    checked = sum(j["checked"] for j in journal)
    return (
        f"null test {_holds(ok)}: {cells} report cells differ over "
        f"{report.get('sessions')} sessions; {differ} of {checked} journal "
        f"decisions differ over {len(journal)} offsets (criterion 4)"
    )


# The registered decision's lines: criteria 1-3, then (reported) the
# eligible buys, the legs and the drift-adjusted reading.
def _registered_lines(
    payload: Mapping[str, Any], criteria: Mapping[str, bool]
) -> list[str]:
    """Return the registered decision's lines."""
    main = payload["results"][REGISTERED.label]
    d, a, b = main[DECIDING], main[REPLICATION_A], main[REPLICATION_B]
    span = payload["windows"][DECIDING]
    e = d["eligible"]
    legs = "; ".join(
        f"{leg} {_signed(s['mean_bp'])} bp ({s['buys']})"
        for leg, s in d["by_leg"].items()
    )
    return [
        f"deciding {span[0]}..{span[1]}: {_reading(d)} - criterion 1 "
        f"{_holds(criteria['1_deciding_per_buy_and_session'])}",
        f"{REPLICATION_A}: {_reading(a)}; {REPLICATION_B}: {_reading(b)} - "
        f"criterion 2 {_holds(criteria['2_replication_per_buy'])}",
        f"next_open control, deciding: "
        f"{_reading(d, 'per_buy_next_open', 'session_next_open')} - criterion 3 "
        f"{_holds(criteria['3_deciding_next_open'])}",
        f"eligible buys, deciding: {e['buys']} of {d['control_buys']} control buys; "
        f"matched {e['matched']}, partial {e['partial']}, missed {e['missed']}; "
        f"extra round trips {d['extras']['count']} at "
        f"{_signed(d['extras']['pnl_bp'])} bp after costs (reported)",
        f"by leg, deciding (reported): {legs}",
        "drift-adjusted, deciding (reported): "
        f"{_reading(d, 'per_buy_drift', 'session_drift')}",
    ]


# The other decision times' lines (the 15:45 variant: reported, deciding
# nothing).
def _variant_lines(payload: Mapping[str, Any]) -> list[str]:
    """Return one line per reported decision time."""
    lines = []
    for label, v in payload["results"].items():
        if label == REGISTERED.label:
            continue
        lines.append(
            f"{label} decision (reported, decides nothing): deciding "
            f"{_reading(v[DECIDING])}; {REPLICATION_A} g "
            f"{_signed(v[REPLICATION_A]['per_buy']['mean_bp'])}; {REPLICATION_B} g "
            f"{_signed(v[REPLICATION_B]['per_buy']['mean_bp'])}"
        )
    return lines


# The full ledger walk's line (reported), or that it was not run.
def _walk_line(walked: Mapping[str, Any] | None) -> str:
    """Return the walk's line."""
    if walked is None:
        return "full ledger walk: not run"
    w = walked["windows"][DECIDING]
    same = "is" if walked["control_is_the_simulator"] else "IS NOT"
    return (
        f"full ledger walk (reported; the simulator's fills, the control walk {same} "
        f"the simulator's run): deciding {_signed(w['mean_bp'], 2)} bp a session "
        f"(t {_signed(w['hac_t'], 2)}), CAGR {_signed(100 * _f(w['candidate_cagr']))}% "
        f"against {_signed(100 * _f(w['control_cagr']))}%"
    )


# The verdict's headline: PASS or RECORD with the criteria that failed; a
# smoke run says it is not the registered test.
def _headline(
    offsets: Mapping[str, Any], label: str, criteria: Mapping[str, bool]
) -> str:
    """Return the headline text."""
    head = ""
    if offsets.get("smoke"):
        head = (
            f"SMOKE RUN ({offsets.get('priced')} of {offsets.get('registered')} "
            "offsets): not the registered test. "
        )
    if label == PASS:
        return head + (
            f"{PASS}: buying the eligible buys at the decision day's close on the "
            f"{REGISTERED.label} decision clears criteria 1-4; the change may be "
            "proposed to the operator (a live change is its own release)"
        )
    failed = ", ".join(k for k, v in criteria.items() if not v)
    return head + (
        f"{RECORD}: criteria not met ({failed}); the board keeps buying in the "
        "next session"
    )


# The verdict: PASS when criteria 1-4 all hold, else RECORD; one line per
# criterion and per reported reading; a smoke run says it is not the test.
def verdict(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return {"label", "criteria", "lines", "text"}."""
    criteria = criteria_of(payload)
    label = PASS if all(criteria.values()) else RECORD
    lines = [
        _null_line(payload["null_test"], criteria["4_null_test"]),
        *_registered_lines(payload, criteria),
        *_variant_lines(payload),
        _walk_line(payload.get("walk")),
    ]
    return {
        "label": label,
        "criteria": criteria,
        "lines": lines,
        "text": _headline(payload.get("offsets") or {}, label, criteria),
    }
