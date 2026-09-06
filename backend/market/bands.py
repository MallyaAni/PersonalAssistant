"""Bollinger bands: where price sits between them, and how wide they are.

Two different readings come out of the same construction. Position says how
stretched the price is right now against its own recent range. Width says
what kind of market this is: a narrow band is a coiled one, a wide band an
extended one, and the width only means anything against the same name's own
history, since a name that always moves ten percent a week has a
permanently wide band.

Both are causal: session t reads sessions up to t and no further.
"""

import numpy as np

WINDOW = 20
SIGMA = 2.0
WIDTH_HISTORY = 250


# The middle band: a simple average of the last `window` closes.
def _middle(close: np.ndarray, window: int) -> np.ndarray:
    out = np.full(close.shape, np.nan)
    for t in range(window - 1, close.shape[0]):
        with np.errstate(all="ignore"):
            out[t] = np.nanmean(close[t - window + 1 : t + 1], axis=0)
    return out


# The standard deviation of the same window.
def _spread(close: np.ndarray, window: int) -> np.ndarray:
    out = np.full(close.shape, np.nan)
    for t in range(window - 1, close.shape[0]):
        with np.errstate(all="ignore"):
            out[t] = np.nanstd(close[t - window + 1 : t + 1], axis=0)
    return out


# Where the close sits between the bands: 0 at the lower band, 1 at the
# upper, and outside that range when price breaks through.
def position(
    close: np.ndarray, window: int = WINDOW, sigma: float = SIGMA
) -> np.ndarray:
    """Return (T, N) band position."""
    middle = _middle(close, window)
    spread = _spread(close, window)
    with np.errstate(all="ignore"):
        span = 2.0 * sigma * spread
        return np.where(span > 0, (close - (middle - sigma * spread)) / span, np.nan)


# The band's width as a fraction of its middle: a scale-free measure of how
# much this name has been moving lately.
def width(close: np.ndarray, window: int = WINDOW, sigma: float = SIGMA) -> np.ndarray:
    """Return (T, N) band width."""
    middle = _middle(close, window)
    spread = _spread(close, window)
    with np.errstate(all="ignore"):
        return np.where(middle > 0, 2.0 * sigma * spread / middle, np.nan)


# Where today's width sits within the same name's own trailing `history`
# sessions, in [0, 1]. Near zero is a squeeze; near one is an extended
# market that has already made its move. Reads only sessions before t, so a
# reading never knows how wide the band is about to become.
def width_rank(
    close: np.ndarray,
    window: int = WINDOW,
    sigma: float = SIGMA,
    history: int = WIDTH_HISTORY,
) -> np.ndarray:
    """Return (T, N) width percentile against the name's own past."""
    values = width(close, window, sigma)
    out = np.full(values.shape, np.nan)
    for t in range(history, values.shape[0]):
        past = values[t - history : t]
        with np.errstate(all="ignore"):
            known = np.isfinite(past).sum(axis=0)
            below = (past < values[t]).sum(axis=0)
        out[t] = np.where(
            np.isfinite(values[t]) & (known >= history // 2),
            below / np.maximum(known, 1),
            np.nan,
        )
    return out
