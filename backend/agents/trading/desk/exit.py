"""The exit analyst: measured, and not currently trading.

Entry and exit are different questions. Entry asks which of ninety-three
names is best today, and a cross-sectional rank answers it. Exit asks
whether this one position has finished, which no ranking can answer. This
module was built to ask the second question properly, and the rules in it
are kept because the reasoning behind them is sound and the measurement
that retired them is worth not repeating. **Nothing here trades.** The
paper book passes no `finished` map (see `desk/paper.py`).

Why it was retired
------------------
The rules below were chosen on a per-trade study: hold each of 352 real
entries fixed, vary only the exit, and compare. On that test the band
rules looked clearly best, selling at the 62nd-67th percentile of the
surrounding ten sessions against the 53rd for the old grade rule, with a
median trade of +14.1% against +7.9%.

That study asked the wrong question. It compared the band exit against
holding for up to 250 sessions. The book does not hold for 250 sessions;
it rebalances every 20, and the rebalance is already an exit. Run inside
the book's own rules (`desk/simulate.py`), from 2021-06:

| the book                    | a year | vol   | Sharpe | worst | total   |
| no exit overlay             | +31.6% | 17.5% |   1.81 | -18.3%| +384.4% |
| the band rules, to cash     | +28.6% | 16.2% |   1.77 | -17.5%| +318.7% |
| the band rules, redeployed  | +30.3% | 17.5% |   1.73 | -18.7%| +352.1% |

The overlay costs 3.0% a year (t -1.99) and lowers Sharpe in every one of
the six years. It helps only in 2022, the one falling year.

The reason is direct. Over 86,209 sessions on which the book held a name
graded B or better, that name beat the benchmark by 1.95% over the next 20
sessions. Conditioning on an exit trigger raises that number rather than
lowering it:

| trigger                                    | fires | next 20 vs benchmark |
| holding, no trigger (the baseline)         | 86209 | +1.95%   (t +42.7)   |
| a wide band with price near its top        |  3977 | +3.10%   (t +14.0)   |
| a bearish candle at the upper band         |   616 | +2.26%   (t  +4.1)   |
| price closes below its 50-day average      |  2874 | +1.39%   (t  +6.5)   |
| the 21-day average turns down              |  2575 | +1.99%   (t  +7.8)   |
| the weekly average turns down              |  1519 | +1.90%   (t  +5.3)   |
| the desk's rank falls below the middle     |  2097 | +1.24%   (t  +4.0)   |
| the grade falls out of A or better         |  1165 | +1.49%   (t  +4.3)   |

Twenty-one triggers were screened, from price crossing every average to
the desk's own grade and rank falling, and not one is followed by a fall.
The two the desk was using are the two worst of the set: "the band is wide
and price sits near its top" is one of the strongest *buy* signals here.
On these ninety-three names over this period the pattern is consistent —
a technical sell trigger fires into a pause of about a week, after which
the name resumes and beats the market.

What this does not say
----------------------
It does not say exits are unimportant. It says the rebalance is the exit
that works: 203 of 287 closes in the simulation are a name being replaced
by a better-ranked one, which is a funding decision, not a protection
decision. The triggers that came closest to earning their place are the
ones where the desk changes its mind about the name, not the ones where
the chart looks tired, and even those only match doing nothing.

It is also one period, and a period in which these names rose a great
deal. The 2022 column is the warning: in the only falling year the overlay
helped on both return and Sharpe. The regime analyst already cuts gross
exposure in that state, which is the same protection bought once rather
than twice, so gating exits on the regime was not added — that would be
fitting a rule to a single year.
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
