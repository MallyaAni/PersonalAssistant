"""The mid-cycle rule redesigned for the `/4` book: entry variants under live execution.

The execution ablation (`docs/research/execution-ablation-2026-09-27.md`)
found that the whole 4.3-point gap between plain fills and the live
execution policy on the graded equal-weight book is `live_midcycle`: with
it the book earns 23.2% on 2016-2023 against 27.8% without, at paired t
0.5, while on 2024-2026 the same option earns 5 points and 10 points of
drawdown. The verdict was KEEP, and the note named the one candidate: a
redesign of the mid-cycle rule *for this book*. The rule was built to size
concentrated `/3` positions - a band breakout in an A/A+ name buys
`paper.entry_size(band)` of equity, 1.8% at the trigger, up to a 15% name
cap, from whatever cash is on hand - and the `/4` book holds every A/A+
member at about 9% with next to no cash.

What the rule does between rebalances, read from `simulate._live_midcycle`
and `paper.midcycle_orders`:

* rotation: a held name whose grade falls below A is sold in full (at the
  next session's close, held back on a green open) and its proceeds are
  planned pro rata into the other held names up to the paper cap - but the
  buys are paid from tonight's cash, which is nothing, so they are carried
  as a deferred remainder and retried once from the proceeds a session
  later; a retry a gate refuses (the name now rejects its band, or is
  itself downgraded) is dropped and that cash waits for a breakout;
* entries: every A/A+ name in the panel whose band reading is at least
  `paper.ENTRY_BAND_Z`, held or not, buys `entry_size(band)` of equity from
  the cash left after the retry - an unheld name the rebalance would open at
  9% enters at 1.8%, a held name at 9% is topped up toward 15%;
* the cash bound: buys compete for the cash on hand and are scaled down
  together, so after a rotation the pro-rata redeploy and the breakout
  entries split the proceeds by requested notional.

So on this book the mid-cycle rule is (i) a fast exit on a downgrade, (ii)
a small momentum tilt into whichever names break out while cash exists,
and (iii) entries into newly graded names at a fifth of the size the
rebalance will give them. Which of these costs on 2016-2023 and which
earns the 2024-2026 drawdown is what the variants and the diagnostics here
are built to separate. Every variant is the full live policy
(`market_pit_scorecard._live_options`) with the mid-cycle rule alone
modified, through the `midcycle_entries` and `midcycle_sweep` options of
`simulate.run` (their defaults are byte-identical to the live rule);
"mc-off" is live without `live_midcycle`, the ablation's number, kept as
the anchor. `VARIANTS` is fixed here before any run.

Beside the usual statistics each priced run carries a `Ledger` - a passive
observer on the simulator's journal hook, which records decisions and
closing marks without touching execution - from which the diagnostics are
read: mid-cycle turnover, the cash share held, mid-cycle entries and exits
a year, the weight an entry takes, the share of entries still held at the
next rebalance and the share of exits the next rebalance buys back.

`verdict` reads the choosing window (2016-2023) at 25 bp against live.
Nothing here trades or changes the executor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.agents.trading.desk import point_in_time, policy_v4, simulate
from backend.cli import market_pit_scorecard as scorecard
from backend.cli.market_pit_scorecard import WINDOWS, Curve, _on, _since, window_stats
from backend.market import candidate_stats

LIVE = "live"
MC_OFF = "mc-off"
ANCHORS = (LIVE, MC_OFF)
HAC_LAG = 20
VERDICT_COST_BPS = 25.0
CHOOSING = "2016-2023"
REPORTED = "2024-2026"
# The floors, fixed before the run: CAGR points over live on the choosing
# window at 25 bp, the paired Newey-West t against live there, not worse
# than live on the reported window by paired bp/d, and a median worst
# drawdown within this many points of live's on both windows.
ADOPT_POINTS = 1.0
ADOPT_T = 2.0
DRAWDOWN_POINTS = 3.0
ADOPT = "ADOPT (registered)"
RECORD = "RECORD"
STUDY = "midcycle_ew"


@dataclass(frozen=True)
class Variant:
    """One named mid-cycle rule: live with these `simulate.run` options changed."""

    name: str
    live_midcycle: bool = True
    entries: str = simulate.MIDCYCLE_BREAKOUT
    sweep: bool = False
    note: str = ""


# Fixed before the run and named in the payload. Two anchors and four
# modifications of the entry leg; the rotation exit, the deferred retry,
# the cash bound and every other live convention are unchanged in all six.
VARIANTS: tuple[Variant, ...] = (
    Variant(
        MC_OFF,
        live_midcycle=False,
        note="live without live_midcycle: the execution ablation's number, the anchor",
    ),
    Variant(LIVE, note="the full live execution policy, the control"),
    Variant(
        "mc-target-size",
        entries="target",
        note=(
            "breakout entries sized straight to the policy's equal-weight target "
            "for the name that session, less what is held, instead of entry_size(band)"
        ),
    ),
    Variant(
        "mc-no-idle-cash",
        sweep=True,
        note=(
            "the live rule plus a sweep: cash the plan would leave beyond the "
            "policy's own idle share is redeployed pro rata to the held names each "
            "session instead of waiting for a breakout"
        ),
    ),
    Variant(
        "mc-new-grades-only",
        entries="new-grade",
        note=(
            "no band trigger: only a name the policy would hold today that it did "
            "not hold at the last rebalance enters, at its target weight"
        ),
    ),
    Variant(
        "mc-exit-only",
        entries="none",
        note=(
            "rotation exits only: a name losing its grade leaves and its proceeds "
            "are redeployed pro rata; no mid-cycle entries"
        ),
    ),
)


# The variant by name, or KeyError.
def variant(name: str) -> Variant:
    """Return the registered variant called `name`."""
    for v in VARIANTS:
        if v.name == name:
            return v
    raise KeyError(name)


# The `simulate.run` options of a variant: the live policy, exactly as the
# scorecard prices the account, with the mid-cycle keys alone changed.
def options_for(variant_: Variant, panel) -> dict[str, Any]:
    """Return the keyword options `simulate.run` receives for `variant_`."""
    options = scorecard._live_options(panel)
    options["live_midcycle"] = bool(variant_.live_midcycle)
    if variant_.live_midcycle:
        options["midcycle_entries"] = variant_.entries
        options["midcycle_sweep"] = bool(variant_.sweep)
    return options


# An options dict as JSON-able text: the FOMC path is named, not listed.
def _describe(options: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (
            "event_risk.live_path(panel)"
            if k == "event_exposure" and v is not None
            else v
        )
        for k, v in options.items()
    }


REBALANCE = "rebalance"
MIDCYCLE = "midcycle"
EVENT = "event"


# A passive observer for `simulate.run(journal=...)`: it keeps each
# decision's kind (a scheduled rebalance, a mid-cycle plan, or an event
# transition) and each session's closing cash, shares and NAV, and nothing
# else. It never changes an order or a fill - the simulator only reads a
# journal's return values to pass them back - and the diagnostics are read
# off it after the run.
class Ledger:
    """Decisions by kind and closing marks, recorded through the journal hook."""

    # Start empty; the calendar and closes arrive with `assert_inputs`.
    def __init__(self) -> None:
        self.dates: np.ndarray | None = None
        self.closes: np.ndarray | None = None
        self.kinds: dict[int, str] = {}
        self.marks: dict[int, tuple[float, np.ndarray, float, float]] = {}

    # Keep the calendar and the closes the marks will be valued against.
    def assert_inputs(self, sessions, symbols, opens, closes, cost_bps) -> None:
        self.dates = np.asarray(sessions, dtype="datetime64[D]")
        self.closes = np.asarray(closes, dtype=float)

    # The account opens; nothing to keep beyond the first mark that follows.
    def open_account(self, session, cash, positions) -> None:
        return None

    # Classify the decision from its metadata and return the session as its handle.
    def decision(self, session, submitted_units, desired_weights, reason, metadata):
        meta = metadata or {}
        if "scheduled" not in meta or meta.get("event_changed"):
            kind = EVENT
        elif meta.get("scheduled"):
            kind = REBALANCE
        else:
            kind = MIDCYCLE
        self.kinds[int(session)] = kind
        return int(session)

    # Phase adjustments (green-open holds, split legs) change nothing here.
    def adjustment(self, decision, session, phase, submitted_units, reason) -> None:
        return None

    # Fills are read from the marks, not from the batch.
    def fill_batch(self, *args, **kwargs) -> None:
        return None

    # The closing state of a session.
    def mark(self, session, cash, positions, nav, traded) -> None:
        self.marks[int(session)] = (
            float(cash),
            np.array(positions, dtype=float),
            float(nav),
            float(traded),
        )

    # The run is over; nothing to close.
    def finish(self, session, cash, positions, traded, pending) -> None:
        return None


# The names of the diagnostics, in the order the payload and the table show them.
DIAGNOSTICS: tuple[str, ...] = (
    "midcycle_turnover",
    "rebalance_turnover",
    "cash_share",
    "midcycle_cash_share",
    "entries_per_year",
    "entry_weight",
    "entries_held_at_rebalance",
    "exits_per_year",
    "exits_rebought_at_rebalance",
)


# Read one window's diagnostics off a ledger. A fill on session s is the
# decision of s - 1, so its kind is the kind of that decision; an entry is a
# name going from no shares to some on a mid-cycle fill, an exit the
# reverse. "Held at the next rebalance" reads the mark of the next scheduled
# decision session (before its own fill); "rebought" reads the mark after
# that rebalance's fill. Entries and exits whose next rebalance is outside
# the run are left out of the two shares. Turnover is notional traded over
# the mean NAV a year, split by the kind of decision that traded.
def diagnostics(ledger: Ledger, start, end) -> dict[str, float]:  # noqa: C901 - one pass over the marks
    """Return the diagnostics over the fill sessions in [start, end)."""
    out = {k: math.nan for k in DIAGNOSTICS}
    if ledger.dates is None or len(ledger.marks) < 2:
        out["sessions"] = 0
        return out
    keep = point_in_time.window(ledger.dates, start, end)
    sessions = sorted(ledger.marks)
    rebalances = sorted(s for s, k in ledger.kinds.items() if k == REBALANCE)
    navs, cash_shares, mid_cash = [], [], []
    mid_traded = reb_traded = 0.0
    entries: list[tuple[int, int]] = []
    exits: list[tuple[int, int]] = []
    weights: list[float] = []
    for previous, s in zip(sessions[:-1], sessions[1:], strict=False):
        if not keep[s]:
            continue
        cash, shares, nav, traded = ledger.marks[s]
        _pc, before, _pn, traded_before = ledger.marks[previous]
        kind = ledger.kinds.get(previous)
        navs.append(nav)
        if nav > 0:
            cash_shares.append(cash / nav)
            if kind == MIDCYCLE:
                mid_cash.append(cash / nav)
        if kind == MIDCYCLE:
            mid_traded += traded - traded_before
        elif kind == REBALANCE:
            reb_traded += traded - traded_before
        if kind != MIDCYCLE:
            continue
        for j in np.flatnonzero((before <= 0) & (shares > 0)):
            entries.append((s, int(j)))
            price = ledger.closes[s, j]
            if nav > 0 and np.isfinite(price):
                weights.append(float(shares[j] * price / nav))
        for j in np.flatnonzero((before > 0) & (shares <= 0)):
            exits.append((s, int(j)))
    n = len(navs)
    out["sessions"] = n
    if n == 0:
        return out
    years = n / 252.0
    mean_nav = float(np.mean(navs))
    out["midcycle_turnover"] = (
        mid_traded / mean_nav / years if mean_nav > 0 else math.nan
    )
    out["rebalance_turnover"] = (
        reb_traded / mean_nav / years if mean_nav > 0 else math.nan
    )
    out["cash_share"] = float(np.mean(cash_shares)) if cash_shares else math.nan
    out["midcycle_cash_share"] = float(np.mean(mid_cash)) if mid_cash else math.nan
    out["entries_per_year"] = len(entries) / years
    out["exits_per_year"] = len(exits) / years
    out["entry_weight"] = float(np.mean(weights)) if weights else math.nan

    # The next scheduled decision at or after fill session s, or None.
    def _next_rebalance(s: int):
        i = int(np.searchsorted(np.asarray(rebalances), s))
        return rebalances[i] if i < len(rebalances) else None

    held = judged = 0
    for s, j in entries:
        r = _next_rebalance(s)
        if r is None or r not in ledger.marks:
            continue
        judged += 1
        held += int(ledger.marks[r][1][j] > 0)
    out["entries_held_at_rebalance"] = held / judged if judged else math.nan
    rebought = judged = 0
    for s, j in exits:
        r = _next_rebalance(s)
        if r is None or (r + 1) not in ledger.marks:
            continue
        judged += 1
        rebought += int(ledger.marks[r + 1][1][j] > 0)
    out["exits_rebought_at_rebalance"] = rebought / judged if judged else math.nan
    return out


@dataclass(frozen=True)
class Priced:
    """One variant from one offset at one cost: its curve and per-window diagnostics."""

    curve: Curve
    diagnostics: dict[str, dict[str, float]] = field(default_factory=dict)


# Price one variant from one offset at one cost: `simulate.run` on the
# restricted report with the policy's allocator, the variant's options and
# a fresh Ledger, then the diagnostics per window.
def price(
    restricted, mask: np.ndarray, variant_: Variant, since, cost_bps: float
) -> Priced:
    """Return the variant's Priced result from `since` at `cost_bps`."""
    panel = restricted.panel
    ledger = Ledger()
    result = simulate.run(
        restricted,
        since=since,
        cost_bps=cost_bps,
        allocator=policy_v4.allocator(mask),
        journal=ledger,
        **options_for(variant_, panel),
    )
    return Priced(
        Curve(variant_.name, result.dates, result.returns),
        {w: diagnostics(ledger, s, e) for w, (s, e) in WINDOWS.items()},
    )


# Median over finite entries, NaN when there are none.
def _nanmedian(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmedian(x)) if np.isfinite(x).any() else math.nan


# Minimum over finite entries, NaN when there are none.
def _nanmin(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmin(x)) if np.isfinite(x).any() else math.nan


# Maximum over finite entries, NaN when there are none.
def _nanmax(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmax(x)) if np.isfinite(x).any() else math.nan


# The reference calendar of one offset: live's sessions, else the first variant
# that ran.
def _calendar(offset: dict[str, Priced]) -> np.ndarray:
    if LIVE in offset:
        return offset[LIVE].curve.dates
    return next(iter(offset.values())).curve.dates


# One row per (variant, window) at one cost: medians, worsts, the count of
# offsets whose CAGR beats live's on the same sessions, and the median of
# each diagnostic across offsets. Field names are the pit scorecard's.
def summarise(priced: list[dict[str, Priced]], cost_bps: float) -> list[dict[str, Any]]:
    """Return the per-window rows across the offsets at `cost_bps`."""
    rows: list[dict[str, Any]] = []
    names = [v.name for v in VARIANTS if all(v.name in offset for offset in priced)]
    for window, (start, end) in WINDOWS.items():
        stats: dict[str, list[dict[str, float]]] = {name: [] for name in names}
        for offset in priced:
            base = _calendar(offset)
            keep = point_in_time.window(base, start, end)
            for name in names:
                stats[name].append(window_stats(_on(base, offset[name].curve)[keep]))
        live_cagr = np.array([s["cagr"] for s in stats.get(LIVE, [])], dtype=float)
        for name in names:
            cagrs = np.array([s["cagr"] for s in stats[name]], dtype=float)
            above = (
                int(np.nansum(cagrs > live_cagr)) if len(live_cagr) == len(cagrs) else 0
            )
            row = {
                "line": name,
                "cost_bps": cost_bps,
                "window": window,
                "offsets": len(priced),
                "median_cagr": _nanmedian(cagrs),
                "worst_cagr": _nanmin(cagrs),
                "best_cagr": _nanmax(cagrs),
                "median_drawdown": _nanmedian([s["drawdown"] for s in stats[name]]),
                "median_sharpe": _nanmedian([s["sharpe"] for s in stats[name]]),
                "offsets_above_live": above,
                "sessions": int(np.nanmedian([s["sessions"] for s in stats[name]])),
            }
            for key in DIAGNOSTICS:
                row[key] = _nanmedian(
                    [
                        offset[name].diagnostics.get(window, {}).get(key, math.nan)
                        for offset in priced
                    ]
                )
            rows.append(row)
    return rows


# The paired daily difference of every variant against live and against
# mc-off at the median offset, per window: mean bp a day, Newey-West t at
# lag 20 and the probabilistic Sharpe.
def paired(priced: list[dict[str, Priced]], cost_bps: float) -> list[dict[str, Any]]:
    """Return the paired rows at the median offset for `cost_bps`."""
    out: list[dict[str, Any]] = []
    offset = priced[len(priced) // 2]
    base = _calendar(offset)
    for window, (start, end) in WINDOWS.items():
        keep = point_in_time.window(base, start, end)
        for against in ANCHORS:
            if against not in offset:
                continue
            b = _on(base, offset[against].curve)[keep]
            for v in VARIANTS:
                if v.name == against or v.name not in offset:
                    continue
                diff = _on(base, offset[v.name].curve)[keep] - b
                diff = diff[np.isfinite(diff)]
                mom = candidate_stats.moments(diff) if len(diff) > 2 else None
                out.append(
                    {
                        "cost_bps": cost_bps,
                        "window": window,
                        "line": v.name,
                        "against": against,
                        "sessions": int(len(diff)),
                        "mean_daily_bp": float(diff.mean() * 1e4)
                        if len(diff)
                        else math.nan,
                        "hac_t": candidate_stats.hac_t(diff, HAC_LAG)
                        if len(diff) > 2
                        else math.nan,
                        "psr": (
                            candidate_stats.probabilistic_sharpe(
                                mom.sharpe, mom.length, mom.skew, mom.kurtosis
                            )
                            if mom is not None
                            else math.nan
                        ),
                    }
                )
    return out


# Run every variant at every offset and cost and assemble the payload.
# `store` is accepted for the scorecard's call shape and is not read. A
# variant `simulate.run` refuses is recorded under `refused` with the
# reason and left out of the rows - never silently skipped.
def run_variants(
    report, restricted, mask: np.ndarray, store, offsets: int, costs: tuple[float, ...]
) -> dict[str, Any]:
    """Return the study payload for the policy on the restricted report."""
    panel = restricted.panel
    refused: dict[str, str] = {}
    payload: dict[str, Any] = {
        "study": STUDY,
        "policy": policy_v4.POLICY_VERSION,
        "asof": str(panel.dates[-1]),
        "offsets": int(offsets),
        "costs_bps": [float(c) for c in costs],
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "trials": len(VARIANTS),
        "variants": [
            {
                "name": v.name,
                "live_midcycle": v.live_midcycle,
                "entries": v.entries if v.live_midcycle else None,
                "sweep": v.sweep if v.live_midcycle else None,
                "note": v.note,
                "options": _describe(options_for(v, panel)),
            }
            for v in VARIANTS
        ],
        "hac_lag": HAC_LAG,
        "diagnostics": list(DIAGNOSTICS),
        "rows": [],
        "paired": [],
        "refused": refused,
        "note": (
            "Every variant is one registered trial, fixed in VARIANTS before the run: "
            "the full live execution policy with the mid-cycle rule alone modified. "
            "Lines priced on identical sessions from each of the first `offsets` "
            "sessions of the restricted report with policy_v4's allocator; medians "
            "and worsts across offsets; paired statistics at the median offset against "
            "live and against mc-off; diagnostics are medians across offsets of what a "
            "passive ledger read off each run."
        ),
    }
    for cost in costs:
        priced: list[dict[str, Priced]] = []
        for k in range(int(offsets)):
            since = _since(panel, k)
            offset: dict[str, Priced] = {}
            for v in VARIANTS:
                if v.name in refused:
                    continue
                try:
                    offset[v.name] = price(restricted, mask, v, since, float(cost))
                except ValueError as exc:
                    refused[v.name] = f"simulate.run refused: {exc}"
            priced.append(offset)
        for offset in priced:
            for name in list(offset):
                if name in refused:
                    del offset[name]
        payload["rows"].extend(summarise(priced, float(cost)))
        payload["paired"].extend(paired(priced, float(cost)))
    payload["ran"] = [v.name for v in VARIANTS if v.name not in refused]
    return payload


# The row for a line and window at a cost, or None.
def _row(payload: dict[str, Any], line: str, window: str, cost: float) -> dict | None:
    for r in payload["rows"]:
        if r["line"] == line and r["window"] == window and float(r["cost_bps"]) == cost:
            return r
    return None


# The paired entry for a line against a base and window at a cost, or None.
def _pair(
    payload: dict[str, Any], line: str, against: str, window: str, cost: float
) -> dict | None:
    for p in payload["paired"]:
        if (
            p["line"] == line
            and p["against"] == against
            and p["window"] == window
            and float(p["cost_bps"]) == cost
        ):
            return p
    return None


# A payload value that may be None (after json_ready) or NaN, as a float.
def _f(value) -> float:
    return math.nan if value is None else float(value)


# A signed number to `digits` decimals, "n/a" for NaN.
def _signed(x: float, digits: int = 2) -> str:
    return "n/a" if not np.isfinite(x) else f"{x:+.{digits}f}"


# The verdict: every variant other than live is read against live at 25 bp -
# the CAGR points on the choosing window, the paired t there, the paired
# bp/d on the reported window, and the drawdown gap on both windows. ADOPT
# (registered) only when all four floors hold; else RECORD. mc-off is
# assessed the same way, as the anchor: an ADOPT there would repeat the
# ablation's removal question, which the ablation already answered KEEP.
def verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the verdict block for the payload."""
    costs = [float(c) for c in payload.get("costs_bps", [])]
    cost = (
        VERDICT_COST_BPS
        if VERDICT_COST_BPS in costs
        else (max(costs) if costs else math.nan)
    )
    live_choose = _row(payload, LIVE, CHOOSING, cost) or {}
    live_report = _row(payload, LIVE, REPORTED, cost) or {}
    live_cagr = _f(live_choose.get("median_cagr"))
    live_dd = {
        CHOOSING: _f(live_choose.get("median_drawdown")),
        REPORTED: _f(live_report.get("median_drawdown")),
    }
    variants: dict[str, dict[str, Any]] = {}
    adopt: list[str] = []
    record: list[str] = []
    for v in VARIANTS:
        if v.name == LIVE:
            continue
        row = _row(payload, v.name, CHOOSING, cost) or {}
        later = _row(payload, v.name, REPORTED, cost) or {}
        pair = _pair(payload, v.name, LIVE, CHOOSING, cost) or {}
        later_pair = _pair(payload, v.name, LIVE, REPORTED, cost) or {}
        points = (_f(row.get("median_cagr")) - live_cagr) * 100.0
        later_points = (
            _f(later.get("median_cagr")) - _f(live_report.get("median_cagr"))
        ) * 100.0
        t = _f(pair.get("hac_t"))
        later_bp = _f(later_pair.get("mean_daily_bp"))
        dd_gap = {
            CHOOSING: (_f(row.get("median_drawdown")) - live_dd[CHOOSING]) * 100.0,
            REPORTED: (_f(later.get("median_drawdown")) - live_dd[REPORTED]) * 100.0,
        }
        measured = bool(np.isfinite(points))
        passes = bool(
            measured and points >= ADOPT_POINTS and np.isfinite(t) and t >= ADOPT_T
        )
        not_worse = bool(np.isfinite(later_bp) and later_bp >= 0.0)
        drawdown_ok = bool(
            all(np.isfinite(g) and g >= -DRAWDOWN_POINTS for g in dd_gap.values())
        )
        decision = ADOPT if passes and not_worse and drawdown_ok else RECORD
        variants[v.name] = {
            "anchor": v.name in ANCHORS,
            "measured": measured,
            "refused": payload.get("refused", {}).get(v.name),
            "choosing_points": points,
            "choosing_bp_vs_live": _f(pair.get("mean_daily_bp")),
            "choosing_t_vs_live": t,
            "reported_points": later_points,
            "reported_bp_vs_live": later_bp,
            "drawdown_gap_points": dd_gap,
            "passes_choosing": passes,
            "not_worse_reported": not_worse,
            "drawdown_within": drawdown_ok,
            "decision": decision,
        }
        (adopt if decision == ADOPT else record).append(v.name)
    if not np.isfinite(live_cagr):
        text = (
            f"not measured: live has no {CHOOSING} CAGR at {cost:g} bp "
            f"(refused: {sorted(payload.get('refused', {})) or 'none'})"
        )
    else:
        parts = [
            f"{name} {_signed(info['choosing_points'], 1)} pt "
            f"(t {_signed(info['choosing_t_vs_live'])}, "
            f"{REPORTED} {_signed(info['reported_bp_vs_live'], 1)} bp/d, "
            f"DD {_signed(info['drawdown_gap_points'][CHOOSING], 1)}/"
            f"{_signed(info['drawdown_gap_points'][REPORTED], 1)} pt) "
            f"{info['decision']}"
            for name, info in variants.items()
        ]
        text = (
            f"{CHOOSING} at {cost:g} bp: live {live_cagr * 100:.1f}%. "
            "Variants against live: "
            + "; ".join(parts)
            + ". "
            + (
                f"{ADOPT}: {', '.join(adopt)}."
                if adopt
                else (
                    f"No variant clears {ADOPT_POINTS:g} pt with t >= {ADOPT_T:g}, "
                    f"not worse on {REPORTED} and drawdown within "
                    f"{DRAWDOWN_POINTS:g} pt; every variant is RECORD."
                )
            )
        )
    return {
        "cost_bps": cost,
        "choosing_window": CHOOSING,
        "reported_window": REPORTED,
        "floors": {
            "points": ADOPT_POINTS,
            "hac_t": ADOPT_T,
            "drawdown_points": DRAWDOWN_POINTS,
        },
        "live_cagr": live_cagr,
        "variants": variants,
        "adopt": adopt,
        "record": record,
        "text": text,
    }
