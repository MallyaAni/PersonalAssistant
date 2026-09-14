"""Daily-data research mechanics; no dashboard, account or broker writes.

Decide after close t, execute after close t+1, then hold to the next decision.
Adjusted-price units approximate reinvested total return, not broker shares.
Missing prices on a held asset invalidate the path instead of becoming zero.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np

from backend.market import calendar, growth_objective

ACTION_NAMES = (
    "USD",
    "momentum20",
    "half_momentum20",
    "momentum120",
    "half_momentum120",
    "equal",
    "half_equal",
)
FEATURE_NAMES = (
    "return5",
    "return20",
    "return60",
    "return120",
    "vol20",
    "distance_ma20",
    "distance_ma60",
    "relative_volume",
)


@dataclass(frozen=True)
class Dataset:
    dates: np.ndarray
    prices: np.ndarray
    features: np.ndarray
    eligible: np.ndarray
    market: np.ndarray
    tickers: tuple[str, ...]
    benchmark: int


# Build causal numerical inputs and keep missing observations explicit.
def dataset(panel):
    prices = panel.adj_close
    rows, names = prices.shape
    features = np.full((rows, names, len(FEATURE_NAMES)), np.nan)
    with np.errstate(all="ignore"):
        for channel, lag in enumerate((5, 20, 60, 120)):
            features[lag:, :, channel] = np.log(prices[lag:] / prices[:-lag])
        returns = panel.log_returns()
        for t in range(120, rows):
            features[t, :, 4] = np.std(returns[t - 19 : t + 1], axis=0)
            features[t, :, 5] = prices[t] / np.mean(prices[t - 19 : t + 1], axis=0) - 1
            features[t, :, 6] = prices[t] / np.mean(prices[t - 59 : t + 1], axis=0) - 1
            features[t, :, 7] = (
                panel.volume[t] / np.mean(panel.volume[t - 19 : t + 1], axis=0) - 1
            )
    eligible = np.isfinite(features).all(axis=2) & (prices > 0)
    benchmark = panel.index(panel.benchmark)
    eligible[:, benchmark] = False
    # Unscheduled emergency decisions were not knowable in advance.
    scheduled = [
        d
        for d in calendar.fomc_decisions()
        if d not in (date(2020, 3, 3), date(2020, 3, 15))
    ]
    ahead, since = calendar._fomc_distances(panel.dates, scheduled)
    count = np.maximum(eligible.sum(axis=1), 1)
    breadth = ((features[:, :, 1] > 0) & eligible).sum(axis=1) / count
    market = np.column_stack((features[:, benchmark], breadth, ahead / 30, since / 30))
    return Dataset(
        panel.dates, prices, features, eligible, market, panel.tickers, benchmark
    )


# Select by evidence known on the decision date, with a ten-percent name limit.
def basket(scores, eligible, gross=1.0):
    candidates = np.flatnonzero(eligible & np.isfinite(scores))
    chosen = candidates[np.argsort(-scores[candidates], kind="stable")[:10]]
    out = np.zeros(len(scores))
    if len(chosen):
        out[chosen] = min(gross / len(chosen), 0.1)
    return out


# Give the learner fixed, interpretable stock baskets plus explicit cash choices.
def actions(data, t):
    m20 = basket(data.features[t, :, 1], data.eligible[t])
    m120 = basket(data.features[t, :, 3], data.eligible[t])
    equal = data.eligible[t].astype(float)
    equal *= min(1 / max(equal.sum(), 1), 0.1)
    return np.stack(
        (np.zeros_like(equal), m20, 0.5 * m20, m120, 0.5 * m120, equal, 0.5 * equal)
    )


# Charge costs against traded dollars while solving for a fully funded target.
def rebalance(holdings, cash, target, cost):
    if not np.isfinite(target).all() or np.any(target < 0) or target.sum() > 1 + 1e-9:
        raise ValueError("Long-only funded target required")
    if not 0 <= cost < 0.1:
        raise ValueError("Invalid proportional execution cost")
    nav = cash + holdings.sum()
    low, high = 0.0, nav
    for _ in range(60):
        net = (low + high) / 2
        paid = cost * np.abs(target * net - holdings).sum()
        if net + paid > nav:
            high = net
        else:
            low = net
    net = (low + high) / 2
    new = target * net
    turnover = float(np.abs(new - holdings).sum() / nav)
    return new, float(net - new.sum()), turnover


# Mark only held assets; an absent price cannot silently improve an experiment.
def mark(holdings, previous, current):
    held = holdings > 1e-12
    if np.any(
        held
        & (
            ~np.isfinite(previous)
            | ~np.isfinite(current)
            | (previous <= 0)
            | (current <= 0)
        )
    ):
        raise ValueError("Missing held-asset price invalidates the path")
    result = holdings.copy()
    result[held] *= current[held] / previous[held]
    return result


# Advance a real sequential account through a delayed trade and daily marks.
def transition(data, t, end, holdings, cash, target, cost):
    if end <= t or end >= len(data.dates):
        raise ValueError("A later observed session is required")
    initial = float(cash + holdings.sum())
    navs, turnover = [], 0.0
    for day in range(t + 1, end + 1):
        holdings = mark(holdings, data.prices[day - 1], data.prices[day])
        if day == t + 1:
            if np.any(
                (target > 0)
                & (~np.isfinite(data.prices[day]) | (data.prices[day] <= 0))
            ):
                raise ValueError("Missing execution price invalidates the path")
            holdings, cash, turnover = rebalance(holdings, cash, target, cost)
        navs.append(float(cash + holdings.sum()))
    return holdings, cash, navs, growth_objective.reward(initial, navs[-1]), turnover


# Purge the full label endpoint rather than splitting examples at their start.
def split_rows(data, start, stop, horizon=5):
    valid = np.isfinite(data.market).all(axis=1)
    rows = np.flatnonzero(
        (data.dates >= np.datetime64(start))
        & (data.dates < np.datetime64(stop))
        & valid
    )
    return np.array(
        [
            t
            for t in rows
            if t + horizon < len(data.dates)
            and data.dates[t + horizon] < np.datetime64(stop)
        ],
        dtype=int,
    )


# Show market conditions and current account allocation without future outcomes.
def policy_state(data, t, holdings, cash, mean, scale):
    nav = cash + holdings.sum()
    weights = holdings / nav
    turnover = np.abs(actions(data, t) - weights).sum(axis=1)
    market = np.clip((data.market[t] - mean) / scale, -5, 5)
    return np.concatenate((market, [cash / nav], turnover)).astype(np.float32)


# Evaluate one continuous account, preserving holdings across regime boundaries.
def evaluate(data, rows, chooser, cost=0.001, stride=5):
    first, last = int(rows[0]), int(rows[-1]) + 1
    holdings, cash = np.zeros(data.prices.shape[1]), 1.0
    dates, navs, decisions = [str(data.dates[first])], [1.0], []
    for t in range(first, last, stride):
        end = min(t + stride, last)
        target, name = chooser(t, holdings, cash)
        holdings, cash, path, _, turnover = transition(
            data, t, end, holdings, cash, target, cost
        )
        navs.extend(path)
        dates.extend(str(d) for d in data.dates[t + 1 : end + 1])
        decisions.append(
            {
                "decision": str(data.dates[t]),
                "execution": str(data.dates[t + 1]),
                "action": name,
                "target_cash": float(1 - target.sum()),
                "turnover": turnover,
            }
        )
    return {
        "metrics": growth_objective.evaluate(navs),
        "dates": dates,
        "nav": navs,
        "decisions": decisions,
        "regimes": regime_metrics(dates, navs),
    }


# Separate event days from the first fully post-announcement daily sessions.
def regime_metrics(dates, navs):
    dates = np.asarray(dates, dtype="datetime64[D]")
    navs = np.asarray(navs)
    periods = (
        ("before_june_statement", "1900-01-01", "2026-06-17"),
        ("june_statement_day", "2026-06-17", "2026-06-18"),
        ("after_june_before_jackson_hole", "2026-06-18", "2026-08-28"),
        ("jackson_hole_day", "2026-08-28", "2026-08-29"),
        ("after_jackson_hole", "2026-08-29", "2100-01-01"),
    )
    result = {}
    for name, start, stop in periods:
        indices = np.flatnonzero(
            (dates >= np.datetime64(start))
            & (dates < np.datetime64(stop))
            & (np.arange(len(dates)) > 0)
        )
        if len(indices):
            metrics = growth_objective.evaluate(
                navs[indices[0] - 1 : indices[-1] + 1].tolist()
            )
            result[name] = {
                **metrics,
                "first": str(dates[indices[0]]),
                "last": str(dates[indices[-1]]),
                "scheduled_decisions": sum(
                    str(d) in set(dates[indices].astype(str))
                    for d in calendar.fomc_decisions()
                ),
            }
    return result
