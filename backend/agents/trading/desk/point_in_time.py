"""Restrict a desk report to the names the book could have held on each session.

`desk.run` grades the book as it stands today over the whole history, so a
backtest on its report holds names the desk could not have known about:
2024-25 listings, this year's overlay, names chosen because they won. This
module applies the dated membership history (`universe.as_of`) to a report:
on every session, a name outside its membership interval is graded C and
given no score, so the rules cannot select it, size it or rank it. Nothing
else about the report changes, and the panel keeps every column, so prices
and benchmarks line up exactly with the unrestricted run.

The masked report is what a point-in-time backtest runs on, and the same
mask defines the equal-weight book that is the survivorship hurdle.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk.grading import ORDINAL, C
from backend.market import membership, universe


# (T, N) True where the name was a book member on the session, from the
# dated intervals. A name with no interval at all is never eligible.
def eligibility(
    dates: np.ndarray,
    tickers: tuple[str, ...],
    history_path: Path = universe.MEMBERSHIP_HISTORY_PATH,
) -> np.ndarray:
    """Return the (T, N) Boolean membership mask."""
    records = membership.load_history(history_path)
    days = np.asarray(dates, dtype="datetime64[D]")
    mask = np.zeros((len(days), len(tickers)), dtype=bool)
    column = {t: i for i, t in enumerate(tickers)}
    for row in records:
        j = column.get(row.ticker)
        if j is None:
            continue
        start = np.datetime64(max(row.entered, row.entry_announced), "D")
        lo = int(np.searchsorted(days, start, side="left"))
        hi = len(days)
        if row.exited is not None:
            hi = int(np.searchsorted(days, np.datetime64(row.exited, "D"), side="left"))
        if lo < hi:
            mask[lo:hi, j] = True
    return mask


# The report with every non-member (session, name) graded C and unscored.
def restrict(report, mask: np.ndarray):
    """Return a copy of `report` restricted to `mask`; the panel is untouched."""
    graded = report.graded
    if mask.shape != graded.grades.shape:
        raise ValueError("mask must match the report's (T, N) shape")
    grades = np.where(mask, graded.grades, ORDINAL[C])
    conviction = None
    if graded.conviction is not None:
        conviction = np.where(mask, graded.conviction, np.nan)
    scores = np.where(mask, report.scores, np.nan)
    restricted = replace(graded, grades=grades, conviction=conviction)
    return replace(report, graded=restricted, scores=scores)


# One call: mask from the history, then restrict.
def point_in_time(report, history_path: Path = universe.MEMBERSHIP_HISTORY_PATH):
    """Return (restricted report, mask)."""
    mask = eligibility(report.panel.dates, tuple(report.panel.tickers), history_path)
    benchmark = report.panel.index(report.panel.benchmark)
    mask[:, benchmark] = False
    return restrict(report, mask), mask


# An allocator for `simulate.run(allocator=...)`: equal weight across every
# member of the book on the decision session, the benchmark excluded, at
# `gross` of equity. It reads only the mask at `t`, so it cannot see the
# future through the unsliced panel the hook receives.
def equal_weight_allocator(mask: np.ndarray, gross: float = 1.0):
    """Return a callable (report, panel, config, t) -> target weights."""

    def allocate(report, panel, config, t: int) -> np.ndarray:
        eligible = mask[t].copy()
        eligible[panel.index(panel.benchmark)] = False
        # A name with no price on the decision day cannot be bought.
        eligible &= np.isfinite(panel.adj_close[t])
        targets = np.zeros(len(panel.tickers))
        count = int(eligible.sum())
        if count:
            targets[eligible] = gross / count
        return targets

    return allocate


# Sessions on or after `start` and before `end`, as a Boolean mask over dates.
def window(dates: np.ndarray, start: date | None, end: date | None) -> np.ndarray:
    """Return the (T,) mask of sessions inside [start, end)."""
    days = np.asarray(dates, dtype="datetime64[D]")
    out = np.ones(len(days), dtype=bool)
    if start is not None:
        out &= days >= np.datetime64(start, "D")
    if end is not None:
        out &= days < np.datetime64(end, "D")
    return out


# Arm P1.2 of the volatile-book plan: capped equal weight across every name
# the desk grades A or better on the decision session, within the book's
# membership, at most `cap` of equity each, never more than `gross` in
# total. With ten or more qualifying names the book is fully invested and
# equal weight; with fewer, each takes `cap` and the rest stays in cash
# (the plan's rule: leftover cash stays in cash). No volatility target, no
# regime multiplier and no grade ladder: those are exactly what the arm
# removes, and each is measured by the scorecard rather than assumed.
def graded_equal_weight_allocator(
    mask: np.ndarray, min_grade: int, cap: float = 0.10, gross: float = 1.0
):
    """Return a callable (report, panel, config, t) -> target weights."""
    if not 0 < cap <= gross <= 1.0:
        raise ValueError("need 0 < cap <= gross <= 1")

    def allocate(report, panel, config, t: int) -> np.ndarray:
        eligible = mask[t] & (report.graded.grades[t] >= min_grade)
        eligible[panel.index(panel.benchmark)] = False
        eligible &= np.isfinite(panel.adj_close[t])
        targets = np.zeros(len(panel.tickers))
        count = int(eligible.sum())
        if count:
            targets[eligible] = min(gross / count, cap)
        return targets

    return allocate
