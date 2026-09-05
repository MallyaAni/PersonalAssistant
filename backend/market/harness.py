"""The walk-forward harness: the only numbers that mean anything.

Two things live here.

`evaluate_scores` takes any score matrix — a baseline, a model's output —
and measures it the way a portfolio would experience it: on each rebalance
date (every `horizon` sessions, so consecutive labels never overlap) it
ranks the names that have a score and a fully known forward return, records
the rank correlation between score and *residual* forward return (own minus
market, so a score that only says "the market will go up" earns nothing),
and holds an equal-weight long-short book of the top and bottom fractions
until the next rebalance. Turnover is charged at a per-unit cost, and the
report carries gross, cost and net so the cost of trading a signal is never
hidden inside it.

`walk_forward_folds` is for anything that is *fit*: it yields train and
test index ranges where the training range ends `horizon + embargo`
sessions before the test range begins. A window whose label ends inside
the test period is thereby excluded from training; this is the purge that
makes an out-of-sample number honest.

Everything here is numpy; no model framework is a dependency of measuring
one.
"""

import math
from dataclasses import dataclass

import numpy as np

from backend.market.baselines import average_rank
from backend.market.panel import Panel

SESSIONS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class PeriodResult:
    """One rebalance period's outcome."""

    date: np.datetime64
    names: int
    rank_ic: float
    gross_return: float
    turnover: float
    cost: float

    @property
    def net_return(self) -> float:
        return self.gross_return - self.cost


@dataclass(frozen=True, slots=True)
class HarnessReport:
    """A score matrix measured over every non-overlapping rebalance period."""

    horizon: int
    cost_bps: float
    periods: tuple[PeriodResult, ...]

    @property
    def count(self) -> int:
        return len(self.periods)

    @property
    def mean_ic(self) -> float:
        return (
            float(np.mean([p.rank_ic for p in self.periods]))
            if self.periods
            else float("nan")
        )

    # The t-statistic of the mean IC: how many standard errors from zero.
    @property
    def ic_tstat(self) -> float:
        ics = np.asarray([p.rank_ic for p in self.periods])
        if len(ics) < 2 or ics.std(ddof=1) == 0:
            return float("nan")
        return float(ics.mean() / (ics.std(ddof=1) / math.sqrt(len(ics))))

    @property
    def ic_hit_rate(self) -> float:
        return (
            float(np.mean([p.rank_ic > 0 for p in self.periods]))
            if self.periods
            else float("nan")
        )

    @property
    def mean_net_return(self) -> float:
        return (
            float(np.mean([p.net_return for p in self.periods]))
            if self.periods
            else float("nan")
        )

    @property
    def total_net_return(self) -> float:
        return (
            float(np.sum([p.net_return for p in self.periods]))
            if self.periods
            else float("nan")
        )

    @property
    def total_cost(self) -> float:
        return (
            float(np.sum([p.cost for p in self.periods]))
            if self.periods
            else float("nan")
        )

    # Net Sharpe annualised by the number of periods in a year.
    @property
    def net_sharpe(self) -> float:
        nets = np.asarray([p.net_return for p in self.periods])
        if len(nets) < 2 or nets.std(ddof=1) == 0:
            return float("nan")
        per_year = SESSIONS_PER_YEAR / self.horizon
        return float(nets.mean() / nets.std(ddof=1) * math.sqrt(per_year))


# Spearman rank correlation of two 1-D arrays with ties averaged.
def rank_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Return the Spearman correlation between `a` and `b`."""
    if len(a) < 3:
        return float("nan")
    ra, rb = average_rank(a), average_rank(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denominator = math.sqrt(float((ra * ra).sum()) * float((rb * rb).sum()))
    if denominator == 0:
        return float("nan")
    return float((ra * rb).sum() / denominator)


# Equal-weight long-short weights from one row of scores: +1/k on the top
# fraction, -1/k on the bottom fraction, 0 elsewhere. Sums to zero, and the
# long side sums to one.
def long_short_weights(scores: np.ndarray, top_fraction: float) -> np.ndarray:
    """Return weights over `scores` (NaN-free) for an equal-weight long-short book."""
    n = len(scores)
    k = max(1, int(math.floor(n * top_fraction)))
    order = np.argsort(scores, kind="mergesort")
    weights = np.zeros(n)
    weights[order[-k:]] = 1.0 / k
    weights[order[:k]] -= 1.0 / k
    return weights


# Measure a score matrix over non-overlapping rebalance periods.
#
# On each rebalance date the eligible names are those with a finite score
# and a finite forward return; the period is skipped when fewer than
# `min_names` qualify. Cost is `cost_bps` per unit of absolute weight
# traded, so a full flip of the book costs 2 x cost_bps x 2 sides.
def evaluate_scores(
    scores: np.ndarray,
    panel: Panel,
    horizon: int,
    cost_bps: float = 10.0,
    top_fraction: float = 0.2,
    min_names: int = 20,
    exclude: tuple[str, ...] = (),
) -> HarnessReport:
    """Return a HarnessReport for `scores` against residual forward returns."""
    if scores.shape != panel.adj_close.shape:
        raise ValueError("scores must have the panel's (sessions x tickers) shape")
    own_fwd = panel.forward_log_returns(horizon)
    market_fwd = own_fwd[:, panel.index(panel.benchmark)][:, None]
    residual = own_fwd - market_fwd
    simple_fwd = np.expm1(own_fwd)
    excluded = np.zeros(len(panel.tickers), dtype=bool)
    excluded[panel.index(panel.benchmark)] = True
    for ticker in exclude:
        if ticker in panel.tickers:
            excluded[panel.index(ticker)] = True

    periods: list[PeriodResult] = []
    previous_weights = np.zeros(len(panel.tickers))
    unit_cost = cost_bps / 10_000.0
    t = 0
    rows = len(panel.dates)
    while t + horizon < rows:
        eligible = np.isfinite(scores[t]) & np.isfinite(residual[t]) & ~excluded
        if eligible.sum() < min_names:
            t += 1
            continue
        columns = np.flatnonzero(eligible)
        ic = rank_correlation(scores[t, columns], residual[t, columns])
        weights = np.zeros(len(panel.tickers))
        weights[columns] = long_short_weights(scores[t, columns], top_fraction)
        gross = float((weights[columns] * simple_fwd[t, columns]).sum())
        turnover = float(np.abs(weights - previous_weights).sum())
        periods.append(
            PeriodResult(
                date=panel.dates[t],
                names=int(len(columns)),
                rank_ic=ic,
                gross_return=gross,
                turnover=turnover,
                cost=turnover * unit_cost,
            )
        )
        previous_weights = weights
        t += horizon
    return HarnessReport(horizon=horizon, cost_bps=cost_bps, periods=tuple(periods))


# Train/test index ranges for anything that is fit, with a purge.
#
# Each fold's test range is `test_size` sessions; the training range is the
# `train_size` sessions ending `horizon + embargo` sessions before the test
# range starts. Folds roll forward by `test_size`. Any training window
# ending in the purged span would carry a label overlapping the test period.
def walk_forward_folds(
    n_sessions: int,
    train_size: int,
    test_size: int,
    horizon: int,
    embargo: int = 0,
) -> list[tuple[range, range]]:
    """Return [(train_range, test_range), ...] with a purge of horizon + embargo."""
    if min(train_size, test_size, horizon) < 1 or embargo < 0:
        raise ValueError("sizes and horizon must be >= 1, embargo >= 0")
    folds: list[tuple[range, range]] = []
    gap = horizon + embargo
    test_start = train_size + gap
    while test_start + test_size <= n_sessions:
        train = range(test_start - gap - train_size, test_start - gap)
        test = range(test_start, test_start + test_size)
        folds.append((train, test))
        test_start += test_size
    return folds
