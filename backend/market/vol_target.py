"""Volatility targeting of the book (B1): the gross path, and the verdict.

The plan (`docs/research/vol-target-plan-2026-10-01.md`, registered before
any code) fixes the rule and the criteria; nothing here restates either in
a way the plan does not. The rule: gross(t) = min(1, σ* ÷ σ̂(t)), where
σ̂(t) is the annualised standard deviation of the book's own daily
returns at gross 1 over the last `window` sessions known at the close of
t−1, applied to the targets decided at t's close and filled at t+1's open;
the weights are the policy's, scaled; cash earns nothing; the rescaling
trades pay the same cost. `gross_path` turns a gross-1 return series into
that path; `simulate.run(gross_path=...)` applies it; the point-in-time
scorecard (`market_pit_scorecard --gross-target`) runs the gross-1 book
first and the scaled book second on the same sessions, costs and offsets,
so σ̂ is point in time by construction.

Reported beside the three registered targets and deciding nothing: Xu's
two switches. `switch_return`: gross 0 when the gross-1 book's trailing
`switch_window` (120)-session return is negative. `switch_intercept`: no
scaling (gross 1) when the intercept of the trailing `switch_window`-session
regression of the gross-1 book's daily return on its lagged σ̂² is
negative. Both read only sessions through t−1. When both fire the return
switch wins (the book is in cash). The 120-session window is a build
convention; the plan names the switches without one.

The verdict (`verdict`) pairs a target's scorecard payload with the
control's: per window the median worst drawdown and CAGR against the
control, the Sharpe, the paired daily difference's Newey-West t at lag
20, the offsets above the control, and the deflated Sharpe at the
cumulative 474 (reported, deciding nothing). REPLACES on the plan's
drawdown trade (worst drawdown better by at least 5 points on both windows
with the CAGR down by at most 3 points on each) or its Sharpe trade (+0.15
on both windows with the drawdown not worse), and in either case the
paired daily difference not negative at NW t ≤ −2 on either window.
Anything else is RECORD.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.market import candidate_stats

PLAN = "docs/research/vol-target-plan-2026-10-01.md"
STUDY = "vol_target"
ANNUALISATION = 252
WINDOW = 20
SWITCH_WINDOW = 120
# The three registered targets, a year, fixed by the plan; the rest are reported.
REGISTERED = (0.20, 0.25, 0.30)
REPORTED_TARGETS = (0.15,)
REPORTED_WINDOW = 60
# The criteria, fixed by the plan.
DRAWDOWN_POINTS = 0.05
CAGR_GIVE_UP = 0.03
SHARPE_POINTS = 0.15
NEGATIVE_T = -2.0
# "The drawdown not worse": equal to floating-point precision counts.
NOT_WORSE_TOLERANCE = 1e-12
# Newey-West lag and the deflated-Sharpe gate, as stage 4 fixed them
# (`stage4_decisions.HAC_LAG`, `DSR_GATE`; not imported, since that module
# reaches the scorecard, which reaches this one).
HAC_LAG = 20
DSR_GATE = 0.95
TRIALS = {"registered": 3, "cumulative": 474}
DECIDING = "2016-2023"
RECENT = "2024-2026"
WINDOWS = (DECIDING, RECENT)
COST_BPS = 25.0
RULE_LINE = "rule / point-in-time"
REPLACES = "REPLACES"
RECORD = "RECORD"

assert TRIALS["registered"] == len(REGISTERED)


@dataclass(frozen=True)
class Spec:
    """One volatility-target variant: σ* a year, the σ̂ window, the switches."""

    target: float  # a year; math.inf is the null test
    window: int = WINDOW
    switch_return: bool = False
    switch_intercept: bool = False
    switch_window: int = SWITCH_WINDOW

    # The file tag and payload name of this variant: "vt25" for 25% at the
    # default window, "vt25_w60", "vt25_sr", "vt25_si"; "vtinf" for the null.
    @property
    def tag(self) -> str:
        """Return the variant's tag."""
        pct = "inf" if math.isinf(self.target) else f"{round(self.target * 100):02d}"
        tag = f"vt{pct}"
        if self.window != WINDOW:
            tag += f"_w{self.window}"
        if self.switch_return:
            tag += "_sr"
        if self.switch_intercept:
            tag += "_si"
        return tag

    # The payload's record of the variant.
    def record(self) -> dict[str, Any]:
        """Return the variant as a JSON-ready dict."""
        return {
            "target": self.target,
            "window": self.window,
            "switch_return": self.switch_return,
            "switch_intercept": self.switch_intercept,
            "switch_window": self.switch_window,
            "annualisation": ANNUALISATION,
            "tag": self.tag,
            "registered": (
                not self.switch_return
                and not self.switch_intercept
                and self.window == WINDOW
                and any(math.isclose(self.target, r) for r in REGISTERED)
            ),
        }


# σ̂ on the panel's calendar: out[t] is the annualised sample standard
# deviation of returns[t-window .. t-1], the `window` returns known at the
# close of t−1, and NaN until that many finite returns precede t (the book
# before its first fill has none; a NaN inside the window leaves σ̂
# undefined for that session rather than estimated on fewer).
def sigma_hat(returns: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """Return the (T,) annualised trailing standard deviation known at t−1."""
    r = np.asarray(returns, dtype=float)
    out = np.full(len(r), np.nan)
    if window < 2:
        raise ValueError("the window needs at least two sessions")
    for t in range(window, len(r)):
        block = r[t - window : t]
        if np.isfinite(block).all():
            out[t] = float(block.std(ddof=1)) * math.sqrt(ANNUALISATION)
    return out


# Xu's return switch on the calendar: True at t when the gross-1 book's
# compounded return over sessions t-window .. t-1 is negative (every one
# finite); False where the window is not yet full.
def return_switch(returns: np.ndarray, window: int = SWITCH_WINDOW) -> np.ndarray:
    """Return the (T,) mask of sessions whose trailing book return is negative."""
    r = np.asarray(returns, dtype=float)
    out = np.zeros(len(r), dtype=bool)
    for t in range(window, len(r)):
        block = r[t - window : t]
        if np.isfinite(block).all():
            out[t] = bool(np.prod(1.0 + block) - 1.0 < 0.0)
    return out


# Xu's intercept switch on the calendar: True at t when the ordinary
# least-squares intercept of r[s] on σ̂²[s] (daily variance, itself known
# at s−1) over s in t-window .. t-1 is negative, with every pair finite;
# False where the window is not full or the variance does not vary.
def intercept_switch(
    returns: np.ndarray, sigma: np.ndarray, window: int = SWITCH_WINDOW
) -> np.ndarray:
    """Return the (T,) mask of sessions whose trailing intercept is negative."""
    r = np.asarray(returns, dtype=float)
    v = (np.asarray(sigma, dtype=float) / math.sqrt(ANNUALISATION)) ** 2
    out = np.zeros(len(r), dtype=bool)
    for t in range(window, len(r)):
        y, x = r[t - window : t], v[t - window : t]
        if not (np.isfinite(y).all() and np.isfinite(x).all()):
            continue
        sx = float(x.var())
        if sx <= 0:
            continue
        slope = float(((x - x.mean()) * (y - y.mean())).mean() / sx)
        out[t] = bool(y.mean() - slope * x.mean() < 0.0)
    return out


# The gross path of a variant from the gross-1 book's daily returns on the
# panel's calendar: min(1, σ*/σ̂) where σ̂ is defined and positive, 1
# elsewhere (so an infinite target, or a book too young for a σ̂, is the
# control); then the switches. Returns (gross, σ̂).
def gross_path(returns: np.ndarray, spec: Spec) -> tuple[np.ndarray, np.ndarray]:
    """Return the (T,) gross in [0, 1] and the (T,) σ̂ the rule read."""
    if not (spec.target > 0):
        raise ValueError("the volatility target must be positive (inf for the null)")
    sigma = sigma_hat(returns, spec.window)
    gross = np.ones(len(sigma))
    defined = np.isfinite(sigma) & (sigma > 0)
    with np.errstate(divide="ignore", over="ignore"):
        gross[defined] = np.minimum(1.0, spec.target / sigma[defined])
    if spec.switch_intercept:
        gross[intercept_switch(returns, sigma, spec.switch_window)] = 1.0
    if spec.switch_return:
        gross[return_switch(returns, spec.switch_window)] = 0.0
    return gross, sigma


# --- the verdict against the control -----------------------------------------


# A payload number as a float: None (a NaN written to JSON) reads NaN.
def _f(value: Any) -> float:
    """Return `value` as a float, NaN for None."""
    return math.nan if value is None else float(value)


# A signed number for a verdict line, "n/a" when missing.
def _signed(x: Any, digits: int = 2) -> str:
    """Return `x` with its sign, "n/a" when missing."""
    v = _f(x)
    return f"{v:+.{digits}f}" if math.isfinite(v) else "n/a"


# The rule line's row of a payload at the study's cost on a window.
def _row(
    payload: Mapping[str, Any], window: str, cost: float = COST_BPS
) -> Mapping[str, Any]:
    """Return the matching row; KeyError when the payload has none."""
    for r in payload["rows"]:
        if (
            r["line"] == RULE_LINE
            and r["window"] == window
            and float(r["cost_bps"]) == cost
        ):
            return r
    raise KeyError(f"no {RULE_LINE!r} row for {window!r} at {cost:g} bp")


# The median-offset daily returns of the rule line on a window, paired
# session by session between two payloads (dates matched, both finite),
# as (candidate, control).
def paired_daily(
    candidate: Mapping[str, Any],
    control: Mapping[str, Any],
    window: str,
    cost: float = COST_BPS,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (candidate daily, control daily) on the sessions both price."""
    start, end = candidate["windows"][window]
    key = f"{cost:g}"
    a, b = candidate["curves"][key], control["curves"][key]
    theirs = dict(zip(b["dates"], b["lines"][RULE_LINE], strict=True))
    xs, ys = [], []
    for day, value in zip(a["dates"], a["lines"][RULE_LINE], strict=True):
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


# The paired difference (candidate minus control) on a window: its length,
# mean in bp a session, Newey-West t at lag 20, and the moments the
# deflated Sharpe needs.
def paired(
    candidate: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> dict[str, Any]:
    """Return the statistics of the candidate's rule line minus the control's."""
    a, b = paired_daily(candidate, control, window)
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


# The per-window reading of a target against the control, from the rows:
# median worst drawdown, CAGR and Sharpe for both, and the differences.
def window_reading(
    candidate: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> dict[str, float]:
    """Return the window's drawdown, CAGR and Sharpe of both and their differences."""
    a, b = _row(candidate, window), _row(control, window)
    f = _f
    return {
        "drawdown": f(a["median_drawdown"]),
        "drawdown_control": f(b["median_drawdown"]),
        # Positive when the candidate's worst drawdown is shallower.
        "drawdown_gain": f(a["median_drawdown"]) - f(b["median_drawdown"]),
        "cagr": f(a["median_cagr"]),
        "cagr_control": f(b["median_cagr"]),
        "cagr_difference": f(a["median_cagr"]) - f(b["median_cagr"]),
        "sharpe": f(a["median_sharpe"]),
        "sharpe_control": f(b["median_sharpe"]),
        "sharpe_difference": f(a["median_sharpe"]) - f(b["median_sharpe"]),
    }


# The offsets at which the candidate's CAGR is above the control's on a
# window, from the rows' per-offset CAGRs; (above, offsets).
def offsets_above(
    candidate: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> tuple[int, int]:
    """Return (offsets above the control, offsets compared)."""
    own = np.asarray(_row(candidate, window)["cagrs"], dtype=float)
    theirs = np.asarray(_row(control, window)["cagrs"], dtype=float)
    if len(own) != len(theirs):
        return 0, int(len(theirs))
    return int(np.nansum(own > theirs)), int(len(theirs))


# One target's verdict from its payload and the control's. `trial_variance`
# is the variance of the paired-difference Sharpes across the registered
# targets (NaN leaves the deflated Sharpe unjudged; it is reported either
# way and decides nothing); `trials` is the cumulative count the deflated
# Sharpe is taken at (a study reusing this verdict passes its own).
def verdict(
    candidate: Mapping[str, Any],
    control: Mapping[str, Any],
    trial_variance: float = math.nan,
    trials: int = TRIALS["cumulative"],
) -> dict[str, Any]:
    """Return the target's verdict record."""
    spec = candidate.get("vol_target", {})
    readings = {w: window_reading(candidate, control, w) for w in WINDOWS}
    pairs = {w: paired(candidate, control, w) for w in WINDOWS}
    above, offsets = offsets_above(candidate, control, DECIDING)
    deciding = pairs[DECIDING]
    dsr = math.nan
    if math.isfinite(trial_variance) and math.isfinite(deciding["sharpe"]):
        dsr = candidate_stats.deflated_sharpe(
            deciding["sharpe"],
            deciding["length"],
            deciding["skew"],
            deciding["kurtosis"],
            trials,
            trial_variance,
        )
    drawdown_trade = all(
        math.isfinite(r["drawdown_gain"])
        and r["drawdown_gain"] >= DRAWDOWN_POINTS
        and math.isfinite(r["cagr_difference"])
        and r["cagr_difference"] >= -CAGR_GIVE_UP
        for r in readings.values()
    )
    sharpe_trade = all(
        math.isfinite(r["sharpe_difference"])
        and r["sharpe_difference"] >= SHARPE_POINTS
        and math.isfinite(r["drawdown_gain"])
        and r["drawdown_gain"] >= -NOT_WORSE_TOLERANCE
        for r in readings.values()
    )
    not_negative = all(
        not (math.isfinite(p["hac_t"]) and p["hac_t"] <= NEGATIVE_T)
        for p in pairs.values()
    )
    on = [
        name
        for name, ok in (("drawdown", drawdown_trade), ("sharpe", sharpe_trade))
        if ok
    ]
    label = REPLACES if on and not_negative else RECORD
    reading = {
        "label": label,
        "replaces_on": on if label == REPLACES else [],
        "drawdown_trade": drawdown_trade,
        "sharpe_trade": sharpe_trade,
        "not_negative": not_negative,
        "windows": readings,
        "paired": pairs,
        "offsets_above": above,
        "offsets": offsets,
        "dsr": dsr,
        "trials": trials,
        "trial_variance": trial_variance,
        "cost_bps": COST_BPS,
        "vol_target": dict(spec),
        "candidate_arm": candidate.get("arm"),
        "control_arm": control.get("arm"),
        "criteria": {
            "drawdown_points": DRAWDOWN_POINTS,
            "cagr_give_up": CAGR_GIVE_UP,
            "sharpe_points": SHARPE_POINTS,
            "negative_t": NEGATIVE_T,
            "hac_lag": HAC_LAG,
            "dsr_gate_reported": DSR_GATE,
        },
    }
    reading["lines"] = lines(reading)
    return reading


# A target's verdict as the registered lines: the paired evidence, each
# window's drawdown, CAGR and Sharpe against the control, the label.
def lines(reading: Mapping[str, Any]) -> list[str]:
    """Return the verdict as lines."""
    signed = _signed
    spec = reading.get("vol_target", {})
    if "target" in spec:
        target = spec["target"]
        name = "inf" if target is None or math.isinf(target) else f"{target * 100:.0f}%"
        extras = []
        if spec.get("window", WINDOW) != WINDOW:
            extras.append(f"{spec['window']}-session window")
        if spec.get("switch_return"):
            extras.append("return switch")
        if spec.get("switch_intercept"):
            extras.append("intercept switch")
        head = f"σ* = {name}" + (f" ({', '.join(extras)})" if extras else "")
    else:
        # A candidate that is not a volatility target (the regime-gross
        # study reuses this verdict): named by its arm.
        head = str(reading.get("candidate_arm") or "candidate")
    d, r = reading["paired"][DECIDING], reading["paired"][RECENT]
    out = [
        f"{head}: paired {DECIDING} {signed(d['mean_daily_bp'], 1)} bp/session "
        f"(t {signed(d['hac_t'])}) over {d['sessions']} sessions; {RECENT} "
        f"{signed(r['mean_daily_bp'], 1)} bp/session (t {signed(r['hac_t'])}); "
        f"above the control at {reading['offsets_above']} of {reading['offsets']} "
        f"offsets; deflated Sharpe {signed(reading['dsr'])} at {reading['trials']}"
    ]
    for window, v in reading["windows"].items():
        out.append(
            f"  {window}: median worst drawdown {v['drawdown'] * 100:+.1f}% against "
            f"{v['drawdown_control'] * 100:+.1f}% "
            f"({signed(v['drawdown_gain'] * 100, 1)} points); CAGR "
            f"{v['cagr'] * 100:+.1f}% against {v['cagr_control'] * 100:+.1f}% "
            f"({signed(v['cagr_difference'] * 100, 1)} points); Sharpe "
            f"{v['sharpe']:.2f} against {v['sharpe_control']:.2f} "
            f"({signed(v['sharpe_difference'])})"
        )
    if reading["label"] == REPLACES:
        out.append(f"  REPLACES gross 1.0 (on {', '.join(reading['replaces_on'])})")
    else:
        failed = []
        if not reading["drawdown_trade"]:
            failed.append("drawdown trade fails")
        if not reading["sharpe_trade"]:
            failed.append("Sharpe trade fails")
        if not reading["not_negative"]:
            failed.append(f"paired difference negative at t <= {NEGATIVE_T:g}")
        out.append(f"  RECORD ({'; '.join(failed)})")
    return out


# The variance of the paired-difference Sharpes across the registered
# targets' payloads (NaN with fewer than two), for the deflated Sharpe.
def trial_variance(
    candidates: Mapping[str, Mapping[str, Any]], control: Mapping[str, Any]
) -> float:
    """Return the across-target variance of the deciding window's paired Sharpe."""
    sharpes = [
        paired(c, control, DECIDING)["sharpe"]
        for c in candidates.values()
        if c.get("vol_target", {}).get("registered")
    ]
    sharpes = [s for s in sharpes if math.isfinite(s)]
    if len(sharpes) < 2:
        return math.nan
    return float(np.var(sharpes, ddof=1))
