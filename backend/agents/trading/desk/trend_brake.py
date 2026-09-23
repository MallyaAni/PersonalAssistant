"""The trend brake: a market-wide exposure ceiling read from QQQ's own trend.

A predeclared, causal state machine over the QQQ adjusted close, decided at
each close from that close and the ones before it:

  risk_off turns on    the close is below 0.97 x its trailing 200-session mean
  risk_off turns off   the close is above 1.02 x that mean
  otherwise            the previous state holds (the hysteresis band)
  first 200 sessions   risk_on, there being no mean yet

While risk_off the book is scaled by `simulate.run`'s `brake_scale` and the
released part waits in cash. This module only reads the state; the ledger,
the fills and the composition with the FOMC ceiling live in `simulate`.
The thresholds are fixed by the specification and are not tuned here.
"""

import numpy as np

LOOKBACK = 200
ENTER_BELOW = 0.97
EXIT_ABOVE = 1.02
QQQ = "QQQ"


# Pull the QQQ history out of the benchmark context and prove it sits on
# the panel's own calendar, one close per session, so a row of the state
# is a row of the panel and never a shifted one.
def aligned_qqq(panel_dates: np.ndarray, benchmark_prices: dict | None) -> np.ndarray:
    """Return the (T,) QQQ adjusted closes aligned to `panel_dates`."""
    if benchmark_prices is None:
        raise ValueError("trend_brake requires benchmark_prices with dates and QQQ")
    dates = benchmark_prices.get("dates")
    if dates is None:
        raise ValueError("trend_brake benchmark context must carry its own dates")
    dates = np.asarray(dates)
    panel_dates = np.asarray(panel_dates)
    if dates.ndim != 1 or dates.dtype.kind != "M":
        raise ValueError(
            "trend_brake benchmark dates must be one-dimensional datetime64"
        )
    if len(dates) != len(panel_dates) or not np.array_equal(
        dates.astype("datetime64[D]"), panel_dates.astype("datetime64[D]")
    ):
        raise ValueError("trend_brake benchmark dates must equal the panel calendar")
    qqq = benchmark_prices.get(QQQ)
    if qqq is None:
        raise ValueError("trend_brake requires a QQQ benchmark history")
    qqq = np.asarray(qqq, dtype=float)
    if qqq.ndim != 1 or qqq.shape[0] != len(panel_dates):
        raise ValueError("QQQ must be a one-dimensional history aligned to the panel")
    return qqq


# Walk the state machine over the closes. Each session's state is decided
# from rows <= t only, so appending future rows never changes an earlier
# value. A session whose close or trailing mean is not finite holds the
# previous state: missing evidence is not a signal either way.
def risk_off_path(
    qqq: np.ndarray,
    lookback: int = LOOKBACK,
    enter_below: float = ENTER_BELOW,
    exit_above: float = EXIT_ABOVE,
) -> np.ndarray:
    """Return a (T,) boolean array, True on every session the brake is risk_off."""
    closes = np.asarray(qqq, dtype=float)
    rows = closes.shape[0]
    out = np.zeros(rows, dtype=bool)
    state = False
    for t in range(rows):
        if t >= lookback - 1:
            window = closes[t - lookback + 1 : t + 1]
            mean = float(window.mean()) if np.all(np.isfinite(window)) else np.nan
            close = closes[t]
            if np.isfinite(close) and np.isfinite(mean) and mean > 0:
                if close < enter_below * mean:
                    state = True
                elif close > exit_above * mean:
                    state = False
        out[t] = state
    return out
