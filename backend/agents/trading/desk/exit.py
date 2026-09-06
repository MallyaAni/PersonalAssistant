"""The exit analyst: when a position the desk owns is done.

Entry and exit are different questions and were not treated that way here.
Entry asks which of ninety-three names is best today, and a cross-sectional
rank answers it. Exit asks whether this one position has finished, which no
ranking can answer. The desk's original exit — sell after the grade has sat
below B for ten sessions — was never measured against anything, and when it
finally was, it sold at the 53rd percentile of the surrounding price range,
which is no better than chance, and it performed no better than holding for
a fixed period.

Measured on 352 real entries the desk's own rules produced, holding every
entry fixed and varying only the exit, over 2021-06 to 2026-09 and again on
2024 onward alone:

| exit                                   | median | wins | where it sold |
| the old rule (grade below B for 10)    |  +7.9% |  64% | 0.53          |
| a fixed 120-session hold               | +11.6% |  66% | 0.45          |
| a bearish candle at the upper band     | +14.1% |  72% | 0.62          |
| a wide band with price near its top    | +12.4% |  74% | 0.67          |
| either of those, after a month's grace | +12.2% |  73% | 0.66          |

"Where it sold" is the percentile of the sale price within the ten sessions
either side, so higher is a better sale. Two things in that table are worth
keeping in mind. Adding the grade rule back to the band rules made them
worse, from +14.1% to +9.4%: the old exit was cutting winners rather than
protecting anything, so it is gone rather than kept as a floor. And named
candlestick shapes, which measured nothing at all as a way of ranking names
to buy, are the best single ingredient here — because "the move is extended
and it has just turned" is an exit question, and it was only ever asked as
an entry one.
"""

from dataclasses import dataclass

import numpy as np

from backend.market import bands, technical
from backend.market.panel import Panel

NAME = "exit"
# A position is left alone for this many sessions after it is opened, so a
# name bought while already extended is not sold straight back out.
GRACE = 20
# "At the band" is not only a break of it: a close in the top few percent of
# the band is the same condition and fires more often.
NEAR_TOP = 0.95
# The wide-band rule needs both: a band in the top decile of its own year,
# and price in the upper fifth of that band.
WIDE = 0.90
UPPER_FIFTH = 0.80


@dataclass(frozen=True)
class ExitEvidence:
    """Per session and name, everything the exit analyst reads."""

    band_position: np.ndarray
    band_width_rank: np.ndarray
    bearish_candle: np.ndarray

    # Whether each name meets the exit condition on each session, ignoring
    # how long it has been held.
    def signalled(self) -> np.ndarray:
        """Return (T, N) True where the position looks finished."""
        return reversal_at_band(self) | extended_and_high(self)


# A named bearish reversal shape while price is at or through the upper
# band: the move is stretched and today went the other way.
def reversal_at_band(evidence: ExitEvidence) -> np.ndarray:
    """Return (T, N) True for a reversal at the top of the band."""
    with np.errstate(invalid="ignore"):
        return (evidence.band_position >= NEAR_TOP) & evidence.bearish_candle


# The band is wider than it has been almost all year and price is in the
# top of it: the move has already happened.
def extended_and_high(evidence: ExitEvidence) -> np.ndarray:
    """Return (T, N) True where the market is extended and price is high in it."""
    with np.errstate(invalid="ignore"):
        return (evidence.band_width_rank >= WIDE) & (
            evidence.band_position >= UPPER_FIFTH
        )


# Read the evidence off a panel.
def evidence(panel: Panel) -> ExitEvidence:
    """Return the ExitEvidence for the panel."""
    close = panel.adj_close
    features = technical.technical_features(panel)
    index = {name: i for i, name in enumerate(technical.TECHNICAL_NAMES)}
    bearish = (features[:, :, index["shooting_star"]] > 0) | (
        features[:, :, index["bearish_engulfing"]] > 0
    )
    return ExitEvidence(
        band_position=bands.position(close),
        band_width_rank=bands.width_rank(close),
        bearish_candle=np.where(np.isfinite(close), bearish, False).astype(bool),
    )


# Should a position opened on `entry_index` be closed at session `t`? The
# grace period is the only thing that depends on how long it has been held;
# the rest is a reading of the market now.
def should_exit(
    evidence: ExitEvidence,
    t: int,
    column: int,
    entry_index: int,
    grace: int = GRACE,
) -> bool:
    """Return True when the position is finished."""
    if t - entry_index < grace:
        return False
    return bool(evidence.signalled()[t, column])


# Why it left, for the record and the page.
def reason(evidence: ExitEvidence, t: int, column: int) -> str:
    """Return a short phrase naming which condition fired."""
    if bool(reversal_at_band(evidence)[t, column]):
        return "a bearish candle at the top of its Bollinger band"
    if bool(extended_and_high(evidence)[t, column]):
        return "the band is wide and price sits near the top of it"
    return "no exit condition"
