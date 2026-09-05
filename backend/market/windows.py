"""Window tensors a model learns structure from, without hand-coded indicators.

This is the answer to "wouldn't a neural network already learn the structure
report?": yes — so the model is fed raw normalized sequences, not a computed
trend slope or volatility number. Each window is a stack of daily channels
for one ticker ending at one session:

- **own log return** — the ticker's daily return from adjusted close,
- **log volume** — the ticker's daily traded volume on a log scale,
- **market-relative return** — the ticker's return minus the benchmark's on
  the same session, the seed of rotation and relative-strength learning.

Two properties are structural, not hoped for. A window ending at session t
contains only sessions up to and including t, so nothing future leaks in.
The future label is the ticker's own forward log return over a horizon, kept
separate from the inputs and marked invalid wherever the future is not fully
known, so a harness can never train on a label that overlaps its test period.

Channel values are emitted raw (returns are unitless; volume is log-scaled).
Z-scoring is a training-time step the harness fits on the training split
only — standardizing here on the full sample would leak held-out statistics.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from backend.market.yahoo import DailyBar

# Channel order in the emitted tensor. Add sector/theme breadth and news
# channels here as later slices build them.
OWN_RETURN = 0
LOG_VOLUME = 1
MARKET_RELATIVE = 2
CHANNELS = 3


@dataclass(frozen=True, slots=True)
class WindowSet:
    """Windows plus the metadata that tells a harness what each one is."""

    inputs: np.ndarray  # (n, window_size, CHANNELS) float32
    tickers: np.ndarray  # (n,) object
    end_dates: np.ndarray  # (n,) datetime64[D]
    future_returns: np.ndarray  # (n,) float32, NaN where not fully known
    valid: np.ndarray  # (n,) bool - label complete and usable for training


# Build every window over the shared session calendar of the given tickers
# and the benchmark.
#
# Returns a WindowSet. A window is emitted for session t of a ticker when the
# whole window is within the calendar and the ticker traded every session in
# it (a listed name should); windows over a gap are dropped rather than
# filled with an invented price.
def build_windows(
    bars_by_ticker: Mapping[str, Sequence[DailyBar]],
    benchmark_bars: Sequence[DailyBar],
    window_size: int = 20,
    horizon: int = 20,
) -> WindowSet:
    """Build no-look-ahead window tensors over the shared trading calendar."""
    if window_size < 2 or horizon < 1:
        raise ValueError("window_size >= 2 and horizon >= 1 are required")

    # The union calendar every series is aligned to. Missing sessions stay
    # missing (NaN) rather than being interpolated.
    calendar = sorted(
        {bar.session_date for bars in bars_by_ticker.values() for bar in bars}
        | {bar.session_date for bar in benchmark_bars}
    )
    index_of = {session: i for i, session in enumerate(calendar)}
    size = len(calendar)

    bench_adj = _aligned(benchmark_bars, calendar, "adjusted_close")
    bench_ret = _series_return(bench_adj)

    inputs: list[np.ndarray] = []
    tickers: list[str] = []
    end_dates: list[np.datetime64] = []
    future: list[float] = []
    valid: list[bool] = []

    for ticker, bars in bars_by_ticker.items():
        adj = _aligned(bars, calendar, "adjusted_close")
        volume = _aligned(bars, calendar, "volume")
        own_ret = _series_return(adj)
        log_volume = _log_volume(volume)
        market_relative = own_ret - bench_ret
        forward = _forward_return(adj, horizon)

        for t in range(window_size, size):
            start = t - window_size + 1
            window_own = own_ret[start : t + 1]
            # The ticker must have traded every session in the window; a gap
            # means the window is not a real consecutive run.
            if np.isnan(window_own).any():
                continue
            window = np.stack(
                [
                    window_own,
                    log_volume[start : t + 1],
                    market_relative[start : t + 1],
                ],
                axis=1,
            )
            label = forward[t]
            inputs.append(window.astype(np.float32))
            tickers.append(ticker)
            end_dates.append(np.datetime64(calendar[t], "D"))
            future.append(float(label) if not np.isnan(label) else float("nan"))
            valid.append(bool(not np.isnan(label)))

    if not inputs:
        empty = np.empty((0, window_size, CHANNELS), dtype=np.float32)
        return WindowSet(
            inputs=empty,
            tickers=np.empty((0,), dtype=object),
            end_dates=np.empty((0,), dtype="datetime64[D]"),
            future_returns=np.empty((0,), dtype=np.float32),
            valid=np.empty((0,), dtype=bool),
        )

    return WindowSet(
        inputs=np.asarray(inputs, dtype=np.float32),
        tickers=np.asarray(tickers, dtype=object),
        end_dates=np.asarray(end_dates, dtype="datetime64[D]"),
        future_returns=np.asarray(future, dtype=np.float32),
        valid=np.asarray(valid, dtype=bool),
    )


# One ticker's series over the shared calendar, NaN where it did not trade.
def _aligned(
    bars: Sequence[DailyBar], calendar: Sequence[date], field: str
) -> np.ndarray:
    values: dict[date, float | None] = {}
    for bar in bars:
        values[bar.session_date] = getattr(bar, field)
    return np.asarray(
        [
            (float(values[session]) if session in values and values[session] is not None else np.nan)
            for session in calendar
        ],
        dtype=np.float64,
    )


# Daily log return per calendar position; the first position has no prior.
def _series_return(adjusted_close: np.ndarray) -> np.ndarray:
    previous = adjusted_close[:-1]
    current = adjusted_close[1:]
    returns = np.full(len(adjusted_close), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        returns[1:] = np.log(current / previous)
    returns[~np.isfinite(returns)] = np.nan
    return returns


# Log-scaled volume per calendar position, NaN where the ticker did not trade.
def _log_volume(volume: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.log1p(np.nan_to_num(volume, nan=0.0))
    result[~np.isfinite(volume)] = np.nan
    return result


# The K-session forward log return from each position, NaN where the future
# is not fully known. Uses only the ticker's own adjusted close.
def _forward_return(adjusted_close: np.ndarray, horizon: int) -> np.ndarray:
    forward = np.full(len(adjusted_close), np.nan)
    current = adjusted_close[:-horizon]
    later = adjusted_close[horizon:]
    with np.errstate(divide="ignore", invalid="ignore"):
        computed = np.log(later / current)
    computed[~np.isfinite(computed)] = np.nan
    forward[:-horizon] = computed
    return forward
