"""The universe-expansion registration's criteria, read off the scorecard payloads.

`docs/research/universe-expansion-plan-2026-09-30.md` fixes six PASS
criteria for the U-sector arm at 25 bp against the book-94 control, each
a number the `market_pit_scorecard` payloads carry: the summary rows
(median and per-offset CAGR, worst drawdown), the concentration block
(worst single-name day), the candidates block (sessions with fewer than
five A/A+ names) and the median-offset daily curves, from which the
paired difference against the control, its Newey-West t and its deflated
Sharpe are computed here. U-flat and U-tone are reported against the same
criteria and cannot pass on their own; the module reports, the plan says
what a PASS does.

Everything here is arithmetic on the payloads: no store, no desk, so the
write-up's numbers can be recomputed from the committed files alone.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from backend.market import candidate_stats

RULE_PIT = "rule / point-in-time"
EW_PIT = "equal weight / point-in-time"
DECIDING = "2016-2023"
RECENT = "2024-2026"
ALL = "all"
COST = 25.0
# The criteria, as registered.
CAGR_LEAD = 0.02
HAC_T = 2.0
HAC_LAG = 20
OFFSETS_ABOVE = 15
DRAWDOWN_TOLERANCE = 0.03
FEW_SHARE = 0.05
CUMULATIVE_TRIALS = 457
DEFLATED_SHARPE = 0.95
PRIMARY = "sector"


# The (line, window) summary row of a payload at the registration's cost.
def row(payload: dict, line: str, window: str, cost: float = COST) -> dict:
    """Return the summary row, or raise when the payload lacks it."""
    for r in payload["rows"]:
        if r["line"] == line and r["window"] == window and float(r["cost_bps"]) == cost:
            return r
    raise KeyError(f"no row for {line!r} {window!r} at {cost:g} bp")


# The median-offset daily returns of `line` on `window`, paired session by
# session between two payloads (dates matched, both finite).
def paired_daily(
    a: dict, b: dict, line: str, window: str, cost: float = COST
) -> tuple[np.ndarray, np.ndarray]:
    """Return (a_daily, b_daily) on the sessions both payloads price in `window`."""
    start, end = a["windows"][window]
    ca, cb = a["curves"][f"{cost:g}"], b["curves"][f"{cost:g}"]
    by_date = dict(zip(cb["dates"], cb["lines"][line], strict=True))
    xs, ys = [], []
    for day, value in zip(ca["dates"], ca["lines"][line], strict=True):
        if start is not None and day < start:
            continue
        if end is not None and day >= end:
            continue
        other = by_date.get(day)
        if other is None:
            continue
        if value is None or other is None:
            continue
        if not (math.isfinite(value) and math.isfinite(other)):
            continue
        xs.append(value)
        ys.append(other)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


# The paired difference (arm minus control) of the rule line on a window:
# its length, mean in bp/day, Newey-West t at lag 20, per-period Sharpe,
# skew and kurtosis (for the deflated Sharpe) and PSR.
def paired_difference(arm: dict, control: dict, window: str = DECIDING) -> dict:
    """Return the statistics of the arm's rule line minus the control's."""
    a, b = paired_daily(arm, control, RULE_PIT, window)
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
        "psr": candidate_stats.probabilistic_sharpe(
            mom.sharpe, mom.length, mom.skew, mom.kurtosis
        ),
        "annualised_sharpe": mom.sharpe * math.sqrt(252.0)
        if math.isfinite(mom.sharpe)
        else math.nan,
    }


# One arm against the control on every registered criterion. `trial_variance`
# is the across-arm variance of the paired-difference Sharpes (supplied by
# `judge`, which sees every arm); NaN leaves criterion 6 unjudged.
def criteria(arm: dict, control: dict, trial_variance: float) -> dict[str, Any]:
    """Return {"c1".."c6": {...}, "pass": bool} for the arm."""
    out: dict[str, Any] = {}
    # 1. CAGR lead on both windows, median across offsets.
    leads = {
        w: row(arm, RULE_PIT, w)["median_cagr"]
        - row(control, RULE_PIT, w)["median_cagr"]
        for w in (DECIDING, RECENT)
    }
    out["c1"] = {
        "name": f"median CAGR lead >= {CAGR_LEAD:.1%} on both windows",
        "lead": leads,
        "ok": all(math.isfinite(v) and v >= CAGR_LEAD for v in leads.values()),
    }
    # 2. Paired difference against the control, deciding window.
    paired = paired_difference(arm, control, DECIDING)
    out["c2"] = {
        "name": f"paired daily difference NW t >= {HAC_T} on {DECIDING}",
        "paired": paired,
        "ok": math.isfinite(paired["hac_t"]) and paired["hac_t"] >= HAC_T,
    }
    # 3. Offsets above the control, deciding window.
    own = np.asarray(row(arm, RULE_PIT, DECIDING)["cagrs"], dtype=float)
    theirs = np.asarray(row(control, RULE_PIT, DECIDING)["cagrs"], dtype=float)
    above = int(np.nansum(own > theirs)) if len(own) == len(theirs) else 0
    out["c3"] = {
        "name": f"above the control on >= {OFFSETS_ABOVE} of {len(theirs)} offsets",
        "above": above,
        "offsets": int(len(theirs)),
        "ok": len(own) == len(theirs) and above >= OFFSETS_ABOVE,
    }
    # 4. Worst drawdown (all) and worst single-name day per window.
    dd_arm = row(arm, RULE_PIT, ALL)["worst_drawdown"]
    dd_control = row(control, RULE_PIT, ALL)["worst_drawdown"]
    worst_days = {
        w: (
            arm["concentration"][w].get("worst_single_name_day", math.nan),
            control["concentration"][w].get("worst_single_name_day", math.nan),
        )
        for w in (DECIDING, RECENT)
    }
    out["c4"] = {
        "name": f"worst drawdown not worse by > {DRAWDOWN_TOLERANCE:.0%}; "
        "worst single-name day not worse on either window",
        "worst_drawdown": {"arm": dd_arm, "control": dd_control},
        "worst_single_name_day": {
            w: {"arm": a, "control": c} for w, (a, c) in worst_days.items()
        },
        "ok": math.isfinite(dd_arm)
        and dd_arm >= dd_control - DRAWDOWN_TOLERANCE
        and all(math.isfinite(a) and a >= c for a, c in worst_days.values()),
    }
    # 5. Sessions with fewer than five A/A+ names.
    shares = {
        w: arm["candidates"][w].get("share_below", math.nan) for w in (DECIDING, RECENT)
    }
    out["c5"] = {
        "name": f"sessions with fewer than five A/A+ names < {FEW_SHARE:.0%} on both windows",
        "share_below_five": shares,
        "control": {
            w: control["candidates"][w].get("share_below", math.nan)
            for w in (DECIDING, RECENT)
        },
        "ok": all(math.isfinite(v) and v < FEW_SHARE for v in shares.values()),
    }
    # 6. Deflated Sharpe of the paired difference at the cumulative count.
    dsr = math.nan
    if math.isfinite(trial_variance) and math.isfinite(paired["sharpe"]):
        dsr = candidate_stats.deflated_sharpe(
            paired["sharpe"],
            paired["length"],
            paired["skew"],
            paired["kurtosis"],
            CUMULATIVE_TRIALS,
            trial_variance,
        )
    out["c6"] = {
        "name": f"deflated Sharpe of the paired difference at {CUMULATIVE_TRIALS} trials >= {DEFLATED_SHARPE}",
        "dsr": dsr,
        "trials": CUMULATIVE_TRIALS,
        "trial_variance": trial_variance,
        "ok": math.isfinite(dsr) and dsr >= DEFLATED_SHARPE,
    }
    out["pass"] = all(out[k]["ok"] for k in ("c1", "c2", "c3", "c4", "c5", "c6"))
    return out


# The lines the write-up quotes for one payload: the rule and the hurdle
# per window at the registration's cost, with the concentration and the
# candidate counts.
def summary(payload: dict) -> dict[str, Any]:
    """Return the quoted numbers of one payload."""
    out: dict[str, Any] = {"book": payload.get("book"), "arm": payload.get("arm")}
    for w in (DECIDING, RECENT, ALL):
        lines = {}
        for line in (RULE_PIT, EW_PIT, "SPY", "QQQ"):
            r = row(payload, line, w)
            lines[line] = {
                "median_cagr": r["median_cagr"],
                "worst_cagr": r["worst_cagr"],
                "median_drawdown": r["median_drawdown"],
                "worst_drawdown": r.get("worst_drawdown", math.nan),
                "median_sharpe": r["median_sharpe"],
                "offsets_above_ew_pit": r["offsets_above_ew_pit"],
                "offsets_above_qqq": r["offsets_above_qqq"],
            }
        out[w] = {
            "lines": lines,
            "concentration": payload.get("concentration", {}).get(w),
            "candidates": payload.get("candidates", {}).get(w),
        }
    out["paired_within_run"] = [
        p
        for p in payload["paired"]
        if float(p["cost_bps"]) == COST
        and p["line"] == RULE_PIT
        and p["against"] == EW_PIT
    ]
    return out


# Every arm against the control, with the across-arm trial variance for
# the deflated Sharpe, and the verdict word for each: PASS only for the
# primary arm when every criterion holds, RECORD otherwise.
def judge(control: dict, arms: dict[str, dict]) -> dict[str, Any]:
    """Return {"control": summary, "arms": {name: {...}}, "verdict": {name: word}}."""
    sharpes = np.array(
        [paired_difference(a, control)["sharpe"] for a in arms.values()], dtype=float
    )
    sharpes = sharpes[np.isfinite(sharpes)]
    variance = float(sharpes.var(ddof=1)) if len(sharpes) >= 2 else math.nan
    out: dict[str, Any] = {
        "cost_bps": COST,
        "trial_variance": variance,
        "control": summary(control),
        "arms": {},
        "verdict": {},
    }
    for name, payload in arms.items():
        result = criteria(payload, control, variance)
        out["arms"][name] = {"summary": summary(payload), "criteria": result}
        out["verdict"][name] = (
            "PASS" if (result["pass"] and name == PRIMARY) else "RECORD"
        )
        if result["pass"] and name != PRIMARY:
            out["verdict"][name] = "RECORD (meets the criteria; cannot pass on its own)"
    return out


# The verdict as lines a person reads.
def render(judged: dict) -> str:
    """Return the verdict text."""
    lines = [
        f"universe expansion, {judged['cost_bps']:g} bp, control = book-94 rule / point-in-time"
    ]
    control = judged["control"]
    for w in (DECIDING, RECENT):
        c = control[w]["lines"][RULE_PIT]
        lines.append(
            f"  control {w}: median CAGR {c['median_cagr']:.1%}, worst DD {c['worst_drawdown']:.1%}"
        )
    for name, arm in judged["arms"].items():
        cr = arm["criteria"]
        lines.append(f"\n{name}: {judged['verdict'][name]}")
        for w in (DECIDING, RECENT):
            r = arm["summary"][w]["lines"][RULE_PIT]
            lines.append(
                f"  {w}: median CAGR {r['median_cagr']:.1%} (lead {cr['c1']['lead'][w]:+.1%}), "
                f"worst DD {r['worst_drawdown']:.1%}, sessions < 5 A/A+ {cr['c5']['share_below_five'][w]:.1%}"
            )
        p = cr["c2"]["paired"]
        lines.append(
            f"  paired vs control {DECIDING}: {p['mean_daily_bp']:+.1f} bp/day, NW t {p['hac_t']:.2f}, "
            f"PSR {p['psr']:.2f}, DSR@{cr['c6']['trials']} {cr['c6']['dsr']:.2f}"
        )
        lines.append(
            f"  offsets above control {DECIDING}: {cr['c3']['above']} of {cr['c3']['offsets']}"
        )
        for k in ("c1", "c2", "c3", "c4", "c5", "c6"):
            lines.append(f"  {k} {'ok  ' if cr[k]['ok'] else 'FAIL'} {cr[k]['name']}")
    return "\n".join(lines)
