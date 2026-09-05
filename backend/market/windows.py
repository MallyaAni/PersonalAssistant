"""Window tensors a sequence model learns structure from.

Each window is a stack of daily channels for one ticker ending at one
session, read from the Panel so it is aligned with every baseline:

    0 own log return           what the name did
    1 gap                      log(open / previous close): overnight repricing
    2 range                    log(high / low): the day's spread
    3 close position           where the close sat in the day's range, 0..1
    4 log dollar volume        log1p(volume x close): participation
    5 return vs market         own return minus the market benchmark's
    6 return vs theme          own return minus its theme basket's
    7 theme vs market          the theme basket's return minus the market's

The first five are what "structure" is made of — bases, breakouts, gaps
that hold or fail, ranges that contract before a move — and the last three
are what rotation is made of. None is a hand-coded signal; a network reads
the raw shapes.

Two properties are structural. A window ending at session t contains only
sessions up to and including t. Labels are separate: the own, market and
theme forward log returns over the horizon, the residual (own minus
market), the date the label's horizon ends, and a validity flag that is
False wherever the future is not fully known. `label_end_dates` is what a
harness purges on: no training window may have a label ending after a test
window starts.

Channel values are emitted raw. Z-scoring is a training-time step fit on
the training split only; standardising here would leak held-out statistics.
"""

from dataclasses import dataclass

import numpy as np

from backend.market.panel import Panel

OWN_RETURN = 0
GAP = 1
RANGE = 2
CLOSE_POSITION = 3
LOG_DOLLAR_VOLUME = 4
VS_MARKET = 5
VS_THEME = 6
THEME_VS_MARKET = 7
CHANNELS = 8
CHANNEL_NAMES = (
    "own_return",
    "gap",
    "range",
    "close_position",
    "log_dollar_volume",
    "vs_market",
    "vs_theme",
    "theme_vs_market",
)


@dataclass(frozen=True, slots=True)
class WindowSet:
    """Windows plus the metadata that tells a harness what each one is."""

    inputs: np.ndarray  # (n, window_size, CHANNELS) float32
    tickers: np.ndarray  # (n,) object
    end_dates: np.ndarray  # (n,) datetime64[D]
    label_end_dates: np.ndarray  # (n,) datetime64[D]; NaT where unknown
    own_future: np.ndarray  # (n,) float32 own forward log return
    market_future: np.ndarray  # (n,) float32
    theme_future: np.ndarray  # (n,) float32
    residual_future: np.ndarray  # (n,) float32 own minus market
    valid: np.ndarray  # (n,) bool: every label fully known

    @property
    def size(self) -> int:
        return int(self.inputs.shape[0])


# The eight channel matrices (T, N) for the whole panel.
def channel_matrices(panel: Panel) -> np.ndarray:
    """Return a (T, N, CHANNELS) array of raw channel values, NaN where unknown."""
    own = panel.log_returns()
    bench = panel.benchmark_returns()[:, None]
    theme = panel.theme_return_matrix()
    previous_close = np.vstack(
        [np.full((1, len(panel.tickers)), np.nan), panel.close[:-1]]
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        gap = np.log(panel.open / previous_close)
        spread = np.log(panel.high / panel.low)
        width = panel.high - panel.low
        position = np.where(width > 0, (panel.close - panel.low) / width, 0.5)
        dollar = np.log1p(np.maximum(panel.volume, 0.0) * panel.close)
    stack = np.stack(
        [
            own,
            gap,
            spread,
            position,
            dollar,
            own - bench,
            own - theme,
            np.broadcast_to(theme - bench, own.shape),
        ],
        axis=2,
    )
    return np.where(np.isfinite(stack), stack, np.nan)


# Build every window of `window_size` sessions per ticker whose channels are
# all known, with labels over `horizon` sessions.
def build_windows(panel: Panel, window_size: int = 20, horizon: int = 10) -> WindowSet:
    """Build no-look-ahead window tensors and forward-return labels from a Panel."""
    if window_size < 2 or horizon < 1:
        raise ValueError("window_size >= 2 and horizon >= 1 are required")
    channels = channel_matrices(panel)
    own_fwd = panel.forward_log_returns(horizon)
    bench_column = panel.index(panel.benchmark)
    market_fwd = own_fwd[:, bench_column][:, None]
    theme_fwd = _theme_forward(panel, horizon)
    dates = panel.dates
    size = len(dates)

    inputs: list[np.ndarray] = []
    tickers: list[str] = []
    end_dates: list[np.datetime64] = []
    label_ends: list[np.datetime64] = []
    own_l: list[float] = []
    market_l: list[float] = []
    theme_l: list[float] = []
    valid: list[bool] = []

    for column, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark:
            continue
        series = channels[:, column, :]
        known = np.isfinite(series).all(axis=1)
        for t in range(window_size - 1, size):
            start = t - window_size + 1
            if not known[start : t + 1].all():
                continue
            inputs.append(series[start : t + 1].astype(np.float32))
            tickers.append(ticker)
            end_dates.append(dates[t])
            label_end = (
                dates[t + horizon] if t + horizon < size else np.datetime64("NaT", "D")
            )
            label_ends.append(label_end)
            o, m, th = own_fwd[t, column], market_fwd[t, 0], theme_fwd[t, column]
            own_l.append(float(o))
            market_l.append(float(m))
            theme_l.append(float(th))
            valid.append(bool(np.isfinite(o) and np.isfinite(m) and np.isfinite(th)))

    if not inputs:
        return WindowSet(
            inputs=np.empty((0, window_size, CHANNELS), dtype=np.float32),
            tickers=np.empty((0,), dtype=object),
            end_dates=np.empty((0,), dtype="datetime64[D]"),
            label_end_dates=np.empty((0,), dtype="datetime64[D]"),
            own_future=np.empty((0,), dtype=np.float32),
            market_future=np.empty((0,), dtype=np.float32),
            theme_future=np.empty((0,), dtype=np.float32),
            residual_future=np.empty((0,), dtype=np.float32),
            valid=np.empty((0,), dtype=bool),
        )
    own_arr = np.asarray(own_l, dtype=np.float32)
    market_arr = np.asarray(market_l, dtype=np.float32)
    return WindowSet(
        inputs=np.asarray(inputs, dtype=np.float32),
        tickers=np.asarray(tickers, dtype=object),
        end_dates=np.asarray(end_dates, dtype="datetime64[D]"),
        label_end_dates=np.asarray(label_ends, dtype="datetime64[D]"),
        own_future=own_arr,
        market_future=market_arr,
        theme_future=np.asarray(theme_l, dtype=np.float32),
        residual_future=own_arr - market_arr,
        valid=np.asarray(valid, dtype=bool),
    )


# The forward log return of each ticker's primary theme basket over the
# horizon: the sum of the theme's daily returns over sessions t+1..t+h.
def _theme_forward(panel: Panel, horizon: int) -> np.ndarray:
    theme_daily = panel.theme_return_matrix()
    filled = np.where(np.isfinite(theme_daily), theme_daily, np.nan)
    cumulative = np.nancumsum(filled, axis=0)
    counts = np.cumsum(np.isfinite(filled), axis=0)
    forward = np.full_like(theme_daily, np.nan)
    if horizon < len(panel.dates):
        total = cumulative[horizon:] - cumulative[:-horizon]
        complete = (counts[horizon:] - counts[:-horizon]) == horizon
        forward[:-horizon] = np.where(complete, total, np.nan)
    return forward
