"""Regime gross (B2): the day-type model's tail probability gates exposure.

The plan (`docs/research/regime-gross-plan-2026-10-01.md`, registered
before any code) fixes the rule and the criteria; nothing here restates
either in a way the plan does not. The rule: gross(t) = 1 when the
walk-forward day-type model's tail probability at the close of t−1 is
below a threshold θ (or undefined), else g_low; applied to the targets
decided at t's close and filled at t+1's open through the same
`simulate.run(gross_path=...)` mechanism as the volatility target
(`vol_target`), with the same cost on the rescaling trades.

The probability is point in time and produced here, not read from a file:
`tail_probability` builds the day-type study (`day_type.build`) on the
point-in-time book and scores it with `day_type.walk_forward` - a refit
every `day_type.REFIT` (63) sessions on an expanding window of rows whose
labels matured before the fit (purge of horizon + 22), the first fit after
`day_type.MIN_TRAIN` (750) sessions, each block's probabilities from the
model fit before it. `data/market/desk/day_type.json` stores no model and
no series. Fixed by the plan: horizon 1, the boosted model.

Reported beside the three registered pairs and deciding nothing: a pair
combined with B1's 25% target as the per-session minimum of the two
grosses (`Spec.combine_target`).

The verdict (`verdict`) is B1's trade (`vol_target.verdict`) measured
against two controls: the gross-1 control and the best registered B1
target (`best_registered`, read from B1's verdict file). REPLACES only when
both are cleared; a pair that clears the control alone is RECORD (does not
beat the vol target); anything else RECORD. The combination is reported
with the same readings and no label.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from backend.market import day_type, vol_target

PLAN = "docs/research/regime-gross-plan-2026-10-01.md"
STUDY = "regime_gross"
KEY = "regime_gross"  # the payload key a scaled scorecard payload carries
HORIZON = 1
MODEL = "hgb"
# The three registered (threshold, g_low) pairs, fixed by the plan.
REGISTERED = ((0.3, 0.5), (0.5, 0.5), (0.5, 0.0))
# The reported combination: this pair, with B1's target as a floor on the cut.
REPORTED_COMBINATION = (0.5, 0.5, 0.25)
# A threshold no probability reaches: the null test.
NULL_THRESHOLD = 1.0
TRIALS = {"registered": 3, "cumulative": 477}
REPLACES = vol_target.REPLACES
RECORD = vol_target.RECORD
RECORD_VOL_TARGET = "RECORD (does not beat the vol target)"
REPORTED = "REPORTED"
# The two emergency 2020 decisions the day-type study leaves out of the
# scheduled calendar (`market_day_type.build` makes the same choice).
UNSCHEDULED_FOMC = (date(2020, 3, 3), date(2020, 3, 15))

assert TRIALS["registered"] == len(REGISTERED)


@dataclass(frozen=True)
class Spec:
    """One regime-gross variant: the threshold, the low gross, the combination."""

    threshold: float
    g_low: float
    combine_target: float | None = None  # B1's σ* a year, or None
    horizon: int = HORIZON
    model: str = MODEL

    # The file tag and payload name: "rg30_g50" for θ 0.3 / g_low 0.5,
    # "rg50_g00", "rg100_g50" for the null, "rg50_g50_vt25" combined.
    @property
    def tag(self) -> str:
        """Return the variant's tag."""
        tag = f"rg{round(self.threshold * 100):02d}_g{round(self.g_low * 100):02d}"
        if self.combine_target is not None:
            tag += f"_vt{round(self.combine_target * 100):02d}"
        if self.horizon != HORIZON or self.model != MODEL:
            tag += f"_h{self.horizon}_{self.model}"
        return tag

    # Whether this variant is the null test (a threshold nothing reaches).
    @property
    def is_null(self) -> bool:
        """Return True when the threshold is at or above 1."""
        return self.threshold >= NULL_THRESHOLD

    # Whether this variant is one of the plan's registered pairs.
    @property
    def registered(self) -> bool:
        """Return True for a registered pair at the fixed horizon and model."""
        return (
            self.combine_target is None
            and self.horizon == HORIZON
            and self.model == MODEL
            and any(
                math.isclose(self.threshold, t) and math.isclose(self.g_low, g)
                for t, g in REGISTERED
            )
        )

    # The payload's record of the variant.
    def record(self) -> dict[str, Any]:
        """Return the variant as a JSON-ready dict."""
        return {
            "threshold": self.threshold,
            "g_low": self.g_low,
            "combine_target": self.combine_target,
            "horizon": self.horizon,
            "model": self.model,
            "tag": self.tag,
            "registered": self.registered,
            "null": self.is_null,
        }


# A "THRESH:GLOW" option as a Spec: both in [0, 1], the threshold may be 1.
def parse_pair(text: str, combine_target: float | None = None, **kw) -> Spec:
    """Return the Spec for "0.5:0.5"; ValueError when malformed."""
    try:
        left, right = text.split(":")
        threshold, g_low = float(left), float(right)
    except ValueError as err:
        raise ValueError(f"expected THRESH:GLOW, got {text!r}") from err
    if not (0.0 <= threshold <= 1.0) or not (0.0 <= g_low <= 1.0):
        raise ValueError(f"threshold and g_low must lie in [0, 1]: {text!r}")
    return Spec(threshold, g_low, combine_target, **kw)


@dataclass(frozen=True)
class Probability:
    """The point-in-time tail probability on the panel's calendar, with its record."""

    dates: np.ndarray
    probability: np.ndarray  # (T,) NaN before the first fit
    climatology: np.ndarray  # (T,) the trailing base rate at each fit
    labels: np.ndarray  # (T,) the label the model was scored on, for the record
    horizon: int
    model: str
    skill: float
    sessions: int

    # The payload's record of the series: its schedule and where it starts.
    def record(self) -> dict[str, Any]:
        """Return the series' provenance as a JSON-ready dict."""
        defined = np.flatnonzero(np.isfinite(self.probability))
        first = str(self.dates[defined[0]]) if len(defined) else None
        p = self.probability[np.isfinite(self.probability)]
        return {
            "horizon": self.horizon,
            "model": self.model,
            "refit_every": day_type.REFIT,
            "min_train": day_type.MIN_TRAIN,
            "purge": self.horizon + 22,
            "tail": day_type.TAIL,
            "trailing": day_type.TRAILING,
            "first_session": first,
            "defined_sessions": int(len(p)),
            "brier_skill": self.skill,
            "scored_sessions": self.sessions,
            "share_at_or_above": {
                f"{t:g}": float((p >= t).mean()) if len(p) else math.nan
                for t in sorted({thr for thr, _ in REGISTERED})
            },
            "max": float(p.max()) if len(p) else math.nan,
        }


# The sessions-to and sessions-since FOMC arrays the day-type features
# read, from the scheduled decisions on file (the two emergency 2020
# decisions left out, as the day-type study does).
def fomc_distances(dates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (ahead, since) on the panel's calendar."""
    from backend.market import calendar

    scheduled = [d for d in calendar.fomc_decisions() if d not in UNSCHEDULED_FOMC]
    return calendar._fomc_distances(dates, scheduled)


# The point-in-time tail probability of the restricted (point-in-time)
# report: the day-type study built on its mask and scored walk-forward.
# `study` lets a caller pass a built study (tests); otherwise it is built.
def tail_probability(
    restricted, mask: np.ndarray, horizon: int = HORIZON, model: str = MODEL, study=None
) -> Probability:
    """Return the Probability series for `horizon` under `model`."""
    if study is None:
        ahead, since = fomc_distances(restricted.panel.dates)
        study = day_type.build(restricted, mask, ahead, since)
    scored = day_type.walk_forward(study, horizon, model)
    return Probability(
        np.asarray(study.dates),
        np.asarray(scored.probability, dtype=float),
        np.asarray(scored.climatology, dtype=float),
        np.asarray(study.labels[horizon], dtype=float),
        horizon,
        model,
        scored.skill,
        scored.sessions,
    )


# The rule on the calendar: out[t] = g_low when probability[t-1] is finite
# and at or above the threshold, 1 otherwise (so the first session, a
# session after an undefined probability, and every session under the
# null threshold are the control). Returns (gross, the probability read).
def regime_path(probability: np.ndarray, spec: Spec) -> tuple[np.ndarray, np.ndarray]:
    """Return the (T,) gross in [0, 1] and the (T,) p(t−1) each session read."""
    p = np.asarray(probability, dtype=float)
    read = np.full(len(p), np.nan)
    read[1:] = p[:-1]
    gross = np.ones(len(p))
    fires = np.isfinite(read) & (read >= spec.threshold)
    gross[fires] = spec.g_low
    return gross, read


# The full gross path of a variant: the regime rule, and, when the variant
# combines with a volatility target, the per-session minimum with B1's
# gross from the gross-1 book's returns. Returns (gross, p read, σ̂ or
# None).
def gross_path(
    probability: np.ndarray, spec: Spec, unit_returns: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Return (gross, p(t−1), σ̂) on the calendar."""
    gross, read = regime_path(probability, spec)
    sigma = None
    if spec.combine_target is not None:
        if unit_returns is None:
            raise ValueError("the combination needs the gross-1 book's returns")
        target, sigma = vol_target.gross_path(
            unit_returns, vol_target.Spec(spec.combine_target)
        )
        if len(target) != len(gross):
            raise ValueError(
                "the returns and the probability are on different calendars"
            )
        gross = np.minimum(gross, target)
    return gross, read, sigma


# --- the verdict against two controls -----------------------------------------


# The best registered B1 target from B1's verdict record: the REPLACES
# target with the largest deciding-window drawdown gain, else the
# registered target with the largest one. Returns its tag; KeyError when
# the record carries no registered target.
def best_registered(vt_verdict: Mapping[str, Any]) -> str:
    """Return the tag of B1's best registered target."""
    targets = vt_verdict.get("targets", {})
    registered = {
        tag: r
        for tag, r in targets.items()
        if r.get("vol_target", {}).get("registered")
    }
    if not registered:
        raise KeyError("B1's verdict carries no registered target")

    def gain(r):
        g = r["windows"][vol_target.DECIDING]["drawdown_gain"]
        return -math.inf if g is None or not math.isfinite(g) else g

    winners = {t: r for t, r in registered.items() if r.get("label") == REPLACES}
    pool = winners or registered
    return max(pool, key=lambda t: gain(pool[t]))


# One variant's verdict from its payload and the two controls'. The two
# readings are B1's verdict function with each control in the control's
# seat; the label needs both.
def verdict(
    candidate: Mapping[str, Any],
    control: Mapping[str, Any],
    vol_target_payload: Mapping[str, Any],
    trial_variance: float = math.nan,
) -> dict[str, Any]:
    """Return the variant's verdict record."""
    spec = dict(candidate.get(KEY, {}))
    trials = TRIALS["cumulative"]
    against_control = vol_target.verdict(candidate, control, trial_variance, trials)
    against_target = vol_target.verdict(
        candidate, vol_target_payload, trial_variance, trials
    )
    clears_control = against_control["label"] == REPLACES
    clears_target = against_target["label"] == REPLACES
    if not spec.get("registered"):
        label = REPORTED
    elif clears_control and clears_target:
        label = REPLACES
    elif clears_control:
        label = RECORD_VOL_TARGET
    else:
        label = RECORD
    reading = {
        "label": label,
        "clears_control": clears_control,
        "clears_vol_target": clears_target,
        "against_control": against_control,
        "against_vol_target": against_target,
        "trials": TRIALS["cumulative"],
        "trial_variance": trial_variance,
        "cost_bps": vol_target.COST_BPS,
        KEY: spec,
        "probability": dict(candidate.get("probability", {})),
        "fired": _fired(candidate),
        "candidate_arm": candidate.get("arm"),
        "control_arm": control.get("arm"),
        "vol_target_arm": vol_target_payload.get("arm"),
        "vol_target_tag": vol_target_payload.get("vol_target", {}).get("tag"),
    }
    reading["lines"] = lines(reading)
    return reading


# The share of sessions the gate fired on per window, from the payload's
# gross record at the study's cost (NaN when absent).
def _fired(candidate: Mapping[str, Any]) -> dict[str, float]:
    """Return {window: share of sessions under gross 1}."""
    record = candidate.get(KEY, {}).get(f"{vol_target.COST_BPS:g}", {})
    windows = record.get("windows", {})
    return {
        w: vol_target._f(windows.get(w, {}).get("share_below_one"))
        for w in vol_target.WINDOWS
    }


# A variant's verdict as lines: the head, each control's readings (B1's
# own lines, indented), the label.
def lines(reading: Mapping[str, Any]) -> list[str]:
    """Return the verdict as lines."""
    spec = reading.get(KEY, {})
    threshold = spec.get("threshold", math.nan)
    head = f"θ = {threshold:g} / g_low = {spec.get('g_low', math.nan):g}"
    if spec.get("combine_target") is not None:
        head += f" ∧ σ* = {spec['combine_target'] * 100:.0f}% (reported)"
    fired = reading.get("fired", {})
    shares = ", ".join(
        f"{w} {v * 100:.0f}%" if math.isfinite(v) else f"{w} n/a"
        for w, v in fired.items()
    )
    out = [f"{head}: gross below 1 on {shares} of sessions"]
    for name, key in (
        (f"against the control ({reading.get('control_arm')})", "against_control"),
        (
            f"against the vol target {reading.get('vol_target_tag')} "
            f"({reading.get('vol_target_arm')})",
            "against_vol_target",
        ),
    ):
        out.append(f"  {name}:")
        out.extend("  " + line for line in reading[key]["lines"])
    if reading["label"] == REPLACES:
        out.append("  REPLACES gross 1.0 and the vol target")
    elif reading["label"] == REPORTED:
        out.append("  REPORTED, deciding nothing")
    else:
        out.append(f"  {reading['label']}")
    return out


# The variance of the paired-difference Sharpes across the registered
# pairs' payloads against the control (NaN with fewer than two).
def trial_variance(
    candidates: Mapping[str, Mapping[str, Any]], control: Mapping[str, Any]
) -> float:
    """Return the across-pair variance of the deciding window's paired Sharpe."""
    sharpes = [
        vol_target.paired(c, control, vol_target.DECIDING)["sharpe"]
        for c in candidates.values()
        if c.get(KEY, {}).get("registered")
    ]
    sharpes = [s for s in sharpes if math.isfinite(s)]
    if len(sharpes) < 2:
        return math.nan
    return float(np.var(sharpes, ddof=1))
