"""The first honest scorecard: the rule against a point-in-time book and funded indexes.

    python -m backend.cli.market_pit_scorecard
    python -m backend.cli.market_pit_scorecard --root data/market --offsets 20 \
        --costs 10 25

Every published curve so far graded 2016-2026 on the book as it stands today,
and the equal-weight version of that book beats every rule the desk has - so
the rule's lead over QQQ has been mostly the choice of names, made with
hindsight. This command prices six things on identical sessions, at every
phase of the 20-session clock and at two costs, and reports them side by side
without choosing among them:

  rule / today's book        what every published curve showed
  rule / point-in-time       the same rule, restricted each session to the
                             names the book could have held then
                             (`point_in_time.restrict`, from the dated
                             membership file)
  equal weight / point-in-time   the survivorship hurdle: every eligible name,
                             equal weight, rebalanced on the same clock
  equal weight / today's book    the hindsight ceiling
  SPY, QQQ                   funded like the rules by `benchmarks.load_benchmark`

Two windows are always reported apart: 2016-2023 (the choosing window) and
2024-2026 (already examined by every earlier study; reported, never tuned
on). Across the offsets the median and the worst are shown, plus how many
offsets the rule beats the equal-weight point-in-time book and QQQ. The
paired daily difference at the median offset carries a Newey-West t and a
probabilistic Sharpe. No gate is applied here; this is the number the gate
reads.

Read-only with respect to the desk and the store; writes
`<root>/desk/pit_scorecard.json`.

Every payload carries each row's per-offset CAGRs and worst drawdown and the
median-offset daily curves of every line, so two runs can be paired session
by session (a candidate against its control is a comparison one run cannot
make; `--output FILE` says where a payload goes). These fields were first
written on the structure-rules branch (`a3041068`, not merged) and are
re-implemented here for the volatility-targeting study.

The volatility-targeting study (`docs/research/vol-target-plan-2026-10-01.md`,
B1) adds `--gross-target PCT` (repeatable: one payload per target, named by
the target's tag), `--gross-window N` (default 20), and the two reported
switches `--gross-switch-return` and `--gross-switch-intercept`. With a
target, the two rule lines are run twice at every offset and cost: once at
gross 1 (the control's book, whose daily returns give σ̂), then scaled by
gross(t) = min(1, σ*/σ̂(t)) through `simulate.run(gross_path=...)`
(`vol_target.gross_path`). `--null-test` with `--gross-target inf` runs
the book through the scaled path at an infinite target and through the
plain path at two offsets and asserts every line is reproduced to the bit.

    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 \
        --output docs/research/scorecards/vol-target/control.json
    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 \
        --gross-target inf --null-test
    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 \
        --gross-target 20 25 30 --output docs/research/scorecards/vol-target/vt.json

The regime-gross study (`docs/research/regime-gross-plan-2026-10-01.md`,
B2) reuses the same gross path with a different rule: `--gross-regime
THRESH:GLOW` (repeatable, one payload per pair) scales the rule lines to
GLOW on every session whose previous close carried a day-type tail
probability (`regime_gross.tail_probability`: the walk-forward day-type
model, produced once per run on the point-in-time book) at or above
THRESH, and to 1 elsewhere. `--gross-regime-with-target PCT` (reported)
combines each pair with a PCT% volatility target as the per-session
minimum. `--null-test` with `--gross-regime 1.0:GLOW` is the study's null.

    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 \
        --gross-regime 1.0:0.5 --null-test
    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 \
        --gross-regime 0.3:0.5 0.5:0.5 0.5:0.0 \
        --output docs/research/scorecards/regime-gross/rg.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import (
    event_risk,
    grading,
    learned_arm,
    paper,
    point_in_time,
    simulate,
)
from backend.market import (
    benchmarks,
    candidate_stats,
    day_type,
    regime_gross,
    universe,
    vol_target,
)
from backend.market.universe import MARKET_INDICES

FILE = "pit_scorecard.json"
WINDOWS: dict[str, tuple[date | None, date | None]] = {
    "2016-2023": (date(2016, 1, 1), date(2024, 1, 1)),
    "2024-2026": (date(2024, 1, 1), None),
    "all": (None, None),
}
CONTROL = "control"
RULE_TODAY = "rule / today's book"
RULE_PIT = "rule / point-in-time"
EW_PIT = "equal weight / point-in-time"
EW_TODAY = "equal weight / today's book"
# Version 2: drawdown includes the starting NAV and effective names
# normalize the invested weight; version 1 payloads carry no version.
METRICS_VERSION = "pit-scorecard-metrics/2"
# Version 2 multiplies the weight set at the previous close by the simple
# return into the current close; version 1 used the weight set at the same
# close as the (log) return it was multiplied by, and is withdrawn.
WORST_NAME_DAY_BASIS = "lagged-simple/2"

# Allocation arms the scorecard can put on the rule lines. Each is a factory
# taking the report the line runs on and its (T, N) membership mask, and
# returning a `simulate.run` allocator. Parameters are frozen here, before
# any result is seen, and named in the output file, so an arm is one
# registered trial.
ARMS = {
    # P1.2: every A/A+ name at equal weight, capped at 10% of equity each.
    "ew_graded": lambda report, mask: point_in_time.graded_equal_weight_allocator(
        mask, min_grade=grading.ORDINAL[grading.A], cap=0.10, gross=1.0
    ),
    # The same names with no cap: fully invested whatever the count, so the
    # grade's selection is measured apart from the cash the cap leaves idle.
    "ew_graded_full": lambda report, mask: point_in_time.graded_equal_weight_allocator(
        mask, min_grade=grading.ORDINAL[grading.A], cap=1.0, gross=1.0
    ),
    # The deployable form: the same, under the operator's 20% hold limit.
    "ew_graded_20": lambda report, mask: point_in_time.graded_equal_weight_allocator(
        mask, min_grade=grading.ORDINAL[grading.A], cap=0.20, gross=1.0
    ),
    # A walk-forward gradient-boosted ranker, top ten members at 10% each.
    # "hgb_rank" trains on price features plus the desk's grade and summed
    # conviction (the baseline every earlier attempt used); "hgb_desk" on
    # the analysts' own evidence, the alpha summaries and the regime context
    # (`learned_arm.FEATURE_SETS`). Two registered trials.
    "hgb_rank": lambda report, mask: learned_arm.arm(report, mask, "price"),
    "hgb_desk": lambda report, mask: learned_arm.arm(report, mask, "desk"),
}


# The graded equal-weight arm at any hold cap, for the cap sweep. The cap is
# a risk limit, not a parameter to fit: the sweep measures what each limit
# costs and what it buys, and every cap scored is one registered trial.
def graded_arm(cap: float):
    """Return an ARMS-style factory for every A/A+ name at equal weight under `cap`."""
    return lambda report, mask: point_in_time.graded_equal_weight_allocator(
        mask, min_grade=grading.ORDINAL[grading.A], cap=cap, gross=1.0
    )


# Each session's worst single-name contribution to the book: the weight
# the arm decided at the previous close times that name's simple
# close-to-close return into this close, the minimum over names. The first
# session has no earlier decision, and a missing or nonfinite price
# contributes nothing (the earlier metric's convention for a missing one).
def worst_name_day(weights: np.ndarray, adj_close: np.ndarray) -> np.ndarray:
    """Return the (T,) minimum over names of weights[t-1] * simple return into t."""
    close = np.asarray(adj_close, dtype=float)
    held = np.asarray(weights, dtype=float)
    contribution = np.zeros_like(held)
    with np.errstate(divide="ignore", invalid="ignore"):
        lagged = held[:-1] * (close[1:] / close[:-1] - 1.0)
    contribution[1:] = np.where(np.isfinite(lagged), lagged, 0.0)
    return contribution.min(axis=1)


# What a cap buys, read off the target book the arm asks for on every
# session of the restricted report (before fills, so a property of the
# rule and not of the simulator): the largest single weight, the effective
# number of invested names (sum(weights)**2 / sum(weights**2)), the cash
# left idle, and the worst single-name day (`worst_name_day`: the weight
# set at the previous close times the simple return into the next one;
# `WORST_NAME_DAY_BASIS`), its minimum over the window's sessions. The
# other medians and extremes are conditional on a nonzero stock target.
def concentration(restricted, mask: np.ndarray, allocator, windows=None) -> dict:
    """Return per-window concentration statistics of the arm's target book."""
    panel = restricted.panel
    dates = panel.dates
    weights = np.zeros((len(dates), len(panel.tickers)))
    for t in range(len(dates)):
        weights[t] = allocator(restricted, panel, None, t)
    largest = weights.max(axis=1)
    invested = weights.sum(axis=1)
    sq = (weights**2).sum(axis=1)
    effective = np.divide(invested**2, sq, out=np.zeros_like(sq), where=sq > 0)
    cash = 1.0 - invested
    worst_name = worst_name_day(weights, panel.adj_close)
    out: dict[str, dict[str, object]] = {}
    for name, (start, end) in (windows or WINDOWS).items():
        w = point_in_time.window(dates, start, end)
        held = w & (invested > 0)
        if not held.any():
            out[name] = {"sessions": 0}
            continue
        out[name] = {
            "sessions": int(w.sum()),
            "invested_share": float(held.sum() / w.sum()),
            "largest_weight_median": float(np.median(largest[held])),
            "largest_weight_max": float(largest[held].max()),
            "effective_names_median": float(np.median(effective[held])),
            "effective_names_min": float(effective[held].min()),
            "cash_median": float(np.median(cash[held])),
            "cash_max": float(cash[held].max()),
            "worst_single_name_day": float(worst_name[w].min()),
            "worst_single_name_day_basis": WORST_NAME_DAY_BASIS,
        }
    return out


@dataclass(frozen=True)
class Curve:
    """One strategy's daily returns on its executable sessions."""

    label: str
    dates: np.ndarray
    daily: np.ndarray  # NaN before the first fill
    # The simulator's result behind a rule line (its returns at gross 1 are
    # what a volatility target reads), and under a target the gross and
    # σ̂ the rule applied on these sessions.
    sim: object = None
    gross: np.ndarray | None = None
    sigma: np.ndarray | None = None
    unit: object = None  # the gross-1 result a scaled line was read from
    # Under a regime gross, the tail probability p(t−1) the rule read.
    probability: np.ndarray | None = None


# Annualised return, drawdown from the starting NAV and Sharpe, or NaNs.
def window_stats(daily: np.ndarray) -> dict[str, float]:
    """Return {"cagr", "drawdown", "sharpe", "sessions"} for finite entries."""
    r = np.asarray(daily, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 2:
        return {
            "cagr": math.nan,
            "drawdown": math.nan,
            "sharpe": math.nan,
            "sessions": n,
        }
    curve = np.concatenate(([1.0], np.cumprod(1.0 + r)))
    cagr = float(curve[-1] ** (252.0 / n) - 1.0)
    peak = np.maximum.accumulate(curve)
    drawdown = float((curve / peak - 1.0).min())
    sd = float(r.std(ddof=1))
    sharpe = float(r.mean() / sd * math.sqrt(252.0)) if sd > 0 else math.nan
    return {"cagr": cagr, "drawdown": drawdown, "sharpe": sharpe, "sessions": n}


# The live execution policy the paper account runs, on the rule's own clock.
def _live_options(panel) -> dict:
    return dict(
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        event_exposure=event_risk.live_path(panel),
        event_lifecycle=True,
        **simulate.LIVE_POLICY,
    )


# Price the six lines from one offset at one cost.
def price_offset(
    report,
    restricted,
    mask: np.ndarray,
    store,
    since,
    cost_bps: float,
    arm=None,
) -> dict[str, Curve]:
    """Return {label: Curve} for every line on this offset.

    `arm`, when given, is an allocator factory `(report, mask) -> allocator` that
    replaces the rule on the two "rule" lines (today's book and point in
    time), so an allocation arm is scored on exactly the sessions, costs
    and controls the frozen rule is. The labels keep their keys; the
    payload's `arm` field says what they hold.
    """
    panel = report.panel
    live = _live_options(panel)
    out: dict[str, Curve] = {}
    everyone = np.ones_like(mask)
    everyone[:, panel.index(panel.benchmark)] = False
    if arm is None:
        rule_today = simulate.run(report, since=since, cost_bps=cost_bps, **live)
        rule_pit = simulate.run(restricted, since=since, cost_bps=cost_bps, **live)
    else:
        plain = dict(
            use_exits=False, rebalance=paper.REBALANCE_EVERY, cost_bps=cost_bps
        )
        rule_today = simulate.run(
            report, since=since, allocator=arm(report, everyone), **plain
        )
        rule_pit = simulate.run(
            restricted, since=since, allocator=arm(restricted, mask), **plain
        )
    out[RULE_TODAY] = Curve(
        RULE_TODAY, rule_today.dates, rule_today.returns, sim=rule_today
    )
    out[RULE_PIT] = Curve(RULE_PIT, rule_pit.dates, rule_pit.returns, sim=rule_pit)
    for label, book_mask in ((EW_PIT, mask), (EW_TODAY, everyone)):
        sim = simulate.run(
            restricted if label == EW_PIT else report,
            since=since,
            cost_bps=cost_bps,
            use_exits=False,
            rebalance=paper.REBALANCE_EVERY,
            allocator=point_in_time.equal_weight_allocator(book_mask),
        )
        out[label] = Curve(label, sim.dates, sim.returns)
    for symbol in MARKET_INDICES:
        series = benchmarks.load_benchmark(
            store, symbol, rule_today.dates, cost_bps=cost_bps
        )
        daily = (
            series.daily if series.available else np.full(len(rule_today.dates), np.nan)
        )
        out[symbol] = Curve(symbol, rule_today.dates, daily)
    return out


# The payload key a scaled variant's record lives under: "vol_target" for
# B1's specs, "regime_gross" for B2's.
def spec_key(spec) -> str:
    """Return the payload key of `spec`'s study."""
    return regime_gross.KEY if isinstance(spec, regime_gross.Spec) else "vol_target"


# The gross path of one variant on the panel's calendar from the gross-1
# book's returns there and, for a regime gross, the point-in-time tail
# probability: (gross, σ̂ or None, p(t−1) or None).
def gross_for(spec, on_calendar: np.ndarray, probability: np.ndarray | None):
    """Return (gross, sigma, probability read) for `spec`."""
    if isinstance(spec, regime_gross.Spec):
        if probability is None:
            raise ValueError("a regime gross needs the tail probability series")
        gross, read, sigma = regime_gross.gross_path(probability, spec, on_calendar)
        return gross, sigma, read
    gross, sigma = vol_target.gross_path(on_calendar, spec)
    return gross, sigma, None


# The two rule lines of one priced offset run again under a volatility
# target or a regime gross: the gross path is read off each line's own
# gross-1 returns (the book `price_offset` already ran, so σ̂ at t reads
# only sessions before t) and, for a regime gross, the tail probability
# series on the panel's calendar (`probability`, read at t−1); the book is
# run again through `simulate.run(gross_path=...)` on the same sessions
# and cost, and the other lines are shared with the base. Each scaled
# curve carries its gross path and what the rule read, on the rule's
# calendar.
def scale_offset(
    report,
    restricted,
    mask: np.ndarray,
    since,
    cost_bps: float,
    arm,
    base: dict,
    spec,
    probability: np.ndarray | None = None,
) -> dict[str, Curve]:
    """Return the base's lines with the two rule lines scaled to `spec`."""
    if arm is None:
        raise ValueError("a gross rule needs an allocation arm")
    out = dict(base)
    everyone = np.ones_like(mask)
    everyone[:, report.panel.index(report.panel.benchmark)] = False
    plain = dict(use_exits=False, rebalance=paper.REBALANCE_EVERY, cost_bps=cost_bps)
    for label, rep, book_mask in (
        (RULE_TODAY, report, everyone),
        (RULE_PIT, restricted, mask),
    ):
        unit = base[label].sim
        on_calendar = np.full(len(rep.panel.dates), np.nan)
        start = len(rep.panel.dates) - len(unit.returns)
        on_calendar[start:] = unit.returns
        gross, sigma, read = gross_for(spec, on_calendar, probability)
        sim = simulate.run(
            rep, since=since, allocator=arm(rep, book_mask), gross_path=gross, **plain
        )
        out[label] = Curve(
            label,
            sim.dates,
            sim.returns,
            sim=sim,
            gross=gross[start:],
            sigma=None if sigma is None else sigma[start:],
            unit=unit,
            probability=None if read is None else read[start:],
        )
    return out


# Align a curve's daily returns onto a reference calendar (NaN where absent).
def _on(dates: np.ndarray, curve: Curve) -> np.ndarray:
    ref = np.asarray(dates, dtype="datetime64[D]")
    own = np.asarray(curve.dates, dtype="datetime64[D]")
    out = np.full(len(ref), np.nan)
    pos = np.searchsorted(ref, own)
    ok = (pos < len(ref)) & (ref[np.minimum(pos, len(ref) - 1)] == own)
    out[pos[ok]] = np.asarray(curve.daily, dtype=float)[ok]
    return out


# Summarise every line over every window across the offsets at one cost.
def summarise(
    priced: list[dict[str, Curve]], cost_bps: float
) -> list[dict[str, object]]:
    """Return one row per (line, window) with medians, worsts and win counts."""
    rows: list[dict[str, object]] = []
    labels = list(priced[0])
    for name, (start, end) in WINDOWS.items():
        per_label: dict[str, list[dict[str, float]]] = {label: [] for label in labels}
        for offset in priced:
            base = offset[RULE_TODAY].dates
            keep = point_in_time.window(base, start, end)
            for label in labels:
                per_label[label].append(window_stats(_on(base, offset[label])[keep]))
        for label in labels:
            cagrs = np.array([s["cagr"] for s in per_label[label]])
            hurdle = np.array([s["cagr"] for s in per_label[EW_PIT]])
            index = np.array([s["cagr"] for s in per_label["QQQ"]])
            rows.append(
                {
                    "line": label,
                    "cost_bps": cost_bps,
                    "window": name,
                    "offsets": len(priced),
                    "median_cagr": _nanmedian(cagrs),
                    "worst_cagr": _nanmin(cagrs),
                    "best_cagr": _nanmax(cagrs),
                    "median_drawdown": _nanmedian(
                        np.array([s["drawdown"] for s in per_label[label]])
                    ),
                    "worst_drawdown": _nanmin(
                        np.array([s["drawdown"] for s in per_label[label]])
                    ),
                    # Every offset's CAGR, in offset order, so two runs can
                    # be compared offset by offset.
                    "cagrs": [float(c) for c in cagrs],
                    "median_sharpe": _nanmedian(
                        np.array([s["sharpe"] for s in per_label[label]])
                    ),
                    "offsets_above_ew_pit": int(np.nansum(cagrs > hurdle)),
                    "offsets_above_qqq": int(np.nansum(cagrs > index)),
                    "sessions": int(
                        np.nanmedian([s["sessions"] for s in per_label[label]])
                    ),
                }
            )
    return rows


# Median over finite entries, NaN when there are none.
def _nanmedian(x):
    return float(np.nanmedian(x)) if np.isfinite(x).any() else math.nan


# Minimum over finite entries, NaN when there are none.
def _nanmin(x):
    return float(np.nanmin(x)) if np.isfinite(x).any() else math.nan


# Maximum over finite entries, NaN when there are none.
def _nanmax(x):
    return float(np.nanmax(x)) if np.isfinite(x).any() else math.nan


# Paired evidence at the median offset: rule minus hurdle, rule minus QQQ.
def paired(priced: list[dict[str, Curve]], cost_bps: float) -> list[dict[str, object]]:
    """Return HAC t and PSR of the paired daily differences per window."""
    out: list[dict[str, object]] = []
    offset = priced[len(priced) // 2]
    base = offset[RULE_TODAY].dates
    for name, (start, end) in WINDOWS.items():
        keep = point_in_time.window(base, start, end)
        for line, against in (
            (RULE_PIT, EW_PIT),
            (RULE_PIT, "QQQ"),
            (RULE_TODAY, "QQQ"),
            (EW_PIT, "QQQ"),
        ):
            a = _on(base, offset[line])[keep]
            b = _on(base, offset[against])[keep]
            diff = a - b
            diff = diff[np.isfinite(diff)]
            mom = candidate_stats.moments(diff)
            out.append(
                {
                    "cost_bps": cost_bps,
                    "window": name,
                    "line": line,
                    "against": against,
                    "sessions": int(len(diff)),
                    "mean_daily_bp": float(diff.mean() * 1e4)
                    if len(diff)
                    else math.nan,
                    "hac_t": candidate_stats.hac_t(diff, 20)
                    if len(diff) > 2
                    else math.nan,
                    "psr": candidate_stats.probabilistic_sharpe(
                        mom.sharpe, mom.length, mom.skew, mom.kurtosis
                    ),
                }
            )
    return out


# Run everything and assemble the payload; `report` is the desk's unrestricted report.
def build(
    report, store, offsets: int, costs: tuple[float, ...], history_path=None, arm=None
) -> dict:
    """Return the scorecard payload; `arm` as in `price_offset`."""
    return build_targets(report, store, offsets, costs, history_path, arm, ())[CONTROL]


# The scorecard payload and, per gross variant (a volatility target or a
# regime gross), the payload of the same run with the two rule lines
# scaled (`scale_offset`): every variant shares the base pricing, so the
# control inside a variant run is the plain path at the same offsets,
# costs and store. Keys are `CONTROL` and each variant's tag. A regime
# gross reads the point-in-time tail probability of the restricted book
# (`regime_gross.tail_probability`, one series per horizon and model,
# produced once here, or passed in through `probabilities` keyed by
# (horizon, model) when a caller already holds it).
def build_targets(
    report,
    store,
    offsets: int,
    costs: tuple[float, ...],
    history_path=None,
    arm=None,
    specs: tuple = (),
    probabilities: dict | None = None,
) -> dict[str, dict]:
    """Return {CONTROL: payload, spec.tag: payload, ...}."""
    panel = report.panel
    restricted, mask = (
        point_in_time.point_in_time(report, history_path)
        if history_path
        else point_in_time.point_in_time(report)
    )
    members = mask.sum(axis=1)
    series = probability_series(restricted, mask, specs, probabilities)
    payloads = {CONTROL: _payload(panel, offsets, costs, members, history_path)}
    for spec in specs:
        payloads[spec.tag] = _payload(panel, offsets, costs, members, history_path)
        payloads[spec.tag][spec_key(spec)] = spec.record()
        if isinstance(spec, regime_gross.Spec):
            key = (spec.horizon, spec.model)
            payloads[spec.tag]["probability"] = series[key].record()
    for cost in costs:
        priced = [
            price_offset(report, restricted, mask, store, _since(panel, k), cost, arm)
            for k in range(offsets)
        ]
        _score(payloads[CONTROL], priced, cost)
        for spec in specs:
            scaled = [
                scale_offset(
                    report,
                    restricted,
                    mask,
                    _since(panel, k),
                    cost,
                    arm,
                    base,
                    spec,
                    _probability_of(series, spec),
                )
                for k, base in enumerate(priced)
            ]
            _score(payloads[spec.tag], scaled, cost)
            payloads[spec.tag][spec_key(spec)][f"{cost:g}"] = gross_record(scaled)
    return payloads


# The tail-probability series every regime-gross spec needs, keyed by
# (horizon, model): those passed in are kept, the rest produced once from
# the restricted book. Empty when no spec is a regime gross.
def probability_series(restricted, mask, specs, probabilities=None) -> dict:
    """Return {(horizon, model): Probability} for the regime specs."""
    out = dict(probabilities or {})
    for spec in specs:
        if isinstance(spec, regime_gross.Spec):
            key = (spec.horizon, spec.model)
            if key not in out:
                out[key] = regime_gross.tail_probability(
                    restricted, mask, spec.horizon, spec.model
                )
    return out


# The (T,) probability array a spec reads, None for a volatility target.
def _probability_of(series: dict, spec) -> np.ndarray | None:
    """Return the probability series of a regime spec, else None."""
    if not isinstance(spec, regime_gross.Spec):
        return None
    return np.asarray(series[(spec.horizon, spec.model)].probability, dtype=float)


# One cost's rows, paired evidence and median-offset curves onto a payload.
def _score(payload: dict, priced: list[dict[str, Curve]], cost: float) -> None:
    """Extend the payload's rows, paired and curves with this cost's pricing."""
    payload["rows"].extend(summarise(priced, cost))
    payload["paired"].extend(paired(priced, cost))
    payload["curves"][f"{cost:g}"] = median_offset_curves(priced)


# The daily returns of every line at the median offset (the offset `paired`
# reads), on the rule's calendar, so two payloads from different runs can
# be paired session by session: a candidate against its control is a
# comparison the scorecard cannot make within one run.
def median_offset_curves(priced: list[dict[str, Curve]]) -> dict:
    """Return {"offset", "dates", "lines": {label: [daily...]}} at the median offset."""
    k = len(priced) // 2
    offset = priced[k]
    base = offset[RULE_TODAY].dates
    return {
        "offset": k,
        "dates": [str(d) for d in np.asarray(base, dtype="datetime64[D]")],
        "lines": {label: _on(base, curve).tolist() for label, curve in offset.items()},
    }


# What the gross rule did to the point-in-time rule line at one cost: the
# gross it applied at the median offset, session by session, with what it
# read (σ̂ under a volatility target, p(t−1) under a regime gross, both
# when combined), and per window across the offsets the median of each
# offset's mean gross, share of sessions under gross 1, lowest gross,
# sessions in cash, and the notional traded against the gross-1 book (the
# rescaling trades' cost is in the returns; this is their size).
def gross_record(scaled: list[dict[str, Curve]]) -> dict:
    """Return the payload's per-cost record of the gross path."""
    k = len(scaled) // 2
    median = scaled[k][RULE_PIT]
    at_median: dict[str, object] = {
        "offset": k,
        "dates": [str(d) for d in np.asarray(median.dates, dtype="datetime64[D]")],
        "gross": [float(g) for g in median.gross],
    }
    if median.sigma is not None:
        at_median["sigma_hat"] = [float(s) for s in median.sigma]
    if median.probability is not None:
        at_median["probability"] = [float(p) for p in median.probability]
    out: dict[str, object] = {"median_offset": at_median, "windows": {}}
    for name, (start, end) in WINDOWS.items():
        stats: dict[str, list[float]] = {
            "mean_gross": [],
            "share_below_one": [],
            "min_gross": [],
            "share_in_cash": [],
            "traded_over_gross_one": [],
        }
        for offset in scaled:
            curve = offset[RULE_PIT]
            keep = point_in_time.window(curve.dates, start, end)
            g = np.asarray(curve.gross, dtype=float)[keep]
            if not len(g):
                continue
            stats["mean_gross"].append(float(g.mean()))
            stats["share_below_one"].append(float((g < 1.0).mean()))
            stats["min_gross"].append(float(g.min()))
            stats["share_in_cash"].append(float((g <= 0.0).mean()))
        for offset in scaled:
            # Whole-run notional, not per window: one number per offset.
            curve = offset[RULE_PIT]
            stats["traded_over_gross_one"].append(
                float(curve.sim.traded / curve.unit.traded)
                if curve.unit.traded
                else math.nan
            )
        out["windows"][name] = {
            key: (float(np.median(v)) if v else math.nan) for key, v in stats.items()
        }
    return out


# The skeleton every payload starts from.
def _payload(
    panel, offsets: int, costs: tuple[float, ...], members, history_path
) -> dict:
    """Return the payload with its header and empty rows, paired and curves."""
    payload: dict[str, object] = {
        "metrics_version": METRICS_VERSION,
        "asof": str(panel.dates[-1]),
        "offsets": offsets,
        "costs_bps": list(costs),
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "book": {
            "names_today": int(len(panel.tickers) - 1),
            "eligible_first_session": int(members[0]),
            "eligible_last_session": int(members[-1]),
            "eligible_median": float(np.median(members)),
        },
        "rows": [],
        "paired": [],
        "note": (
            "Lines priced on identical sessions from each of the first `offsets` "
            "sessions; medians and worsts are across offsets. The point-in-time "
            "book is the dated membership file; names with no bars in the store "
            "on a session are not held by any line. Drawdown includes starting NAV. "
            "Concentration, when attached, describes target weights, not fills; "
            "effective names normalizes the invested stock weights and excludes "
            "cash; worst_single_name_day is the weight targeted at the previous "
            "close times the name's simple return into the next close "
            f"({WORST_NAME_DAY_BASIS})."
        ),
        "membership": str(history_path or universe.MEMBERSHIP_HISTORY_PATH),
        "curves": {},
    }
    return payload


# The k-th panel session as a date, for `simulate.run(since=...)`.
def _since(panel, k: int):
    return panel.dates[k].astype("datetime64[D]").astype(object)


# Print the rows as a table people can read.
def render(payload: dict) -> str:
    """Return the scorecard as text."""
    lines = [f"point-in-time scorecard as of {payload['asof']}"]
    book = payload["book"]
    lines.append(
        f"book: {book['names_today']} names today; eligible per session "
        f"{book['eligible_first_session']} at the start, "
        f"{book['eligible_last_session']} "
        f"at the end, median {book['eligible_median']:.0f}"
    )
    for cost in payload["costs_bps"]:
        for window in WINDOWS:
            lines.append(
                f"\n{cost:g} bp, {window}  (median / worst across "
                f"{payload['offsets']} offsets)"
            )
            lines.append(
                f"  {'line':<34}{'CAGR':>8}{'worst':>8}{'maxDD':>8}{'Sharpe':>8}"
                f"{'>EW-PIT':>9}{'>QQQ':>7}"
            )
            for row in payload["rows"]:
                if row["cost_bps"] != cost or row["window"] != window:
                    continue
                lines.append(
                    f"  {row['line']:<34}{_pct(row['median_cagr']):>8}"
                    f"{_pct(row['worst_cagr']):>8}"
                    f"{_pct(row['median_drawdown']):>8}{row['median_sharpe']:>8.2f}"
                    f"{row['offsets_above_ew_pit']:>9}{row['offsets_above_qqq']:>7}"
                )
            for pair in payload["paired"]:
                if pair["cost_bps"] != cost or pair["window"] != window:
                    continue
                lines.append(
                    f"  paired {pair['line']} minus {pair['against']}: "
                    f"{pair['mean_daily_bp']:+.1f} bp/day, HAC t {pair['hac_t']:.2f}, "
                    f"PSR {pair['psr']:.2f}"
                )
            record = payload.get("vol_target") or payload.get(regime_gross.KEY) or {}
            gross = record.get(f"{cost:g}", {}).get("windows", {})
            if window in gross:
                g = gross[window]
                lines.append(
                    f"  gross on {RULE_PIT}: mean {g['mean_gross']:.2f}, below 1 on "
                    f"{g['share_below_one'] * 100:.0f}% of sessions, lowest "
                    f"{g['min_gross']:.2f}, in cash {g['share_in_cash'] * 100:.0f}%; "
                    f"traded {g['traded_over_gross_one']:.2f}x the gross-1 book"
                )
    spec = payload.get("vol_target")
    if spec:
        lines.insert(
            1,
            f"volatility target {spec['tag']}: sigma* {spec['target'] * 100:g}%/yr, "
            f"{spec['window']}-session sigma-hat, return switch "
            f"{spec['switch_return']}, "
            f"intercept switch {spec['switch_intercept']}",
        )
    spec = payload.get(regime_gross.KEY)
    if spec:
        combined = (
            f", min with sigma* {spec['combine_target'] * 100:g}%/yr"
            if spec.get("combine_target") is not None
            else ""
        )
        p = payload.get("probability", {})
        lines.insert(
            1,
            f"regime gross {spec['tag']}: g_low {spec['g_low']:g} when p(t-1) >= "
            f"{spec['threshold']:g}{combined}; p from horizon {spec['horizon']} "
            f"{spec['model']}, first {p.get('first_session')}, refit every "
            f"{p.get('refit_every')} sessions, Brier skill "
            f"{_f(p.get('brier_skill')):.3f}, max p {_f(p.get('max')):.2f}",
        )
    return "\n".join(lines)


# A payload number as a float, NaN for None.
def _f(value) -> float:
    """Return `value` as a float, NaN when missing."""
    return math.nan if value is None else float(value)


# A fraction as a percentage string, "n/a" for NaN.
def _pct(x: float) -> str:
    return "n/a" if x != x else f"{x * 100:.1f}%"


# Run the desk, score, write and print.
def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--offsets", type=int, default=20)
    parser.add_argument("--costs", type=float, nargs="+", default=[10.0, 25.0])
    parser.add_argument(
        "--signed-rotation",
        action="store_true",
        help="score the signed-rotation arm instead of the frozen rule; "
        "writes pit_scorecard_signed_rotation.json",
    )
    parser.add_argument(
        "--arm",
        choices=sorted(ARMS),
        help="score an allocation arm on the two rule lines instead of the "
        "frozen rule; writes pit_scorecard_<arm>.json",
    )
    parser.add_argument(
        "--graded-cap",
        type=float,
        help="score every A/A+ name at equal weight under this hold cap "
        "(0 < cap <= 1) with its concentration statistics; writes "
        "pit_scorecard_ew_graded_cap<percent>.json",
    )
    parser.add_argument(
        "--membership",
        type=Path,
        help="the dated membership file the point-in-time mask reads "
        "(default: the book's)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="where to write the payload; with several --gross-target values "
        "each target's payload is written beside it with the target's tag "
        "before the suffix",
    )
    parser.add_argument(
        "--gross-target",
        type=float,
        nargs="+",
        metavar="PCT",
        help="scale the rule lines' gross to min(1, PCT%%/sigma-hat) (B1; "
        "needs an arm); repeatable, one payload per target; 'inf' is the null",
    )
    parser.add_argument(
        "--gross-window",
        type=int,
        default=vol_target.WINDOW,
        help="sessions of the book's own gross-1 returns sigma-hat reads",
    )
    parser.add_argument(
        "--gross-switch-return",
        action="store_true",
        help="reported only: gross 0 when the trailing 120-session book return "
        "is negative",
    )
    parser.add_argument(
        "--gross-switch-intercept",
        action="store_true",
        help="reported only: no scaling when the trailing risk-return intercept "
        "is negative",
    )
    parser.add_argument(
        "--gross-regime",
        nargs="+",
        metavar="THRESH:GLOW",
        help="gross g_low when the day-type model's walk-forward tail "
        "probability at the previous close is at or above THRESH, else 1 (B2; "
        "needs an arm); repeatable, one payload per pair; THRESH 1.0 is the null",
    )
    parser.add_argument(
        "--gross-regime-with-target",
        type=float,
        metavar="PCT",
        help="reported only: every --gross-regime pair combined with a PCT%% "
        "volatility target as the per-session minimum of the two grosses",
    )
    parser.add_argument(
        "--regime-horizon",
        type=int,
        default=regime_gross.HORIZON,
        choices=sorted(day_type.HORIZONS),
        help="the day-type label's horizon in sessions",
    )
    parser.add_argument(
        "--regime-model",
        default=regime_gross.MODEL,
        choices=("logistic", "hgb"),
        help="the day-type model",
    )
    parser.add_argument(
        "--null-test",
        action="store_true",
        help="with --gross-target inf or --gross-regime 1.0:GLOW: run the book "
        "through the scaled path at a rule that never fires and through the "
        "plain path and assert every line is reproduced to the bit at two "
        "offsets; no payload",
    )
    args = parser.parse_args(argv)
    from backend.agents.trading.desk import desk
    from backend.market.store import MarketStore

    root = Path(args.root)
    store = MarketStore(root)
    arm = ARMS[args.arm] if args.arm else None
    cap_tag = None
    if args.graded_cap is not None:
        if not 0 < args.graded_cap <= 1.0:
            parser.error("--graded-cap must be in (0, 1]")
        arm = graded_arm(args.graded_cap)
        cap_tag = f"ew_graded_cap{round(args.graded_cap * 100):02d}"
    specs = _specs(args, parser, arm)
    history = args.membership or universe.MEMBERSHIP_HISTORY_PATH
    report = desk.run(
        store,
        None,
        inputs=(desk.EXPECTATIONS_GAP,),
        signed_rotation=args.signed_rotation,
    )
    if args.null_test:
        if len(specs) != 1 or not _is_null(specs[0]):
            parser.error(
                "--null-test needs exactly --gross-target inf or "
                "--gross-regime 1.0:GLOW"
            )
        verdict = null_test(report, store, history, 2, tuple(args.costs), arm, specs[0])
        print(render_null_test(verdict))
        return 0 if verdict["ok"] else 1
    payloads = build_targets(
        report, store, args.offsets, tuple(args.costs), history, arm, specs
    )
    tags = [
        t
        for t, on in (
            ("signed_rotation", args.signed_rotation),
            (args.arm, args.arm),
            (cap_tag, cap_tag),
        )
        if on
    ]
    base_arm = " + ".join(tags) if tags else "frozen rule"
    name = FILE if not tags else FILE.replace(".json", "_" + "_".join(tags) + ".json")
    if args.graded_cap is not None:
        restricted, mask = point_in_time.point_in_time(report, history)
        for payload in payloads.values():
            payload["cap"] = args.graded_cap
            payload["concentration"] = concentration(
                restricted, mask, arm(restricted, mask)
            )
    written = _write_payloads(payloads, base_arm, args.output or root / "desk" / name)
    for target in written:
        print(f"\nwrote {target}")
    return 0


# The gross variants a run asks for: B1's targets from `--gross-target`
# and the window and switches, B2's pairs from `--gross-regime` (each
# combined with `--gross-regime-with-target` when given); the options
# are checked here and a bad one stops the parser.
def _specs(args, parser, arm) -> tuple:
    """Return the run's specs, in option order."""
    specs = tuple(
        vol_target.Spec(
            target=t if math.isinf(t) else t / 100.0,
            window=args.gross_window,
            switch_return=args.gross_switch_return,
            switch_intercept=args.gross_switch_intercept,
        )
        for t in (args.gross_target or ())
    )
    combine = args.gross_regime_with_target
    if combine is not None:
        combine /= 100.0
        if not combine > 0:
            parser.error("--gross-regime-with-target must be positive")
    try:
        specs += tuple(
            regime_gross.parse_pair(
                pair, combine, horizon=args.regime_horizon, model=args.regime_model
            )
            for pair in (args.gross_regime or ())
        )
    except ValueError as err:
        parser.error(str(err))
    if specs and arm is None:
        parser.error(
            "--gross-target and --gross-regime need an allocation arm "
            "(--arm or --graded-cap)"
        )
    if args.gross_window < 2:
        parser.error("--gross-window needs at least two sessions")
    if len({s.tag for s in specs}) != len(specs):
        parser.error("two gross variants carry the same tag")
    return specs


# Name, write and print every payload of a run. The control goes to `path`
# itself, or, when the run carries targets, to `path` tagged "control"
# beside them; a target goes to `path` tagged with its own tag, or to
# `path` itself when it is the run's only target.
def _write_payloads(payloads: dict[str, dict], base_arm: str, path: Path) -> list[Path]:
    """Return the paths written, in the payloads' order."""
    targets = [key for key in payloads if key != CONTROL]
    written = []
    for key, payload in payloads.items():
        if key == CONTROL:
            payload["arm"] = base_arm
            target = _tagged(path, CONTROL) if targets else path
        else:
            payload["arm"] = f"{base_arm} + {key}"
            target = path if len(targets) == 1 else _tagged(path, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8"
        )
        print(render(payload))
        written.append(target)
    return written


# A payload path with a tag before its suffix: vt.json + "vt25" -> vt_vt25.json.
def _tagged(path: Path, tag: str) -> Path:
    """Return `path` with `_<tag>` before the suffix."""
    return path.with_name(f"{path.stem}_{tag}{path.suffix}")


# Whether a spec is its study's null: an infinite volatility target, or a
# regime threshold no probability reaches.
def _is_null(spec) -> bool:
    """Return True for the null variant of either study."""
    if isinstance(spec, regime_gross.Spec):
        return spec.is_null
    return math.isinf(spec.target)


# The null test of the gross path: the book through `scale_offset` at a
# rule that never fires (an infinite volatility target, or a regime
# threshold of 1.0 - gross 1 on every session) against the plain
# `price_offset`, every line at two offsets and every cost, dates and
# returns equal to the bit (NaN equal to NaN). A regime null reads the
# real tail-probability series, so it also proves the series reaches the
# path and never crosses 1. The whole thing is `ok` only when every line
# is.
def null_test(
    report, store, history_path, offsets: int, costs, arm, spec, probabilities=None
) -> dict:
    """Return {"ok", "lines": [{cost, offset, line, dates_equal, returns_equal}]}."""
    restricted, mask = point_in_time.point_in_time(report, history_path)
    series = probability_series(restricted, mask, (spec,), probabilities)
    probability = _probability_of(series, spec)
    lines = []
    for cost in costs:
        for k in range(offsets):
            since = _since(report.panel, k)
            plain = price_offset(report, restricted, mask, store, since, cost, arm)
            through = scale_offset(
                report, restricted, mask, since, cost, arm, plain, spec, probability
            )
            for label, curve in plain.items():
                other = through[label]
                lines.append(
                    {
                        "cost_bps": cost,
                        "offset": k,
                        "line": label,
                        "dates_equal": bool(np.array_equal(curve.dates, other.dates)),
                        "returns_equal": bool(
                            np.array_equal(
                                np.asarray(curve.daily, dtype=float),
                                np.asarray(other.daily, dtype=float),
                                equal_nan=True,
                            )
                        ),
                        "gross_all_one": bool(
                            other.gross is None
                            or np.all(np.asarray(other.gross) == 1.0)
                        ),
                    }
                )
    return {
        "ok": all(
            r["dates_equal"] and r["returns_equal"] and r["gross_all_one"]
            for r in lines
        ),
        "lines": lines,
    }


# The null test's verdict as text: one line per mismatch, or the all-clear.
def render_null_test(verdict: dict) -> str:
    """Return the null test as text."""
    lines = [
        "null test: the book through the gross path at a rule that never fires "
        "(target inf, or regime threshold 1.0) against the plain path",
        f"  lines compared: {len(verdict['lines'])}",
    ]
    for row in verdict["lines"]:
        if not (row["dates_equal"] and row["returns_equal"] and row["gross_all_one"]):
            lines.append(
                f"  MISMATCH {row['cost_bps']:g} bp offset {row['offset']} "
                f"{row['line']}: dates {row['dates_equal']}, "
                f"returns {row['returns_equal']}, gross all one {row['gross_all_one']}"
            )
    passed = "PASS, reproduced to the bit" if verdict["ok"] else "FAIL"
    lines.append(f"  verdict: {passed}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
