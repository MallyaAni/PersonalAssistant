"""Multi-scale causal features: what the leaderboard models actually read.

Every model on the Qlib leaderboard that reaches a rank IC near 0.05 reads
a wide set of rolling statistics (Alpha158 and its relatives), not eight
raw channels. This module builds that kind of input from the Panel, all of
it causal: a value at session t reads sessions <= t only.

Per (session, name), in this order:

    returns over 1, 5, 10, 20, 60 sessions
    returns relative to the market over 5, 20, 60
    returns relative to the theme basket over 5, 20, 60
    realised volatility over 5, 20, 60 (std of daily log returns)
    volatility ratio 5/60
    close over its 20- and 60-session max and min (log)
    distance from the 20- and 60-session mean close (log)
    log dollar volume, and its ratio to the 20- and 60-session mean
    correlation of daily returns with the market over 20 and 60
    beta to the market over 60
    mean daily range (log high/low) over 5 and 20
    gap sum over 5 (log open / previous close)
    close position in range, mean over 5

Everything is NaN until its window is complete, so a model never trains on
a partial statistic. Nothing here is a trading signal; each is a summary
the network is free to ignore.
"""

import numpy as np

from backend.market.baselines import trailing_sum
from backend.market.panel import Panel

ALPHA_NAMES: tuple[str, ...] = (
    "ret_1",
    "ret_5",
    "ret_10",
    "ret_20",
    "ret_60",
    "rel_mkt_5",
    "rel_mkt_20",
    "rel_mkt_60",
    "rel_theme_5",
    "rel_theme_20",
    "rel_theme_60",
    "vol_5",
    "vol_20",
    "vol_60",
    "vol_ratio_5_60",
    "close_over_max_20",
    "close_over_min_20",
    "close_over_max_60",
    "close_over_min_60",
    "close_over_mean_20",
    "close_over_mean_60",
    "log_dollar_volume",
    "volume_ratio_20",
    "volume_ratio_60",
    "corr_mkt_20",
    "corr_mkt_60",
    "beta_60",
    "range_mean_5",
    "range_mean_20",
    "gap_sum_5",
    "close_position_mean_5",
)
ALPHA_COUNT = len(ALPHA_NAMES)


# Rolling mean over `length` sessions, NaN until complete.
def _rolling_mean(values: np.ndarray, length: int) -> np.ndarray:
    return trailing_sum(values, length) / length


# Rolling standard deviation over `length` sessions (population), NaN until
# complete.
def _rolling_std(values: np.ndarray, length: int) -> np.ndarray:
    mean = _rolling_mean(values, length)
    mean_sq = _rolling_mean(values * values, length)
    variance = np.maximum(mean_sq - mean * mean, 0.0)
    return np.sqrt(variance)


# Rolling max or min over `length` sessions, NaN wherever any session in
# the window is missing.
def _rolling_extreme(values: np.ndarray, length: int, largest: bool) -> np.ndarray:
    rows, cols = values.shape
    out = np.full_like(values, np.nan)
    reducer = np.max if largest else np.min
    for t in range(length - 1, rows):
        block = values[t - length + 1 : t + 1]
        complete = np.isfinite(block).all(axis=0)
        reduced = reducer(np.where(np.isfinite(block), block, 0.0), axis=0)
        out[t] = np.where(complete, reduced, np.nan)
    return out


# Rolling correlation between each column and a single reference series.
def _rolling_corr(values: np.ndarray, reference: np.ndarray, length: int) -> np.ndarray:
    ref = np.broadcast_to(reference[:, None], values.shape)
    mean_x = _rolling_mean(values, length)
    mean_y = _rolling_mean(ref, length)
    cov = _rolling_mean(values * ref, length) - mean_x * mean_y
    std_x = _rolling_std(values, length)
    std_y = _rolling_std(ref, length)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = cov / (std_x * std_y)
    return np.where(np.isfinite(corr), corr, np.nan)


# Rolling beta of each column to the reference series.
def _rolling_beta(values: np.ndarray, reference: np.ndarray, length: int) -> np.ndarray:
    ref = np.broadcast_to(reference[:, None], values.shape)
    mean_x = _rolling_mean(values, length)
    mean_y = _rolling_mean(ref, length)
    cov = _rolling_mean(values * ref, length) - mean_x * mean_y
    var_y = _rolling_std(ref, length) ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        beta = cov / var_y
    return np.where(np.isfinite(beta), beta, np.nan)


# Build the (T, N, ALPHA_COUNT) feature array for a panel.
def alpha_features(panel: Panel) -> np.ndarray:
    """Return causal multi-scale features per (session, name)."""
    returns = panel.log_returns()
    market = panel.benchmark_returns()
    theme = panel.theme_return_matrix()
    with np.errstate(divide="ignore", invalid="ignore"):
        log_close = np.log(panel.adj_close)
        spread = np.log(panel.high / panel.low)
        previous_close = np.vstack(
            [np.full((1, len(panel.tickers)), np.nan), panel.close[:-1]]
        )
        gap = np.log(panel.open / previous_close)
        width = panel.high - panel.low
        position = np.where(width > 0, (panel.close - panel.low) / width, 0.5)
        dollar = np.log1p(np.maximum(panel.volume, 0.0) * panel.close)
    log_close = np.where(np.isfinite(log_close), log_close, np.nan)
    spread = np.where(np.isfinite(spread), spread, np.nan)
    gap = np.where(np.isfinite(gap), gap, np.nan)
    dollar = np.where(np.isfinite(dollar), dollar, np.nan)

    market_col = market[:, None]
    columns: list[np.ndarray] = []
    columns += [returns]
    columns += [trailing_sum(returns, n) for n in (5, 10, 20, 60)]
    columns += [
        trailing_sum(returns, n) - trailing_sum(market_col, n) for n in (5, 20, 60)
    ]
    columns += [trailing_sum(returns, n) - trailing_sum(theme, n) for n in (5, 20, 60)]
    columns += [_rolling_std(returns, n) for n in (5, 20, 60)]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = columns[-3] / columns[-1]
    columns += [np.where(np.isfinite(ratio), ratio, np.nan)]
    for n in (20, 60):
        columns += [log_close - _rolling_extreme(log_close, n, largest=True)]
        columns += [log_close - _rolling_extreme(log_close, n, largest=False)]
    columns += [log_close - _rolling_mean(log_close, n) for n in (20, 60)]
    columns += [dollar]
    columns += [dollar - _rolling_mean(dollar, n) for n in (20, 60)]
    columns += [_rolling_corr(returns, market, n) for n in (20, 60)]
    columns += [_rolling_beta(returns, market, 60)]
    columns += [_rolling_mean(spread, n) for n in (5, 20)]
    columns += [trailing_sum(gap, 5)]
    columns += [_rolling_mean(position, 5)]
    stacked = np.stack(columns, axis=2)
    assert stacked.shape[2] == ALPHA_COUNT, stacked.shape
    return np.where(np.isfinite(stacked), stacked, np.nan).astype(np.float32)
