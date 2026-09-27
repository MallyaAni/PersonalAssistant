"""The catastrophe stop: a single-name stop priced on the `/4` book, from entry and from peak.

The graded equal-weight policy (`policy_v4.allocator(mask)`, about twelve
names at about 8.3% each on the paper account) has two defences against a
name that falls 90% - the grade rotation, which drops a name when its grade
goes, and the equal-weight cap, which bounds what one name can be. Neither
acts between rebalances. The operator asked how the book avoids a
Lucid-type collapse; this module prices the third defence, a per-name stop,
as a fixed set of registered trials on identical sessions.

The stop wraps the allocator without changing it. `CatastropheStop` tracks
every held name's price path from its entry (the decision session on which
its target weight first became positive; the entry price is that session's
adjusted close, one session before the fill) and, on the first close below
`entry * (1 - threshold)` ("entry" mode) or below the running maximum close
since entry ("peak" mode, a trailing high-water mark), forces the target to
zero. The sale fills at the next open like any other order and the
proceeds sit in cash until the next rebalance. The name stays out until the
allocator's mask has excluded it at a rebalance (one full cycle not held)
and then included it again - the cooldown that stops the same grade
re-buying the name at the very next reset. Every trigger is recorded with
its entry, trigger and drawdown, and afterwards with whether the name
closed back above the trigger price within `RECOVERY_SESSIONS` (the "false
alarm" reading).

The allocator is only called on rebalance sessions, so the stop hooks into
`simulate.run` through its `weight_filter(t, target, prices)` hook (added
for this trial; None leaves every run byte-identical) for the
between-rebalance sessions and through the allocator wrapper for the
cooldown on rebalances. `VARIANTS` is fixed here before any run; `verdict`
reads the choosing window (2016-2023) at 25 bp against the control under
the floors below and prices the insurance premium - CAGR points given up
per point of drawdown saved. Nothing here trades or changes the executor.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from backend.agents.trading.desk import paper, point_in_time, policy_v4, simulate
from backend.cli.market_pit_scorecard import WINDOWS, Curve, _on, _since, window_stats
from backend.market import candidate_stats

NONE = "none"
ENTRY = "entry"
PEAK = "peak"
# Sessions after a trigger within which a close back above the trigger
# price counts the trigger as a false alarm.
RECOVERY_SESSIONS = 60
HAC_LAG = 20
VERDICT_COST_BPS = 25.0
CHOOSING = "2016-2023"
REPORTED = "2024-2026"
# The floors for a stop to be adopted, fixed before the run: not worse
# than the control on the choosing window at 25 bp by more than this many
# CAGR points, cutting the median worst drawdown by at least this many
# points or the worst single-name day by at least this fraction, and not
# worse on the reported window by paired bp a day.
MAX_COST_POINTS = 0.5
DRAWDOWN_POINTS = 3.0
WORST_DAY_CUT = 0.25
ADOPT = "ADOPT (registered)"
RECORD = "RECORD"


@dataclass(frozen=True)
class Variant:
    """One named stop: the reference the threshold is read from, and the threshold."""

    name: str
    mode: str
    threshold: float | None = None
    note: str = ""


# Fixed before the run and named in the payload: the control and three
# thresholds each from entry and from the running peak. Seven trials.
VARIANTS: tuple[Variant, ...] = (
    Variant(NONE, NONE, None, note="control: plain next-open fills, no stop"),
    Variant("entry-40", ENTRY, 0.40, note="sell on a close 40% below the entry close"),
    Variant("entry-50", ENTRY, 0.50, note="sell on a close 50% below the entry close"),
    Variant("entry-60", ENTRY, 0.60, note="sell on a close 60% below the entry close"),
    Variant(
        "peak-40",
        PEAK,
        0.40,
        note="sell on a close 40% below the peak close since entry",
    ),
    Variant(
        "peak-50",
        PEAK,
        0.50,
        note="sell on a close 50% below the peak close since entry",
    ),
    Variant(
        "peak-60",
        PEAK,
        0.60,
        note="sell on a close 60% below the peak close since entry",
    ),
)


@dataclass
class Trigger:
    """One stop firing: the position's entry, the session it fired, what came after."""

    ticker: str
    column: int
    entry_index: int
    entry_date: str
    entry_price: float
    peak_price: float
    trigger_index: int
    trigger_date: str
    trigger_price: float
    # The drawdown the rule read: from entry in "entry" mode, from peak in "peak" mode.
    drawdown: float
    drawdown_from_entry: float
    drawdown_from_peak: float
    # Filled after the run: True when a close within RECOVERY_SESSIONS after
    # the trigger was above the trigger price, False when the full window
    # passed without one, None when the panel ends before the window does.
    recovered: bool | None = None
    recovery_sessions: int | None = None

    # The trigger as a JSON-able dict.
    def as_dict(self) -> dict[str, Any]:
        """Return the trigger's fields as a plain dict."""
        return asdict(self)


# The plain option set every variant runs under: no exit overlay, the live
# reset cadence, next-open fills, and a stopped name's proceeds held as cash
# rather than redeployed into the other names (`redeploy=False`), because
# the run is about what one name's collapse costs, not about re-risking.
def plain_options() -> dict[str, Any]:
    """Return the `simulate.run` keyword options for plain next-open fills."""
    return dict(use_exits=False, rebalance=paper.REBALANCE_EVERY, redeploy=False)


class CatastropheStop:
    """The stop around an allocator: entries, the trigger, the cooldown, the record.

    `allocator` is the wrapped rebalance allocator (`(report, panel, config,
    t) -> weights`) and `weight_filter` the per-session hook for
    `simulate.run`; both share this object's state. With `threshold` None
    (the control) nothing is ever stopped and the object only records the
    per-session target weights the single-name contribution is read from.
    """

    # Bind the wrapped allocator, the mode and threshold, and the panel whose
    # tickers and dates name the triggers.
    def __init__(self, base, mode: str, threshold: float | None, panel) -> None:
        if mode not in (NONE, ENTRY, PEAK):
            raise ValueError(f"unknown stop mode {mode!r}")
        if mode == NONE and threshold is not None:
            raise ValueError("the control has no threshold")
        if mode != NONE and not (
            threshold is not None and np.isfinite(threshold) and 0 < threshold < 1
        ):
            raise ValueError("threshold must be a finite fraction in (0, 1)")
        self.base = base
        self.mode = mode
        self.threshold = threshold
        self.panel = panel
        self.tickers = list(panel.tickers)
        self.stamps = [str(d) for d in panel.dates]
        self.entry_index: dict[int, int] = {}
        self.entry_price: dict[int, float] = {}
        self.peak: dict[int, float] = {}
        # A stopped name -> whether a rebalance has since excluded it. It is
        # forced to zero at every rebalance until that happens, and released
        # at the first rebalance after it that wants the name back.
        self.blocked: dict[int, bool] = {}
        self.triggers: list[Trigger] = []
        self.rebalances: list[int] = []
        # (T, N) the target decided on each session after the stop, NaN on
        # sessions the book made no decision (before `since`, the last).
        self.weights = np.full(panel.adj_close.shape, np.nan)

    # The rebalance allocator: the base's targets with every stopped name in
    # cooldown forced to zero. A base target of zero for a blocked name is
    # the mask excluding it - one full cycle out - after which the next
    # rebalance that wants it may have it.
    def allocator(self, report, panel, config, t: int) -> np.ndarray:
        """Return the base allocator's targets with cooled-down names at zero."""
        target = np.array(self.base(report, panel, config, t), dtype=float)
        self.rebalances.append(int(t))
        for column in list(self.blocked):
            if not target[column] > 0:
                self.blocked[column] = True
            elif self.blocked[column]:
                del self.blocked[column]
            else:
                target[column] = 0.0
        return target

    # The reference price the threshold is read against for one tracked name.
    def _reference(self, column: int) -> float:
        return self.entry_price[column] if self.mode == ENTRY else self.peak[column]

    # Forget a name's path (it left the book, or it was just stopped).
    def _forget(self, column: int) -> None:
        self.entry_index.pop(column, None)
        self.entry_price.pop(column, None)
        self.peak.pop(column, None)

    # The per-session hook for `simulate.run`: track entries and peaks of
    # every targeted name at `prices` (that session's adjusted closes),
    # force a stopped or cooling-down name to zero, and record the trigger.
    def weight_filter(self, t: int, weights, prices) -> np.ndarray:
        """Return `weights` with any name through its stop forced to zero."""
        out = np.array(weights, dtype=float)
        prices = np.asarray(prices, dtype=float)
        targeted = out > 0
        for column in list(self.entry_index):
            if not targeted[column]:
                self._forget(column)
        for column in np.flatnonzero(targeted):
            column = int(column)
            if column in self.blocked:
                # A stopped name the book still carries (a sale that did not
                # fill, or a rebalance that wanted it back) stays at zero.
                out[column] = 0.0
                continue
            price = float(prices[column])
            if not (np.isfinite(price) and price > 0):
                continue
            if column not in self.entry_index:
                self.entry_index[column] = int(t)
                self.entry_price[column] = price
                self.peak[column] = price
            elif price > self.peak[column]:
                self.peak[column] = price
            if self.threshold is None:
                continue
            reference = self._reference(column)
            if price < reference * (1.0 - self.threshold):
                entry_price = self.entry_price[column]
                peak = self.peak[column]
                self.triggers.append(
                    Trigger(
                        ticker=self.tickers[column],
                        column=column,
                        entry_index=self.entry_index[column],
                        entry_date=self.stamps[self.entry_index[column]],
                        entry_price=entry_price,
                        peak_price=peak,
                        trigger_index=int(t),
                        trigger_date=self.stamps[int(t)],
                        trigger_price=price,
                        drawdown=price / reference - 1.0,
                        drawdown_from_entry=price / entry_price - 1.0,
                        drawdown_from_peak=price / peak - 1.0,
                    )
                )
                out[column] = 0.0
                self.blocked[column] = False
                self._forget(column)
        self.weights[int(t)] = out
        return out

    # Fill every trigger's recovery reading from the panel's closes.
    def resolve_recoveries(self, sessions: int = RECOVERY_SESSIONS) -> None:
        """Mark each trigger recovered, not recovered, or unresolved (panel ended)."""
        closes = self.panel.adj_close
        rows = closes.shape[0]
        for trigger in self.triggers:
            first = trigger.trigger_index + 1
            last = min(rows, first + sessions)
            after = closes[first:last, trigger.column]
            above = np.flatnonzero(np.isfinite(after) & (after > trigger.trigger_price))
            if len(above):
                trigger.recovered = True
                trigger.recovery_sessions = int(above[0]) + 1
            elif last - first >= sessions:
                trigger.recovered = False
            else:
                trigger.recovered = None

    # The worst single-name contribution on each session: the smallest
    # weight-times-return over names, where the weight is the target decided
    # at the previous session's close and the return that session's
    # close-to-close move. Zero when nothing was held; NaN before the run.
    def name_loss(self) -> np.ndarray:
        """Return the (T,) worst one-name contribution per session (<= 0)."""
        closes = self.panel.adj_close
        rows = closes.shape[0]
        out = np.full(rows, np.nan)
        with np.errstate(all="ignore"):
            ret = closes[1:] / closes[:-1] - 1.0
        prior = self.weights[:-1]
        decided = np.isfinite(prior).all(axis=1)
        contribution = np.where(np.isfinite(ret) & (prior > 0), prior * ret, 0.0)
        worst = np.minimum(contribution.min(axis=1), 0.0)
        out[1:] = np.where(decided, worst, np.nan)
        return out


@dataclass
class Priced:
    """One variant from one offset at one cost: curve, name loss and triggers."""

    curve: Curve
    name_loss: Curve
    triggers: list[Trigger] = field(default_factory=list)


# The variant by name, or KeyError.
def variant(name: str) -> Variant:
    """Return the registered variant called `name`."""
    for v in VARIANTS:
        if v.name == name:
            return v
    raise KeyError(name)


# The stop for a variant around the policy's allocator on a panel.
def build(variant_: Variant, mask: np.ndarray, panel) -> CatastropheStop:
    """Return the CatastropheStop for `variant_` around `policy_v4.allocator(mask)`."""
    return CatastropheStop(
        policy_v4.allocator(mask), variant_.mode, variant_.threshold, panel
    )


# Price one variant from one offset at one cost: `simulate.run` on the
# restricted report under the plain options with the stop's allocator and
# hook. The control's stop never fires; it records the weights the
# single-name contribution is read from and nothing else, so the control's
# curve is `simulate.run` under the plain options element for element.
def price(
    restricted, mask: np.ndarray, variant_: Variant, since, cost_bps: float
) -> Priced:
    """Return the variant's Priced result from `since` at `cost_bps`."""
    panel = restricted.panel
    stop = build(variant_, mask, panel)
    result = simulate.run(
        restricted,
        since=since,
        cost_bps=cost_bps,
        allocator=stop.allocator,
        weight_filter=stop.weight_filter,
        **plain_options(),
    )
    stop.resolve_recoveries()
    start = len(panel.dates) - len(result.dates)
    return Priced(
        Curve(variant_.name, result.dates, result.returns),
        Curve(variant_.name, result.dates, stop.name_loss()[start:]),
        stop.triggers,
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


# The reference calendar of one offset: the control's sessions, else the
# first variant that ran.
def _calendar(offset: dict[str, Priced]) -> np.ndarray:
    if NONE in offset:
        return offset[NONE].curve.dates
    return next(iter(offset.values())).curve.dates


# The triggers of one run whose trigger session falls inside a window.
def _in_window(
    triggers: list[Trigger], dates: np.ndarray, keep: np.ndarray
) -> list[Trigger]:
    inside = {str(d) for d in np.asarray(dates)[keep]}
    return [tr for tr in triggers if tr.trigger_date in inside]


# One row per (variant, window) at one cost: the scorecard's medians and
# worsts, the worst single-name day (min over the window, median across
# offsets), triggers a year (median across offsets), the false-alarm rate
# (pooled across offsets over the triggers whose recovery window the panel
# covers) and the count of offsets whose CAGR beats the control's.
def summarise(priced: list[dict[str, Priced]], cost_bps: float) -> list[dict[str, Any]]:
    """Return the per-window rows across the offsets at `cost_bps`."""
    rows: list[dict[str, Any]] = []
    names = [v.name for v in VARIANTS if all(v.name in offset for offset in priced)]
    for window, (start, end) in WINDOWS.items():
        stats: dict[str, list[dict[str, float]]] = {name: [] for name in names}
        worst_day: dict[str, list[float]] = {name: [] for name in names}
        per_year: dict[str, list[float]] = {name: [] for name in names}
        recovered: dict[str, list[int]] = {name: [0, 0, 0] for name in names}
        for offset in priced:
            base = _calendar(offset)
            keep = point_in_time.window(base, start, end)
            for name in names:
                run = offset[name]
                stat = window_stats(_on(base, run.curve)[keep])
                stats[name].append(stat)
                worst_day[name].append(_nanmin(_on(base, run.name_loss)[keep]))
                inside = _in_window(run.triggers, base, keep)
                years = stat["sessions"] / 252.0
                per_year[name].append(len(inside) / years if years > 0 else math.nan)
                counts = recovered[name]
                counts[0] += len(inside)
                counts[1] += sum(1 for tr in inside if tr.recovered is True)
                counts[2] += sum(1 for tr in inside if tr.recovered is False)
        control = np.array([s["cagr"] for s in stats.get(NONE, [])], dtype=float)
        for name in names:
            cagrs = np.array([s["cagr"] for s in stats[name]], dtype=float)
            above = int(np.nansum(cagrs > control)) if len(control) == len(cagrs) else 0
            total, yes, no = recovered[name]
            rows.append(
                {
                    "line": name,
                    "cost_bps": cost_bps,
                    "window": window,
                    "offsets": len(priced),
                    "median_cagr": _nanmedian(cagrs),
                    "worst_cagr": _nanmin(cagrs),
                    "best_cagr": _nanmax(cagrs),
                    "median_drawdown": _nanmedian([s["drawdown"] for s in stats[name]]),
                    "median_sharpe": _nanmedian([s["sharpe"] for s in stats[name]]),
                    "worst_name_day": _nanmedian(worst_day[name]),
                    "triggers_per_year": _nanmedian(per_year[name]),
                    "triggers_total": int(total),
                    "triggers_resolved": int(yes + no),
                    "false_alarm_rate": (yes / (yes + no)) if (yes + no) else math.nan,
                    "offsets_above_control": above,
                    "sessions": int(np.nanmedian([s["sessions"] for s in stats[name]])),
                }
            )
    return rows


# The paired daily difference of every stop against the control at the
# median offset, per window: mean bp a day, Newey-West t at lag 20 and the
# probabilistic Sharpe. Field names are the scorecard's.
def paired(priced: list[dict[str, Priced]], cost_bps: float) -> list[dict[str, Any]]:
    """Return the paired rows against the control at the median offset."""
    out: list[dict[str, Any]] = []
    offset = priced[len(priced) // 2]
    if NONE not in offset:
        return out
    base = _calendar(offset)
    for window, (start, end) in WINDOWS.items():
        keep = point_in_time.window(base, start, end)
        b = _on(base, offset[NONE].curve)[keep]
        for v in VARIANTS:
            if v.name == NONE or v.name not in offset:
                continue
            a = _on(base, offset[v.name].curve)[keep]
            diff = a - b
            diff = diff[np.isfinite(diff)]
            mom = candidate_stats.moments(diff) if len(diff) > 2 else None
            out.append(
                {
                    "cost_bps": cost_bps,
                    "window": window,
                    "line": v.name,
                    "against": NONE,
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
# `store` is accepted for the scorecard's call shape and is not read. The
# triggers kept in the payload are those of the median offset at the
# verdict cost (or the largest cost run), per variant, so the file names
# every firing the verdict was read from without repeating them 40 times.
def run_variants(
    report, restricted, mask: np.ndarray, store, offsets: int, costs: tuple[float, ...]
) -> dict[str, Any]:
    """Return the catastrophe-stop payload for the policy on the restricted report."""
    panel = restricted.panel
    costs = tuple(float(c) for c in costs)
    verdict_cost = VERDICT_COST_BPS if VERDICT_COST_BPS in costs else max(costs)
    payload: dict[str, Any] = {
        "study": "catastrophe_stop",
        "policy": policy_v4.POLICY_VERSION,
        "asof": str(panel.dates[-1]),
        "offsets": int(offsets),
        "costs_bps": list(costs),
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "trials": len(VARIANTS),
        "variants": [
            {"name": v.name, "mode": v.mode, "threshold": v.threshold, "note": v.note}
            for v in VARIANTS
        ],
        "options": plain_options(),
        "recovery_sessions": RECOVERY_SESSIONS,
        "hac_lag": HAC_LAG,
        "rows": [],
        "paired": [],
        "triggers": {},
        "note": (
            "Every variant is one registered trial, fixed in VARIANTS before the "
            "run. Lines priced on identical sessions from each of the first "
            "`offsets` sessions of the restricted report with policy_v4's allocator "
            "under plain next-open fills; a stop sells at the next open after the "
            "first close through its threshold and holds cash to the next rebalance; "
            "the name is out until a rebalance has excluded it. Medians across "
            "offsets; the worst single-name day is the smallest weight-times-return "
            "over names, min over the window, median across offsets; the false-alarm "
            "rate is the pooled share of triggers whose name closed above the "
            "trigger price within `recovery_sessions`; paired statistics at the "
            "median offset against the control."
        ),
    }
    for cost in costs:
        priced: list[dict[str, Priced]] = []
        for k in range(int(offsets)):
            since = _since(panel, k)
            priced.append(
                {v.name: price(restricted, mask, v, since, cost) for v in VARIANTS}
            )
        payload["rows"].extend(summarise(priced, cost))
        payload["paired"].extend(paired(priced, cost))
        if cost == verdict_cost:
            median = priced[len(priced) // 2]
            payload["triggers"] = {
                name: [tr.as_dict() for tr in run.triggers]
                for name, run in median.items()
            }
    payload["ran"] = [v.name for v in VARIANTS]
    return payload


# The row for a line and window at a cost, or None.
def _row(payload: dict[str, Any], line: str, window: str, cost: float) -> dict | None:
    for r in payload["rows"]:
        if r["line"] == line and r["window"] == window and float(r["cost_bps"]) == cost:
            return r
    return None


# The paired entry for a line against the control in a window at a cost, or None.
def _pair(payload: dict[str, Any], line: str, window: str, cost: float) -> dict | None:
    for p in payload["paired"]:
        if (
            p["line"] == line
            and p["against"] == NONE
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


# The verdict: for every stop, the CAGR points it costs (negative) or earns
# against the control on the choosing window at 25 bp, the drawdown points
# it saves, the fraction it cuts from the worst single-name day, whether it
# is not worse on the reported window by paired bp a day, and the decision:
# ADOPT (registered) when the cost is within MAX_COST_POINTS and either
# saving clears its floor and the reported window is not worse, else
# RECORD. The insurance premium is CAGR points given up per point of
# drawdown saved (NaN when nothing was saved or nothing given up).
def verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the verdict block for the payload."""
    costs = [float(c) for c in payload.get("costs_bps", [])]
    cost = (
        VERDICT_COST_BPS
        if VERDICT_COST_BPS in costs
        else (max(costs) if costs else math.nan)
    )
    control = _row(payload, NONE, CHOOSING, cost) or {}
    control_later = _row(payload, NONE, REPORTED, cost) or {}
    control_cagr = _f(control.get("median_cagr"))
    control_dd = _f(control.get("median_drawdown"))
    control_worst = _f(control.get("worst_name_day"))
    stops: dict[str, dict[str, Any]] = {}
    adopt: list[str] = []
    record: list[str] = []
    for v in VARIANTS:
        if v.mode == NONE:
            continue
        row = _row(payload, v.name, CHOOSING, cost) or {}
        later = _row(payload, v.name, REPORTED, cost) or {}
        pair = _pair(payload, v.name, CHOOSING, cost) or {}
        later_pair = _pair(payload, v.name, REPORTED, cost) or {}
        points = (_f(row.get("median_cagr")) - control_cagr) * 100.0
        # Drawdowns are negative; a smaller loss is a positive saving.
        dd_saved = (_f(row.get("median_drawdown")) - control_dd) * 100.0
        worst = _f(row.get("worst_name_day"))
        worst_cut = (
            1.0 - worst / control_worst
            if np.isfinite(worst) and np.isfinite(control_worst) and control_worst < 0
            else math.nan
        )
        later_points = (
            _f(later.get("median_cagr")) - _f(control_later.get("median_cagr"))
        ) * 100.0
        later_bp = _f(later_pair.get("mean_daily_bp"))
        measured = bool(np.isfinite(points))
        affordable = bool(measured and points >= -MAX_COST_POINTS)
        saves = bool(
            (np.isfinite(dd_saved) and dd_saved >= DRAWDOWN_POINTS)
            or (np.isfinite(worst_cut) and worst_cut >= WORST_DAY_CUT)
        )
        not_worse = bool(np.isfinite(later_bp) and later_bp >= 0.0)
        decision = ADOPT if affordable and saves and not_worse else RECORD
        premium = (
            -points / dd_saved
            if np.isfinite(points)
            and np.isfinite(dd_saved)
            and dd_saved > 0
            and points < 0
            else math.nan
        )
        stops[v.name] = {
            "mode": v.mode,
            "threshold": v.threshold,
            "measured": measured,
            "choosing_points": points,
            "choosing_bp_vs_control": _f(pair.get("mean_daily_bp")),
            "choosing_t_vs_control": _f(pair.get("hac_t")),
            "drawdown_points_saved": dd_saved,
            "worst_name_day": worst,
            "worst_name_day_cut": worst_cut,
            "triggers_per_year": _f(row.get("triggers_per_year")),
            "false_alarm_rate": _f(row.get("false_alarm_rate")),
            "reported_points": later_points,
            "reported_bp_vs_control": later_bp,
            "affordable": affordable,
            "saves": saves,
            "not_worse_reported": not_worse,
            "insurance_premium": premium,
            "decision": decision,
        }
        (adopt if decision == ADOPT else record).append(v.name)
    if not np.isfinite(control_cagr):
        text = f"not measured: the control has no {CHOOSING} CAGR at {cost:g} bp"
    else:
        parts = [
            f"{name} {_signed(info['choosing_points'], 1)} pt, DD "
            f"{_signed(info['drawdown_points_saved'], 1)} pt, worst day "
            f"{_signed(info['worst_name_day_cut'] * 100, 0)}%, premium "
            f"{_signed(info['insurance_premium'])} {info['decision']}"
            for name, info in stops.items()
        ]
        text = (
            f"{CHOOSING} at {cost:g} bp: control {control_cagr * 100:.1f}% CAGR, "
            f"median max drawdown {control_dd * 100:.1f}%, worst single-name day "
            f"{control_worst * 100:.2f}%. Stops (CAGR points vs control, drawdown "
            f"points saved, worst-day cut, CAGR points per drawdown point): "
            + "; ".join(parts)
            + ". "
            + (
                f"{ADOPT}: {', '.join(adopt)}."
                if adopt
                else (
                    f"No stop is within {MAX_COST_POINTS:g} pt of the control while "
                    f"saving {DRAWDOWN_POINTS:g} drawdown points or "
                    f"{WORST_DAY_CUT * 100:.0f}% of the worst single-name day and "
                    f"not worse on {REPORTED}; every stop is {RECORD}."
                )
            )
        )
    return {
        "cost_bps": cost,
        "choosing_window": CHOOSING,
        "reported_window": REPORTED,
        "floors": {
            "max_cost_points": MAX_COST_POINTS,
            "drawdown_points": DRAWDOWN_POINTS,
            "worst_day_cut": WORST_DAY_CUT,
        },
        "control_cagr": control_cagr,
        "control_drawdown": control_dd,
        "control_worst_name_day": control_worst,
        "stops": stops,
        "adopt": adopt,
        "record": record,
        "text": text,
    }
