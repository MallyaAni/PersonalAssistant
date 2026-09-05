"""The baselines a learned model has to beat.

Each baseline turns the Panel into a score matrix (sessions x tickers): a
higher score means the name should be ranked higher for the coming horizon,
NaN means the baseline has no opinion for that name on that day (not enough
history, or no theme). Every score at session t reads only sessions <= t.

These are deliberately the well-known cross-sectional effects — price
momentum, relative strength versus the market, the strength of a name's
own theme basket — because a network that cannot beat them out of sample,
net of costs, has learned nothing worth trading. They are also what the
hand-coded "sector report" amounts to, made measurable.
"""

import numpy as np

from backend.market.panel import Panel


# The sum of log returns over the `length` sessions ending `skip` sessions
# before t, per ticker; NaN unless every session in that span is known.
def trailing_sum(returns: np.ndarray, length: int, skip: int = 0) -> np.ndarray:
    """Return (T, N) rolling sums of `length` sessions ending `skip` sessions ago."""
    if length < 1 or skip < 0:
        raise ValueError("length >= 1 and skip >= 0 are required")
    known = np.isfinite(returns)
    filled = np.where(known, returns, 0.0)
    cumulative = np.vstack([np.zeros((1, returns.shape[1])), np.cumsum(filled, axis=0)])
    counts = np.vstack([np.zeros((1, returns.shape[1])), np.cumsum(known, axis=0)])
    out = np.full_like(returns, np.nan)
    rows = returns.shape[0]
    for t in range(length + skip - 1, rows):
        end = t - skip + 1  # exclusive index into the cumulative arrays
        start = end - length
        complete = (counts[end] - counts[start]) == length
        out[t] = np.where(complete, cumulative[end] - cumulative[start], np.nan)
    return out


# Classic price momentum: the return over roughly twelve months, skipping
# the most recent month (whose reversal effect would otherwise cancel it).
def momentum(panel: Panel, length: int = 252, skip: int = 21) -> np.ndarray:
    """Score = trailing `length`-session log return ending `skip` sessions ago."""
    return trailing_sum(panel.log_returns(), length, skip)


# Relative strength versus the market: the name's trailing return minus the
# benchmark's over the same sessions.
def relative_strength(panel: Panel, lookback: int = 20) -> np.ndarray:
    """Score = own trailing return minus the benchmark's over `lookback` sessions."""
    own = trailing_sum(panel.log_returns(), lookback)
    bench = own[:, panel.index(panel.benchmark)][:, None]
    return own - bench


# Theme momentum: the trailing return of the name's own theme basket. Every
# member of a theme gets the same score, so this ranks baskets, not names —
# it is the pure rotation signal.
def theme_momentum(panel: Panel, lookback: int = 20) -> np.ndarray:
    """Score = trailing return of the ticker's primary theme basket."""
    theme_daily = panel.theme_return_matrix()
    scores = trailing_sum(theme_daily, lookback)
    # A name with no theme has no rotation opinion.
    for column, ticker in enumerate(panel.tickers):
        if panel.primary_theme(ticker) is None:
            scores[:, column] = np.nan
    return scores


# Relative strength within the theme: the name's trailing return minus its
# basket's. This is stock selection with rotation removed.
def theme_relative_strength(panel: Panel, lookback: int = 20) -> np.ndarray:
    """Score = own trailing return minus the primary theme basket's."""
    own = trailing_sum(panel.log_returns(), lookback)
    theme = trailing_sum(panel.theme_return_matrix(), lookback)
    scores = own - theme
    for column, ticker in enumerate(panel.tickers):
        if panel.primary_theme(ticker) is None:
            scores[:, column] = np.nan
    return scores


# Cross-sectional percentile rank per row, NaN preserved. Ties share the
# average rank so a basket-level score does not fabricate an order.
def percentile_rank(scores: np.ndarray) -> np.ndarray:
    """Return (T, N) percentile ranks in [0, 1] across each row's known scores."""
    out = np.full_like(scores, np.nan)
    for t in range(scores.shape[0]):
        row = scores[t]
        known = np.isfinite(row)
        n = int(known.sum())
        if n < 2:
            continue
        out[t, known] = average_rank(row[known]) / (n - 1)
    return out


# Average ranks (0-based) with ties sharing their mean rank.
def average_rank(values: np.ndarray) -> np.ndarray:
    """Return 0-based average ranks of a 1-D array, ties averaged."""
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(len(values), dtype=np.float64)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0
        i = j + 1
    return ranks


# The mean of several baselines' percentile ranks; NaN where any is NaN.
def rank_blend(*score_matrices: np.ndarray) -> np.ndarray:
    """Return the average cross-sectional percentile rank across baselines."""
    if not score_matrices:
        raise ValueError("at least one score matrix is required")
    ranked = [percentile_rank(m) for m in score_matrices]
    return np.mean(np.stack(ranked, axis=0), axis=0)


# Every baseline by name, at the default parameters, for a report.
def all_baselines(panel: Panel) -> dict[str, np.ndarray]:
    """Return {name: score matrix} for the standard baseline set."""
    rs = relative_strength(panel)
    tm = theme_momentum(panel)
    return {
        "momentum_12_1": momentum(panel),
        "relative_strength_20": rs,
        "theme_momentum_20": tm,
        "theme_relative_strength_20": theme_relative_strength(panel),
        "rotation_blend": rank_blend(rs, tm),
    }
