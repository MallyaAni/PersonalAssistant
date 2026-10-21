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


# Equal risk instead of equal weight: every A-or-better name within the
# book's membership, sized inversely to its own trailing volatility so that a
# wild name takes less of the book than a quiet one, fully invested (or up
# to `gross`), each name at most `cap`. The volatility is the standard
# deviation of the last `window` daily log returns of adjusted close ending
# on the decision session, so nothing after that session is read. A name
# without `window` prior returns, or with zero variance, is not sized rather
# than given a guessed risk. Registered as an arm beside equal weight so the
# scorecard measures what the risk weighting buys, if anything; the only
# parameters are the window and the operator's hold limit.
def graded_inverse_volatility_allocator(
    mask: np.ndarray,
    min_grade: int,
    window: int = 63,
    cap: float = 1.0,
    gross: float = 1.0,
):
    """Return a callable (report, panel, config, t) -> inverse-volatility weights."""
    if not 0 < cap <= gross <= 1.0:
        raise ValueError("need 0 < cap <= gross <= 1")
    if window < 2:
        raise ValueError("need at least two returns for a volatility")

    def allocate(report, panel, config, t: int) -> np.ndarray:
        eligible = mask[t] & (report.graded.grades[t] >= min_grade)
        eligible[panel.index(panel.benchmark)] = False
        eligible &= np.isfinite(panel.adj_close[t])
        targets = np.zeros(len(panel.tickers))
        if t < window or not eligible.any():
            return targets
        closes = np.asarray(panel.adj_close[t - window : t + 1], dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            returns = np.diff(np.log(closes), axis=0)
        volatility = np.nanstd(returns, axis=0, ddof=1)
        known = (
            np.isfinite(returns).all(axis=0)
            & np.isfinite(volatility)
            & (volatility > 0)
        )
        eligible &= known
        if not eligible.any():
            return targets
        inverse = np.where(eligible, 1.0 / volatility, 0.0)
        weights = gross * inverse / inverse.sum()
        # A name over the hold limit is trimmed to it; the excess is left in
        # cash rather than pushed onto the others, so the limit never makes
        # another name larger than its risk says.
        targets[eligible] = np.minimum(weights[eligible], cap)
        return targets

    return allocate


# Exposure control without a forecast: the equal-weight A-or-better book,
# scaled down as a whole when its own recent volatility is high. The basket's
# realised volatility is the standard deviation of the equal-weight basket's
# last `window` daily log returns (the names eligible on the decision
# session, so nothing after it is read), annualised; the book holds
# min(1, target / realised) of equity and the rest stays in cash. The 0.30
# target is the one the frozen rule already used, kept rather than tuned.
def graded_volatility_targeted_allocator(
    mask: np.ndarray,
    min_grade: int,
    window: int = 63,
    target: float = 0.30,
    cap: float = 1.0,
):
    """Return a callable (report, panel, config, t) -> equal weights at a volatility target."""
    if not 0 < cap <= 1.0 or not target > 0 or window < 2:
        raise ValueError(
            "need 0 < cap <= 1, a positive target and a window of two or more"
        )
    equal = graded_equal_weight_allocator(mask, min_grade, cap=cap, gross=1.0)

    def allocate(report, panel, config, t: int) -> np.ndarray:
        targets = equal(report, panel, config, t)
        held = targets > 0
        if t < window or not held.any():
            return targets
        closes = np.asarray(panel.adj_close[t - window : t + 1], dtype=float)[:, held]
        with np.errstate(divide="ignore", invalid="ignore"):
            returns = np.diff(np.log(closes), axis=0)
        basket = np.nanmean(returns, axis=1)
        if not np.isfinite(basket).all() or len(basket) < 2:
            return targets
        realised = float(np.std(basket, ddof=1)) * np.sqrt(252.0)
        if not realised > 0:
            return targets
        return targets * min(1.0, target / realised)

    return allocate


# Per-name price tilts on the equal-weight book. The owner asked whether the
# size of a name should depend on where its price is, so each tilt turns one
# reading of the name's own past prices into a multiplier on its equal-weight
# slot; the slots are renormalised to the gross and then scaled to the
# volatility target like the untilted book, so a tilt changes how the book is
# shared out, not how much of the book is invested. Every reading ends on the
# decision session. The three tilts are the three honest answers to "buy more
# when...": the name is trending (price above its trailing average), the name
# has pulled back (price below its trailing high), the name has led its peers
# (trailing return rank). Each has one parameter beyond the window so the
# scorecard measures the idea, not a fit.
def _tilt_trend(closes: np.ndarray, strength: float) -> np.ndarray:
    """(window+1, n) closes -> 1 above the window's mean close, 1-strength below."""
    mean = np.nanmean(closes[:-1], axis=0)
    return np.where(closes[-1] > mean, 1.0, 1.0 - strength)


def _tilt_pullback(closes: np.ndarray, strength: float) -> np.ndarray:
    """(window+1, n) closes -> 1 at the window high, up to 1+strength at a full retreat."""
    high = np.nanmax(closes, axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        retreat = 1.0 - closes[-1] / high
    return 1.0 + strength * np.clip(np.nan_to_num(retreat), 0.0, 1.0)


def _tilt_leader(closes: np.ndarray, strength: float) -> np.ndarray:
    """(window+1, n) closes -> 1-strength for the weakest trailing return,
    1+strength for the strongest."""
    with np.errstate(divide="ignore", invalid="ignore"):
        trailing = closes[-1] / closes[0] - 1.0
    order = np.argsort(np.argsort(np.nan_to_num(trailing)))
    if len(order) < 2:
        return np.ones(len(order))
    return 1.0 + strength * (2.0 * order / (len(order) - 1) - 1.0)


TILTS = {"trend": _tilt_trend, "pullback": _tilt_pullback, "leader": _tilt_leader}


def graded_tilted_allocator(
    mask: np.ndarray,
    min_grade: int,
    tilt: str,
    strength: float = 0.5,
    window: int = 63,
    target: float = 0.25,
    cap: float = 1.0,
    vol_window: int = 63,
):
    """Return a callable (report, panel, config, t) -> tilted, vol-targeted weights."""
    if tilt not in TILTS:
        raise ValueError(f"unknown tilt {tilt!r}; one of {sorted(TILTS)}")
    if not 0 <= strength <= 1 or window < 2 or not 0 < cap <= 1.0:
        raise ValueError(
            "need 0 <= strength <= 1, a window of two or more and 0 < cap <= 1"
        )
    read = TILTS[tilt]
    scaled = graded_volatility_targeted_allocator(
        mask, min_grade, window=vol_window, target=target, cap=1.0
    )

    def allocate(report, panel, config, t: int) -> np.ndarray:
        base = scaled(report, panel, config, t)
        held = base > 0
        if t < window or not held.any():
            return base
        gross = float(base.sum())
        closes = np.asarray(panel.adj_close[t - window : t + 1], dtype=float)[:, held]
        multipliers = read(closes, strength)
        if not np.isfinite(multipliers).all() or not multipliers.sum() > 0:
            return base
        targets = np.zeros(len(base))
        targets[held] = gross * multipliers / multipliers.sum()
        return np.minimum(targets, cap)

    return allocate
