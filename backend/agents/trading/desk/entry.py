"""The entry analyst: when to buy a name the desk already wants.

The grade says what to hold. This says when to start. Measured on the 90
book names among names already bullish on fundamentals and release tone,
beta-adjusted:

* Dip entries pay over the next week: more than 8% below the 21-day EMA
  +1.2% in 5 sessions (t 3.5, hit 0.58); below the lower 20-day Bollinger
  band +0.9% (t 2.6); below the band while the AI basket is falling +2.1%
  (t 4.3, hit 0.62). By 20 sessions the dip edge is gone.
* Strength pays over the next month: the top of the 60-session range with
  both trends up +1.3% in 20 sessions (t 3.7); more than 8% above the
  21-day EMA +2.0% (t 2.6). So a breakout is the other entry.

Two triggers, then: a dip (stretched below the short EMAs or the band) and
a breakout (strength in an agreed trend). Either is an entry; neither on
its own is a reason to hold, which stays the grade's job.
"""

from dataclasses import dataclass

import numpy as np

from backend.market import levels, technical
from backend.market.panel import Panel

DIP_BELOW_EMA = -0.08
BAND_Z = -1.0
BREAKOUT_RANGE = 0.8
DIP = "dip"
BREAKOUT = "breakout"


@dataclass(frozen=True)
class Entries:
    """Per-session entry triggers for every name."""

    dip: np.ndarray  # (T, N) bool
    breakout: np.ndarray  # (T, N) bool
    bollinger_z: np.ndarray  # (T, N) position in the 20-day band, -1..+1
    stretch_21: np.ndarray  # (T, N) close against the 21-day EMA

    # Both triggers as one boolean.
    def any(self) -> np.ndarray:
        """Return (T, N) True where either trigger fires."""
        return self.dip | self.breakout

    # Which trigger fired for one name on one session, or None.
    def kind(self, t: int, column: int) -> str | None:
        """Return "dip", "breakout" or None."""
        if self.dip[t, column]:
            return DIP
        if self.breakout[t, column]:
            return BREAKOUT
        return None


# Position inside the 20-day, two-sigma Bollinger band: -1 at the lower
# band, +1 at the upper.
def bollinger_z(close: np.ndarray, window: int = 20) -> np.ndarray:
    """Return (T, N) band position."""
    mean = technical.sma(close, window)
    std = np.full_like(close, np.nan)
    for t in range(window - 1, close.shape[0]):
        with np.errstate(all="ignore"):
            std[t] = np.nanstd(close[t - window + 1 : t + 1], axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (close - mean) / (2 * std)


# Compute the triggers for the panel.
def entries(panel: Panel, location: np.ndarray | None = None) -> Entries:
    """Return the Entries for every session and name."""
    close = panel.adj_close
    loc = location if location is not None else levels.level_features(panel)
    lidx = {n: i for i, n in enumerate(levels.LEVEL_NAMES)}
    z = bollinger_z(close)
    e21 = technical.ema(close, 21)
    with np.errstate(invalid="ignore", divide="ignore"):
        stretch = (close - e21) / e21
        dip = (stretch <= DIP_BELOW_EMA) | (z <= BAND_Z)
        breakout = (
            (loc[:, :, lidx["range_position_60"]] >= BREAKOUT_RANGE)
            & (loc[:, :, lidx["weekly_trend"]] > 0)
            & (loc[:, :, lidx["daily_trend"]] > 0)
        )
    dip = np.where(np.isfinite(stretch) & np.isfinite(z), dip, False)
    breakout = np.where(np.isfinite(loc[:, :, lidx["weekly_trend"]]), breakout, False)
    return Entries(dip.astype(bool), breakout.astype(bool), z, stretch)
