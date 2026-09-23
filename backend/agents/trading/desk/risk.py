"""The risk manager: grades and the regime become sizes.

It reuses the measured sizing engine (inverse volatility with a floor,
name and theme caps, a book-level volatility target on the book's own
trailing returns) and adds two multipliers on top: each name's grade
(A+ full, A three quarters, B half, C nothing) and the regime's exposure
(three quarters in a hype phase). Both are applied after the sizing engine
so the caps still hold.
"""

from dataclasses import dataclass, replace
from typing import Protocol

import numpy as np

from backend.agents.trading.desk.grading import GRADES, SIZE_MULTIPLIER
from backend.market.panel import Panel
from backend.market.sizing import (
    Position,
    SizingConfig,
    apply_limits,
    realised_volatility,
    size_today,
)

# The book's knobs. Measured since 2021-06 on the 90 names: the top tenth
# at a 25% volatility target made 31% a year at Sharpe 1.55 and a -20%
# worst drawdown, against 16% at 1.25 and -16.5% for the top fifth at 15%,
# and 41% at 1.28 and -39% for equal weight. The concentration is what
# the grade is for; the volatility target is what keeps the drawdown
# at half the theme's.
# The volatility target scales the whole book DOWN when its estimated
# volatility exceeds the target, so a target set too low holds cash in calm
# markets for no reason. At 0.25 that constraint bound often enough to cost
# return without buying safety: raising it to 0.30 earned +3.5 and +2.0 points
# of CAGR in the two windows at a better Sharpe, and the drawdown over the
# whole history barely moved (-34.89% to -34.67%).
#
# 0.40 earns more again and is NOT taken. In the 2021 window it looks nearly
# free because drawdown saturates near -46% whatever the exposure, but that
# window contains no crash; measured over the whole history with COVID in it,
# 0.40 with a flat grade multiplier falls to -43.03% against -34.89%. Eight
# points of drawdown is what leverage costs when a real fall arrives, and the
# modern window simply cannot see it.
BOOK_CONFIG = SizingConfig(
    top_fraction=0.1, short_fraction=0.0, target_volatility=0.30, name_cap=0.15
)
# While money is tightening the engine's inverse-volatility weights are
# raised to this power, so the steady names take a larger share of the
# same book. Measured on the ninety-three names since 2021-06, with the
# exposure cut the regime analyst already applies: Sharpe 1.47 -> 1.65,
# worst drawdown -38.3% -> -34.6%, and more total return, so this is not
# a trade of return for safety.
TIGHTENING_POWER = 2.0


class RiskBudget(Protocol):
    """Only the exposure and rate posture are required to size a book."""

    exposure: float
    tightening: bool


@dataclass(frozen=True)
class Sized:
    """One name's position with the grade that sized it."""

    position: Position
    grade: str
    multiplier: float
    exposure: float
    # The weight the book actually targets. It used to be derived as
    # position x multiplier x exposure, which was only true while nothing
    # happened after those multipliers. The tightening tilt does, and the
    # cap after it does, so the number is carried rather than recomputed.
    final: float | None = None

    # The weight after grade and regime multipliers, the tilt and the cap.
    @property
    def weight(self) -> float:
        """Return the final weight."""
        if self.final is not None:
            return self.final
        return self.position.weight * self.multiplier * self.exposure


# Learning this allocation is worth nothing, and neither is improving the
# volatility it divides by. The value is in which names are chosen, not in
# how they are weighted.
#
# Three measurements say the same thing from different directions.
#
# A reinforcement-learning agent was given the desk's own state - each
# name's four analyst convictions and its realised volatility, plus the
# regime's participation, exposure and tightening flag - and asked to
# choose the weights directly, rewarded on the book's Sharpe over the next
# twenty sessions and capped at the gross this function would have carried,
# so it could not win by holding more. Walk-forward, ten folds, three
# seeds, two algorithms:
#
#   the desk's rule                +0.611
#   equal weight, same names       +0.605  (Newey-West t -0.46)
#   policy gradient (REINFORCE)    +0.579  (Newey-West t -0.72)
#   cross-entropy search           +0.585  (Newey-West t -0.79)
#
# Neither agent beat the rule, and both were slightly worse. The t is
# Newey-West over the twenty-session reward window, since consecutive
# sessions' rewards overlap; `market_allocation_rl` has the full table.
#
# Equal weight on the same names scored the same as this whole function -
# inverse volatility, caps, grade multipliers and all. And a volatility
# forecast 15.5% more accurate than the one used here changed the book's
# Sharpe from 1.85 to 1.82 (see `sizing.realised_volatility`).
#
# So the weighting is not where the risk-adjusted return is decided. That
# does not make this function pointless: the caps bound what a single name
# or theme can cost, which is a risk decision rather than a return one, and
# equal weight would fail that test in a concentrated book. It does mean
# effort spent making the weights cleverer is effort in the wrong place.
#
# The reinforcement-learning result is a bounded one and worth reading as
# such: two algorithms, one state representation, one reward shape. What it
# does not do is contradict the arithmetic that predicted it - roughly
# 1,300 sessions at a twenty-session horizon is about 65 independent
# periods, and no policy with thousands of parameters learns a market from
# 65 observations. Anything trained here is fitting one price path.


# Which names today's grades let the book hold at all: those whose grade
# multiplier is above zero. Read from `SIZE_MULTIPLIER` rather than a
# threshold, so the candidate set and the sizing can never disagree again.
def _holdable(graded_today: np.ndarray) -> np.ndarray:
    """Return a boolean mask of the names whose grade earns a position."""
    ordinal = np.asarray(graded_today, dtype=float)
    known = np.isfinite(ordinal)
    clipped = np.clip(np.where(known, ordinal, 0), 0, len(GRADES) - 1).astype(int)
    multiplier = np.array([SIZE_MULTIPLIER[GRADES[3 - k]] for k in range(len(GRADES))])
    return known & (multiplier[clipped] > 0)


# The desk's target weight for every name, in one place.
#
# The paper book and the backtest used to compute this separately and in a
# different order: the paper path tilted and capped the engine's weights
# and then applied the grade and exposure multipliers, while the simulator
# applied the multipliers first and tilted and capped the result. Capping
# and scaling do not commute, so with the same inputs in a tightening
# regime the two disagreed on every name - 0.1125 against 0.1500 on the
# largest. A backtest that sizes differently from the book it is meant to
# describe is not evidence about that book, so there is one calculation
# now and both callers use it.
#
# The order is: the engine's weights, then the grade and the regime's
# exposure, then the tightening tilt, then the cap. The cap is last on
# purpose - it constrains what is actually held, which is what a position
# limit is for.
def desk_targets(
    scores_today: np.ndarray,
    graded_today: np.ndarray,
    panel: Panel,
    regime: RiskBudget,
    config: SizingConfig = BOOK_CONFIG,
    held: np.ndarray | None = None,
) -> tuple[list[Position], np.ndarray]:
    """Return (the engine's positions, the final target weight per column)."""
    # A name whose grade earns no position (SIZE_MULTIPLIER of zero: a C,
    # and a B since the ladder was flattened) is not a candidate at all, so
    # it cannot take a slot. This used to exclude only the C grade, and a
    # B name in the top decile then took a slot the multiplier zeroed: the
    # book held fewer names than the slice, at less than its
    # volatility-targeted gross. The engine's top fraction counts the names
    # it can see, so the fraction is rescaled to keep the book the size it
    # would be over the whole universe (a tenth of 90 names, not a tenth
    # of the holdable ones).
    candidates = np.where(_holdable(graded_today), scores_today, np.nan)
    total = max(int(np.isfinite(scores_today).sum()) - 1, 1)
    graded = max(int(np.isfinite(candidates).sum()), 1)
    scaled = replace(
        config, top_fraction=min(1.0, config.top_fraction * total / graded)
    )
    positions = size_today(candidates, panel, scaled, held)
    targets = np.zeros(len(panel.tickers))
    for position in positions:
        column = panel.index(position.ticker)
        letter = GRADES[3 - int(graded_today[column])]
        targets[column] = position.weight * SIZE_MULTIPLIER[letter] * regime.exposure
    if regime.tightening:
        targets = _steepen_weights(targets, panel, scaled, config.name_cap)
    return positions, targets


# Size today's book: the sizing engine on the graded scores, then each name
# scaled by its grade and the regime's exposure.
def size(
    scores_today: np.ndarray,
    graded_today: np.ndarray,
    panel: Panel,
    regime: RiskBudget,
    config: SizingConfig = BOOK_CONFIG,
    held: np.ndarray | None = None,
) -> list[Sized]:
    """Return the sized book, largest final weight first."""
    positions, targets = desk_targets(
        scores_today, graded_today, panel, regime, config, held
    )
    out: list[Sized] = []
    for position in positions:
        column = panel.index(position.ticker)
        letter = GRADES[3 - int(graded_today[column])]
        note = position.note
        if regime.tightening:
            note = note + "; steadier while money tightens"
        out.append(
            Sized(
                position=replace(position, note=note),
                grade=letter,
                multiplier=SIZE_MULTIPLIER[letter],
                exposure=regime.exposure,
                final=float(targets[column]),
            )
        )
    out.sort(key=lambda s: -abs(s.weight))
    return out


# The same names, reweighted so the steadier ones take more of the book.
# The engine already weights by the inverse of volatility; raising that to
# `TIGHTENING_POWER` and renormalising keeps the gross exposure unchanged.
#
# The cap is re-applied afterwards, because renormalising moves weight onto
# the calmest names and those were already at the cap. Without it the tilt
# carried a position to 0.3713 against a 0.15 cap.
def _steepen_weights(
    targets: np.ndarray, panel: Panel, config: SizingConfig, cap: float | None
) -> np.ndarray:
    # The tilt moves weight between names, so it can lift a theme over its
    # cap as easily as a name over its own. Both are re-checked below.
    gross = float(np.abs(targets).sum())
    if gross <= 0:
        return targets
    volatility = realised_volatility(panel, config.volatility_lookback)[-1]
    vol = np.where(
        np.isfinite(volatility) & (volatility > config.min_volatility),
        volatility,
        config.min_volatility,
    )
    adjusted = np.abs(targets) * (config.min_volatility / vol) ** (
        TIGHTENING_POWER - 1.0
    )
    total = float(adjusted.sum())
    if total <= 0:
        return targets
    out = apply_limits(
        adjusted / total * gross,
        panel.themes,
        panel.tickers,
        cap or 0.0,
        config.theme_cap,
        gross,
    )
    return np.sign(targets) * out


# Gross exposure of a sized book.
def gross(sized: list[Sized]) -> float:
    """Return the sum of absolute final weights."""
    return float(sum(abs(s.weight) for s in sized))
