"""The execution ablation: the live policy's options switched off one at a time on the `/4` book.

The graded equal-weight policy (`policy_v4.allocator(mask)`) earns 27.7% a
year on 2016-2023 at 25 bp with plain next-open fills and 23.3% under the
live execution policy (`simulate.LIVE_POLICY` plus the FOMC path and
lifecycle - `market_pit_scorecard._live_options`). The fill-timing trial
(`docs/research/execution-timing-2026-09-27.md`) showed the band gate on
buys alone is neutral, so the 4.4 points come from the other conventions.
This module prices the policy under a fixed, named set of option sets -
plain, live, live with each option removed, plain with one option added -
on identical sessions at every offset of the 20-session clock, and reports
each variant against both ends: plain (the fills the fill-timing trial
priced) and live (the account). Every variant is one registered trial;
`VARIANTS` is fixed here before any run, and the payload counts them.

`verdict` reads the choosing window (2016-2023) at 25 bp: the CAGR points
each option's removal earns or costs relative to live (positive = removing
it helps), the recommendation under the floors below, and the
reconstruction check - the sum of the single-removal effects against the
plain-minus-live gap - so an interaction between options is visible rather
than assumed away. Nothing here trades or changes the executor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.agents.trading.desk import (
    event_risk,
    paper,
    point_in_time,
    policy_v4,
    simulate,
)
from backend.cli import market_pit_scorecard as scorecard
from backend.cli.market_pit_scorecard import WINDOWS, Curve, _on, _since, window_stats
from backend.market import candidate_stats

PLAIN = "plain"
LIVE = "live"
# The options the live policy adds to plain fills, in the order they are
# removed. "event" is the pair `event_exposure=event_risk.live_path(panel)`
# and `event_lifecycle=True`, removed and added together.
LIVE_OPTIONS: tuple[str, ...] = (
    "block_overbought",
    "exit_at_close",
    "green_day_skip",
    "live_midcycle",
    "deferred_buys",
    "event",
)
EVENT = "event"
# The floors for a removal to be recommended: at least this many CAGR
# points on the choosing window at 25 bp, with the paired daily difference
# against live at this Newey-West t, and not worse on the reported window.
REMOVE_POINTS = 1.0
REMOVE_T = 2.0
VERDICT_COST_BPS = 25.0
CHOOSING = "2016-2023"
REPORTED = "2024-2026"
HAC_LAG = 20
REMOVE = "REMOVE (registered)"
KEEP = "KEEP"


@dataclass(frozen=True)
class Variant:
    """One named option set: a base ("plain" or "live") with options removed or added."""

    name: str
    base: str
    removed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    note: str = ""


# Fixed before the run and named in the payload: the two ends, one variant
# per live option removed from the full set, and the additive direction
# from plain for the two options the fill-timing trial could not price.
VARIANTS: tuple[Variant, ...] = (
    Variant(
        PLAIN,
        PLAIN,
        note="use_exits=False, rebalance=paper.REBALANCE_EVERY, next-open fills, nothing else",
    ),
    Variant(
        LIVE,
        LIVE,
        note="the full live execution policy: market_pit_scorecard._live_options",
    ),
    Variant(
        "live-block_overbought",
        LIVE,
        removed=("block_overbought",),
        note="live without the band gate on buys",
    ),
    Variant(
        "live-exit_at_close",
        LIVE,
        removed=("exit_at_close", "deferred_buys"),
        note=(
            "live with sells at the open instead of the close; deferred_buys "
            "is dropped too because simulate.run refuses it without exit_at_close, "
            "so this variant measures both together"
        ),
    ),
    Variant(
        "live-green_day_skip",
        LIVE,
        removed=("green_day_skip",),
        note="live without holding a sell back on a green open",
    ),
    Variant(
        "live-live_midcycle",
        LIVE,
        removed=("live_midcycle",),
        note="live without the mid-cycle band entries",
    ),
    Variant(
        "live-deferred_buys",
        LIVE,
        removed=("deferred_buys",),
        note="live without the deferred buy leg",
    ),
    Variant(
        "live-event",
        LIVE,
        removed=(EVENT,),
        note="live without the FOMC exposure path and lifecycle",
    ),
    Variant(
        "plain+exit_at_close",
        PLAIN,
        added=("exit_at_close",),
        note="plain fills with sells at the close",
    ),
    Variant(
        "plain+event",
        PLAIN,
        added=(EVENT,),
        note="plain fills with the FOMC exposure path and lifecycle",
    ),
)


# The plain option set: no exit overlay, the live reset cadence, and
# every execution flag at the simulator's default (next-open fills).
def plain_options() -> dict[str, Any]:
    """Return the `simulate.run` keyword options for plain next-open fills."""
    return dict(use_exits=False, rebalance=paper.REBALANCE_EVERY)


# The live option set, exactly as the scorecard prices the account.
def live_options(panel) -> dict[str, Any]:
    """Return the `simulate.run` keyword options of the live execution policy."""
    return scorecard._live_options(panel)


# Apply one option's removal or addition to an options dict in place.
# A LIVE_POLICY key is set False (removed) or True (added); "event" sets
# the pair `event_exposure` / `event_lifecycle`.
def _toggle(options: dict[str, Any], option: str, on: bool, panel) -> None:
    if option == EVENT:
        options["event_exposure"] = event_risk.live_path(panel) if on else None
        options["event_lifecycle"] = bool(on)
    elif option in simulate.LIVE_POLICY:
        options[option] = bool(on)
    else:
        raise KeyError(f"unknown execution option {option!r}")


# The `simulate.run` keyword options of a variant on a panel: its base set
# with the named options removed or added and nothing else changed.
def variant_options(variant: Variant, panel) -> dict[str, Any]:
    """Return the options dict `simulate.run` receives for `variant`."""
    if variant.base == PLAIN:
        options = plain_options()
    elif variant.base == LIVE:
        options = live_options(panel)
    else:
        raise ValueError(f"unknown base {variant.base!r}")
    for option in variant.removed:
        _toggle(options, option, False, panel)
    for option in variant.added:
        _toggle(options, option, True, panel)
    return options


# The variant by name, or KeyError.
def variant(name: str) -> Variant:
    """Return the registered variant called `name`."""
    for v in VARIANTS:
        if v.name == name:
            return v
    raise KeyError(name)


# An options dict as JSON-able text: the FOMC path is named, not listed.
def _describe(options: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in options.items():
        if key == "event_exposure":
            out[key] = None if value is None else "event_risk.live_path(panel)"
        else:
            out[key] = value
    return out


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


# Price one variant from one offset at one cost: `simulate.run` on the
# restricted report with the policy's allocator and the variant's options.
def price(
    restricted, mask: np.ndarray, variant_: Variant, since, cost_bps: float
) -> Curve:
    """Return the variant's Curve from `since` at `cost_bps`."""
    panel = restricted.panel
    result = simulate.run(
        restricted,
        since=since,
        cost_bps=cost_bps,
        allocator=policy_v4.allocator(mask),
        **variant_options(variant_, panel),
    )
    return Curve(variant_.name, result.dates, result.returns)


# The reference calendar of one offset: the plain curve's sessions, else
# the first variant that ran.
def _calendar(offset: dict[str, Curve]) -> np.ndarray:
    if PLAIN in offset:
        return offset[PLAIN].dates
    return next(iter(offset.values())).dates


# One row per (variant, window) at one cost: medians, worsts and the count
# of offsets whose CAGR beats plain's on the same sessions. The field
# names are the pit scorecard's (`summarise`); `line` is the variant.
def summarise(priced: list[dict[str, Curve]], cost_bps: float) -> list[dict[str, Any]]:
    """Return the per-window rows across the offsets at `cost_bps`."""
    rows: list[dict[str, Any]] = []
    names = [v.name for v in VARIANTS if all(v.name in offset for offset in priced)]
    for window, (start, end) in WINDOWS.items():
        stats: dict[str, list[dict[str, float]]] = {name: [] for name in names}
        for offset in priced:
            base = _calendar(offset)
            keep = point_in_time.window(base, start, end)
            for name in names:
                stats[name].append(window_stats(_on(base, offset[name])[keep]))
        plain_cagr = np.array([s["cagr"] for s in stats.get(PLAIN, [])], dtype=float)
        for name in names:
            cagrs = np.array([s["cagr"] for s in stats[name]], dtype=float)
            above = (
                int(np.nansum(cagrs > plain_cagr))
                if len(plain_cagr) == len(cagrs)
                else 0
            )
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
                    "offsets_above_plain": above,
                    "sessions": int(np.nanmedian([s["sessions"] for s in stats[name]])),
                }
            )
    return rows


# The paired daily difference of every variant against plain and against
# live at the median offset, per window: mean bp a day, Newey-West t at
# lag 20 and the probabilistic Sharpe. Field names are the scorecard's.
def paired(priced: list[dict[str, Curve]], cost_bps: float) -> list[dict[str, Any]]:
    """Return the paired rows at the median offset for `cost_bps`."""
    out: list[dict[str, Any]] = []
    offset = priced[len(priced) // 2]
    base = _calendar(offset)
    for window, (start, end) in WINDOWS.items():
        keep = point_in_time.window(base, start, end)
        for against in (PLAIN, LIVE):
            if against not in offset:
                continue
            b = _on(base, offset[against])[keep]
            for v in VARIANTS:
                if v.name == against or v.name not in offset:
                    continue
                a = _on(base, offset[v.name])[keep]
                diff = a - b
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
# `store` is accepted for the scorecard's call shape and is not read: no
# line here needs a benchmark. A variant `simulate.run` refuses is
# recorded under `refused` with the reason and left out of the rows - it
# is never silently skipped.
def run_variants(
    report, restricted, mask: np.ndarray, store, offsets: int, costs: tuple[float, ...]
) -> dict[str, Any]:
    """Return the ablation payload for the policy on the restricted report."""
    panel = restricted.panel
    refused: dict[str, str] = {}
    payload: dict[str, Any] = {
        "study": "execution_ablation",
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
                "base": v.base,
                "removed": list(v.removed),
                "added": list(v.added),
                "note": v.note,
                "options": _describe(variant_options(v, panel)),
            }
            for v in VARIANTS
        ],
        "hac_lag": HAC_LAG,
        "rows": [],
        "paired": [],
        "refused": refused,
        "note": (
            "Every variant is one registered trial, fixed in VARIANTS before the "
            "run. Lines priced on identical sessions from each of the first "
            "`offsets` sessions of the restricted report with policy_v4's allocator; "
            "medians and worsts are across offsets; paired statistics at the median "
            "offset against plain and against live."
        ),
    }
    for cost in costs:
        priced: list[dict[str, Curve]] = []
        for k in range(int(offsets)):
            since = _since(panel, k)
            offset: dict[str, Curve] = {}
            for v in VARIANTS:
                if v.name in refused:
                    continue
                try:
                    offset[v.name] = price(restricted, mask, v, since, float(cost))
                except ValueError as exc:
                    refused[v.name] = f"simulate.run refused: {exc}"
            priced.append(offset)
        # A variant refused at any offset is dropped from every offset so the
        # medians count the same runs everywhere.
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


# The verdict: for every option removed from live, the CAGR points its
# removal earns (positive) or costs (negative) on the choosing window at
# 25 bp relative to live, the paired t against live, and whether the
# removal is not worse on the reported window; REMOVE (registered) when
# the removal clears REMOVE_POINTS with t >= REMOVE_T and is not worse,
# else KEEP. The reconstruction check sums the single-removal effects and
# sets them against the plain-minus-live gap; the difference is the
# interaction between the options.
def verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the verdict block for the payload."""
    costs = [float(c) for c in payload.get("costs_bps", [])]
    cost = (
        VERDICT_COST_BPS
        if VERDICT_COST_BPS in costs
        else (max(costs) if costs else math.nan)
    )
    live_row = _row(payload, LIVE, CHOOSING, cost) or {}
    plain_row = _row(payload, PLAIN, CHOOSING, cost) or {}
    live_cagr = _f(live_row.get("median_cagr"))
    plain_cagr = _f(plain_row.get("median_cagr"))
    gap = (plain_cagr - live_cagr) * 100.0
    options: dict[str, dict[str, Any]] = {}
    remove: list[str] = []
    keep: list[str] = []
    total = 0.0
    for v in VARIANTS:
        if v.base != LIVE or not v.removed:
            continue
        row = _row(payload, v.name, CHOOSING, cost) or {}
        later_row = _row(payload, v.name, REPORTED, cost) or {}
        live_later = _row(payload, LIVE, REPORTED, cost) or {}
        pair = _pair(payload, v.name, LIVE, CHOOSING, cost) or {}
        later_pair = _pair(payload, v.name, LIVE, REPORTED, cost) or {}
        points = (_f(row.get("median_cagr")) - live_cagr) * 100.0
        later_points = (
            _f(later_row.get("median_cagr")) - _f(live_later.get("median_cagr"))
        ) * 100.0
        t = _f(pair.get("hac_t"))
        later_bp = _f(later_pair.get("mean_daily_bp"))
        measured = bool(np.isfinite(points))
        passes = bool(
            measured and points >= REMOVE_POINTS and np.isfinite(t) and t >= REMOVE_T
        )
        not_worse = bool(np.isfinite(later_bp) and later_bp >= 0.0)
        decision = REMOVE if passes and not_worse else KEEP
        options[v.name] = {
            "removed": list(v.removed),
            "measured": measured,
            "refused": payload.get("refused", {}).get(v.name),
            "choosing_points": points,
            "choosing_bp_vs_live": _f(pair.get("mean_daily_bp")),
            "choosing_t_vs_live": t,
            "reported_points": later_points,
            "reported_bp_vs_live": later_bp,
            "passes_choosing": passes,
            "not_worse_reported": not_worse,
            "decision": decision,
        }
        (remove if decision == REMOVE else keep).append(v.name)
        if measured:
            total += points
    interaction = gap - total
    if not np.isfinite(gap):
        text = (
            f"not measured: plain or live has no {CHOOSING} CAGR at {cost:g} bp "
            f"(refused: {sorted(payload.get('refused', {})) or 'none'})"
        )
    else:
        parts = [
            f"{name} {_signed(info['choosing_points'], 1)} pt "
            f"(t {_signed(info['choosing_t_vs_live'])}) {info['decision']}"
            for name, info in options.items()
        ]
        text = (
            f"{CHOOSING} at {cost:g} bp: plain {plain_cagr * 100:.1f}% against live "
            f"{live_cagr * 100:.1f}% (gap {gap:+.1f} pt). Single removals: "
            + "; ".join(parts)
            + f". Reconstruction: single removals sum to {total:+.1f} pt against the "
            f"{gap:+.1f} pt gap (interaction {interaction:+.1f} pt). "
            + (
                f"{REMOVE}: {', '.join(remove)}."
                if remove
                else f"No removal clears {REMOVE_POINTS:g} pt with t >= {REMOVE_T:g} and not worse on {REPORTED}; every option is KEEP."
            )
        )
    return {
        "cost_bps": cost,
        "choosing_window": CHOOSING,
        "reported_window": REPORTED,
        "floors": {"points": REMOVE_POINTS, "hac_t": REMOVE_T},
        "plain_cagr": plain_cagr,
        "live_cagr": live_cagr,
        "gap_points": gap,
        "options": options,
        "sum_of_single_removals": total,
        "interaction_points": interaction,
        "remove": remove,
        "keep": keep,
        "text": text,
    }
