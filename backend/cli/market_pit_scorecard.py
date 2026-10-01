"""The first honest scorecard: the rule against a point-in-time book and funded indexes.

    python -m backend.cli.market_pit_scorecard
    python -m backend.cli.market_pit_scorecard --root data/market --offsets 20 --costs 10 25

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

The book gate for a proposed analyst (`docs/research/stance-table-gate.md`)
adds `--stance-table FILE` (repeatable), a point-in-time stance table in
the studies' long form (session, ticker, stance[, conviction | rank]) read
by `desk/stance_table.py`, and `--stance-mode {sixth,replace:<analyst>}`:
`sixth` grades each table as a further full vote under the unchanged rule,
`replace:sentiment` (or any of the five) puts the one table in that
analyst's place. `--membership FILE` names the dated membership file the
point-in-time mask reads, `--output FILE` where the payload goes,
`--rank-ic` attaches the graded score's rank IC at 20 and 60 sessions,
and `--null-test` (with `--stance-table`) grades the book with the same
rows zeroed in `sixth` mode against the plain desk and asserts the grades,
scores and every line's returns are reproduced to the bit at two offsets:
the incumbent must be reproduced before any table is read. Every payload
carries each row's per-offset CAGRs and worst drawdown and the
median-offset daily curves of every line, so two runs can be paired
session by session; a stance-table payload records each table's sha256,
the mode, and what the table did to the grade counts per window.

    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 \\
        --stance-table stances/A2.parquet --null-test
    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 --rank-ic \\
        --output docs/research/scorecards/<study>/control.json
    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 --rank-ic \\
        --stance-table stances/A2.parquet --stance-mode sixth \\
        --output docs/research/scorecards/<study>/pit_scorecard_A2.json
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
    stance_table,
)
from backend.market import benchmarks, candidate_stats, universe
from backend.market.universe import MARKET_INDICES

FILE = "pit_scorecard.json"
WINDOWS: dict[str, tuple[date | None, date | None]] = {
    "2016-2023": (date(2016, 1, 1), date(2024, 1, 1)),
    "2024-2026": (date(2024, 1, 1), None),
    "all": (None, None),
}
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


# Annualised return, drawdown from the starting NAV and Sharpe, or NaNs.
def window_stats(daily: np.ndarray) -> dict[str, float]:
    """Return {"cagr", "drawdown", "sharpe", "sessions"} for finite entries."""
    r = np.asarray(daily, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 2:
        return {"cagr": math.nan, "drawdown": math.nan, "sharpe": math.nan, "sessions": n}
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
    report, restricted, mask: np.ndarray, store, since, cost_bps: float,
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
        plain = dict(use_exits=False, rebalance=paper.REBALANCE_EVERY, cost_bps=cost_bps)
        rule_today = simulate.run(report, since=since, allocator=arm(report, everyone), **plain)
        rule_pit = simulate.run(restricted, since=since, allocator=arm(restricted, mask), **plain)
    out[RULE_TODAY] = Curve(RULE_TODAY, rule_today.dates, rule_today.returns)
    out[RULE_PIT] = Curve(RULE_PIT, rule_pit.dates, rule_pit.returns)
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
        daily = series.daily if series.available else np.full(len(rule_today.dates), np.nan)
        out[symbol] = Curve(symbol, rule_today.dates, daily)
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
                    "sessions": int(np.nanmedian([s["sessions"] for s in per_label[label]])),
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
        for line, against in ((RULE_PIT, EW_PIT), (RULE_PIT, "QQQ"), (RULE_TODAY, "QQQ"), (EW_PIT, "QQQ")):
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
                    "mean_daily_bp": float(diff.mean() * 1e4) if len(diff) else math.nan,
                    "hac_t": candidate_stats.hac_t(diff, 20) if len(diff) > 2 else math.nan,
                    "psr": candidate_stats.probabilistic_sharpe(
                        mom.sharpe, mom.length, mom.skew, mom.kurtosis
                    ),
                }
            )
    return out


# Two reports priced on the same lines at the same offsets and costs,
# compared to the bit: the null test of a new desk path is that the book
# through it reproduces the control exactly. Returns the verdict and, per
# (cost, offset, line), whether the dates and the returns arrays are equal
# (NaN equal to NaN); the whole thing is `ok` only when every line is and
# the grades and scores agree.
def null_test(
    report_a,
    report_b,
    store,
    history_path,
    offsets: int,
    costs: tuple[float, ...],
    arm=None,
) -> dict:
    """Return {"ok", "lines": [{cost, offset, line, dates_equal, returns_equal}]}."""
    priced = []
    for report in (report_a, report_b):
        restricted, mask = point_in_time.point_in_time(report, history_path)
        priced.append(
            {
                (cost, k): price_offset(
                    report, restricted, mask, store, _since(report.panel, k), cost, arm
                )
                for cost in costs
                for k in range(offsets)
            }
        )
    lines = []
    for (cost, k), curves in priced[0].items():
        other = priced[1][(cost, k)]
        for label, curve in curves.items():
            a, b = curve, other[label]
            dates_equal = bool(np.array_equal(a.dates, b.dates))
            returns_equal = bool(
                np.array_equal(
                    np.asarray(a.daily, dtype=float),
                    np.asarray(b.daily, dtype=float),
                    equal_nan=True,
                )
            )
            lines.append(
                {
                    "cost_bps": cost,
                    "offset": k,
                    "line": label,
                    "dates_equal": dates_equal,
                    "returns_equal": returns_equal,
                }
            )
    grades_equal = bool(
        np.array_equal(report_a.graded.grades, report_b.graded.grades)
        and np.array_equal(report_a.scores, report_b.scores, equal_nan=True)
    )
    return {
        "ok": grades_equal
        and all(r["dates_equal"] and r["returns_equal"] for r in lines),
        "grades_and_scores_equal": grades_equal,
        "lines": lines,
    }


# The graded score's rank IC at 20 and 60 sessions (`desk.calibrate`): how
# the analysts are measured, attached so a re-graded desk and the incumbent
# can be read side by side.
def rank_ic(report) -> dict[str, dict[str, float]]:
    """Return {"h20": {...}, "h60": {...}} of the graded score's rank IC."""
    from backend.agents.trading.desk import desk

    out: dict[str, dict[str, float]] = {}
    for horizon in (20, 60):
        _, harness = desk.calibrate(report, horizon)
        out[f"h{horizon}"] = {
            "rank_ic": float(harness.mean_ic),
            "ic_t": float(harness.ic_tstat),
            "net_sharpe": float(harness.net_sharpe),
        }
    return out


# The stance tables read and laid onto the report's panel, in the order
# given, each with its audit record.
def load_stance_tables(paths, report) -> list[stance_table.Aligned]:
    """Return the Aligned tables for `paths` on `report.panel`."""
    panel = report.panel
    return [stance_table.align(stance_table.load(path), panel) for path in paths]


# The payload's "stance_tables" block: each table's path, sha256, grade
# name, row audit, the mode, and what the tables did to the grade counts
# of the eligible book per window (before: the desk as run; after: with
# the tables).
def stance_record(
    plain, regraded, aligned: list[stance_table.Aligned], mode: str, mask: np.ndarray
) -> dict[str, object]:
    """Return the payload's "stance_tables" block."""
    return {
        "mode": mode,
        "tables": [item.record for item in aligned],
        "grades": stance_table.grade_record(plain, regraded, mask, WINDOWS),
    }


# The file-name tag a stance mode carries: stance_sixth, stance_replace_<analyst>.
def stance_tag(mode: str) -> str:
    """Return the tag for `mode`."""
    kind, analyst = stance_table.parse_mode(mode)
    return f"stance_{kind}" if analyst is None else f"stance_{kind}_{analyst}"


# Run everything and assemble the payload; `report` is the desk's unrestricted report.
def build(
    report, store, offsets: int, costs: tuple[float, ...], history_path=None, arm=None
) -> dict:
    """Return the scorecard payload; `arm` as in `price_offset`."""
    panel = report.panel
    restricted, mask = (
        point_in_time.point_in_time(report, history_path)
        if history_path
        else point_in_time.point_in_time(report)
    )
    members = mask.sum(axis=1)
    payload: dict[str, object] = {
        "metrics_version": METRICS_VERSION,
        "asof": str(panel.dates[-1]),
        "offsets": offsets,
        "costs_bps": list(costs),
        "windows": {k: [str(s) if s else None, str(e) if e else None] for k, (s, e) in WINDOWS.items()},
        "book": {
            "names_today": int(len(panel.tickers) - 1),
            "eligible_first_session": int(members[0]),
            "eligible_last_session": int(members[-1]),
            "eligible_median": float(np.median(members)),
        },
        "membership": str(history_path or universe.MEMBERSHIP_HISTORY_PATH),
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
    }
    payload["curves"] = {}
    for cost in costs:
        priced = [
            price_offset(report, restricted, mask, store, _since(panel, k), cost, arm)
            for k in range(offsets)
        ]
        payload["rows"].extend(summarise(priced, cost))
        payload["paired"].extend(paired(priced, cost))
        payload["curves"][f"{cost:g}"] = median_offset_curves(priced)
    return payload


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
        f"{book['eligible_first_session']} at the start, {book['eligible_last_session']} "
        f"at the end, median {book['eligible_median']:.0f}"
    )
    stances = payload.get("stance_tables")
    if stances:
        lines.append(f"stance tables, mode {stances['mode']}:")
        for table in stances["tables"]:
            lines.append(
                f"  {table['path']} sha256 {table['sha256'][:12]}... as "
                f"{table['name']}: {table['rows']} rows, {table['rows_used']} on "
                f"the panel, {table['cells_bullish']} bullish / "
                f"{table['cells_bearish']} bearish cells"
            )
        for window, moved in stances["grades"].items():
            before, after = moved["before"], moved["after"]
            lines.append(
                f"  {window}: A+ {before['A+']} -> {after['A+']}, "
                f"A {before['A']} -> {after['A']}, B {before['B']} -> {after['B']}, "
                f"C {before['C']} -> {after['C']}; {moved['moved']} of "
                f"{moved['eligible_name_sessions']} name-sessions moved "
                f"({moved['moved_up']} up, {moved['moved_down']} down)"
            )
    for cost in payload["costs_bps"]:
        for window in WINDOWS:
            lines.append(f"\n{cost:g} bp, {window}  (median / worst across {payload['offsets']} offsets)")
            lines.append(f"  {'line':<34}{'CAGR':>8}{'worst':>8}{'maxDD':>8}{'Sharpe':>8}{'>EW-PIT':>9}{'>QQQ':>7}")
            for row in payload["rows"]:
                if row["cost_bps"] != cost or row["window"] != window:
                    continue
                lines.append(
                    f"  {row['line']:<34}{_pct(row['median_cagr']):>8}{_pct(row['worst_cagr']):>8}"
                    f"{_pct(row['median_drawdown']):>8}{row['median_sharpe']:>8.2f}"
                    f"{row['offsets_above_ew_pit']:>9}{row['offsets_above_qqq']:>7}"
                )
            for pair in payload["paired"]:
                if pair["cost_bps"] != cost or pair["window"] != window:
                    continue
                lines.append(
                    f"  paired {pair['line']} minus {pair['against']}: "
                    f"{pair['mean_daily_bp']:+.1f} bp/day, HAC t {pair['hac_t']:.2f}, PSR {pair['psr']:.2f}"
                )
    return "\n".join(lines)


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
        "--stance-table",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help="a point-in-time stance table (session, ticker, stance[, conviction "
        "| rank]; parquet or CSV) graded with the desk's five under "
        "--stance-mode; repeatable in sixth mode, one in replace mode; writes "
        "pit_scorecard_..._stance_<mode>.json",
    )
    parser.add_argument(
        "--stance-mode",
        default=stance_table.MODE_SIXTH,
        help="how a stance table is graded: 'sixth' (a further full vote under "
        "the unchanged rule, never a veto) or 'replace:<analyst>' (the table "
        f"takes that analyst's place); analysts: {', '.join(stance_table.ANALYSTS)}",
    )
    parser.add_argument(
        "--rank-ic",
        action="store_true",
        help="attach the graded score's rank IC at 20 and 60 sessions",
    )
    parser.add_argument(
        "--membership",
        type=Path,
        help="the dated membership file the point-in-time mask reads "
        "(default: the book's)",
    )
    parser.add_argument("--output", type=Path, help="where to write the payload")
    parser.add_argument(
        "--null-test",
        action="store_true",
        help="with --stance-table: grade the book with the same rows zeroed in "
        "sixth mode against the plain desk, and assert the grades, scores and "
        "every line are reproduced to the bit at two offsets; no payload",
    )
    args = parser.parse_args(argv)
    _check_stance_arguments(parser, args)
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
    history = args.membership or universe.MEMBERSHIP_HISTORY_PATH
    # The book is asked for exactly as before; a stance table re-grades it.
    plain = desk.run(
        store,
        None,
        inputs=(desk.EXPECTATIONS_GAP,),
        signed_rotation=args.signed_rotation,
    )
    aligned = load_stance_tables(args.stance_table, plain)
    if args.null_test:
        zeroed = [stance_table.zeroed(item) for item in aligned]
        through = stance_table.regrade(plain, zeroed, stance_table.MODE_SIXTH)
        verdict = null_test(plain, through, store, history, 2, tuple(args.costs), arm)
        verdict["tables"] = [item.record for item in aligned]
        print(render_null_test(verdict))
        return 0 if verdict["ok"] else 1
    report = plain
    if aligned:
        report = stance_table.regrade(plain, aligned, args.stance_mode)
    payload = build(
        report, store, args.offsets, tuple(args.costs), history_path=history, arm=arm
    )
    if args.graded_cap is not None:
        restricted, mask = point_in_time.point_in_time(report, history)
        payload["cap"] = args.graded_cap
        payload["concentration"] = concentration(restricted, mask, arm(restricted, mask))
    if args.rank_ic:
        payload["rank_ic"] = rank_ic(report)
    if aligned:
        _, mask = point_in_time.point_in_time(report, history)
        payload["stance_tables"] = stance_record(
            plain, report, aligned, args.stance_mode, mask
        )
    tags = [
        t
        for t, on in (
            ("signed_rotation", args.signed_rotation),
            (args.arm, args.arm),
            (cap_tag, cap_tag),
            (stance_tag(args.stance_mode) if aligned else None, bool(aligned)),
        )
        if on
    ]
    payload["arm"] = " + ".join(tags) if tags else "frozen rule"
    name = FILE if not tags else FILE.replace(".json", "_" + "_".join(tags) + ".json")
    target = args.output or root / "desk" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")
    print(render(payload))
    print(f"\nwrote {target}")
    return 0


# The stance-table arguments checked before the desk is asked for anything:
# a mode that parses, one table in replace mode, tables that exist, and a
# null test that has a table to zero.
def _check_stance_arguments(parser: argparse.ArgumentParser, args) -> None:
    """Exit through `parser.error` on a bad stance-table command line."""
    try:
        kind, _ = stance_table.parse_mode(args.stance_mode)
    except ValueError as exc:
        parser.error(str(exc))
    if kind == stance_table.MODE_REPLACE and len(args.stance_table) != 1:
        parser.error("--stance-mode replace:<analyst> takes exactly one --stance-table")
    missing = [str(p) for p in args.stance_table if not p.is_file()]
    if missing:
        parser.error(f"--stance-table not found: {', '.join(missing)}")
    if args.null_test and not args.stance_table:
        parser.error("--null-test needs --stance-table: it tests that path")


# The null test's verdict as text: one line per mismatch, or the all-clear.
def render_null_test(verdict: dict) -> str:
    """Return the null test as text."""
    lines = [
        "null test: the book re-graded with the stance table's rows zeroed "
        "(sixth mode) against the plain desk",
    ]
    for table in verdict.get("tables", []):
        lines.append(
            f"  table {table['path']} sha256 {table['sha256']}: "
            f"{table['rows']} rows, {table['rows_used']} on the panel"
        )
    lines.extend(
        [
            f"  grades and scores equal: {verdict['grades_and_scores_equal']}",
            f"  lines compared: {len(verdict['lines'])}",
        ]
    )
    for row in verdict["lines"]:
        if not (row["dates_equal"] and row["returns_equal"]):
            lines.append(
                f"  MISMATCH {row['cost_bps']:g} bp offset {row['offset']} "
                f"{row['line']}: dates {row['dates_equal']}, "
                f"returns {row['returns_equal']}"
            )
    passed = "PASS, reproduced to the bit" if verdict["ok"] else "FAIL"
    lines.append(f"  verdict: {passed}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
