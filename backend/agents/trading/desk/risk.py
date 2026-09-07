"""The risk manager: grades and the regime become sizes.

It reuses the measured sizing engine (inverse volatility with a floor,
name and theme caps, a book-level volatility target on the book's own
trailing returns) and adds two multipliers on top: each name's grade
(A+ full, A three quarters, B half, C nothing) and the regime's exposure
(three quarters in a hype phase). Both are applied after the sizing engine
so the caps still hold.
"""

from dataclasses import dataclass, replace

import numpy as np

from backend.agents.trading.desk.grading import GRADES, SIZE_MULTIPLIER
from backend.agents.trading.desk.regime import RegimeState
from backend.market.panel import Panel
from backend.market.sizing import (
    Position,
    SizingConfig,
    apply_name_cap,
    size_today,
)

# The book's knobs. Measured since 2021-06 on the 90 names: the top tenth
# at a 25% volatility target made 31% a year at Sharpe 1.55 and a -20%
# worst drawdown, against 16% at 1.25 and -16.5% for the top fifth at 15%,
# and 41% at 1.28 and -39% for equal weight. The concentration is what
# the grade is for; the volatility target is what keeps the drawdown
# at half the theme's.
BOOK_CONFIG = SizingConfig(
    top_fraction=0.1, short_fraction=0.0, target_volatility=0.25, name_cap=0.15
)
# While money is tightening the engine's inverse-volatility weights are
# raised to this power, so the steady names take a larger share of the
# same book. Measured on the ninety-three names since 2021-06, with the
# exposure cut the regime analyst already applies: Sharpe 1.47 -> 1.65,
# worst drawdown -38.3% -> -34.6%, and more total return, so this is not
# a trade of return for safety.
TIGHTENING_POWER = 2.0


@dataclass(frozen=True)
class Sized:
    """One name's position with the grade that sized it."""

    position: Position
    grade: str
    multiplier: float
    exposure: float

    # The weight after grade and regime multipliers.
    @property
    def weight(self) -> float:
        """Return the final weight."""
        return self.position.weight * self.multiplier * self.exposure


# Size today's book: the sizing engine on the graded scores, then each name
# scaled by its grade and the regime's exposure.
def size(
    scores_today: np.ndarray,
    graded_today: np.ndarray,
    panel: Panel,
    regime: RegimeState,
    config: SizingConfig = BOOK_CONFIG,
    held: np.ndarray | None = None,
) -> list[Sized]:
    """Return the sized book, largest final weight first."""
    # A C-grade name is not a candidate at all, so it cannot take a slot.
    # The engine's top fraction counts the names it can see, so the
    # fraction is rescaled to keep the book the size it would be over the
    # whole universe (a tenth of 90 names, not a tenth of the graded ones).
    candidates = np.where(graded_today > 0, scores_today, np.nan)
    total = max(int(np.isfinite(scores_today).sum()) - 1, 1)
    graded = max(int(np.isfinite(candidates).sum()), 1)
    scaled = replace(
        config, top_fraction=min(1.0, config.top_fraction * total / graded)
    )
    positions = size_today(candidates, panel, scaled, held)
    if regime.tightening:
        positions = _steepen(positions, TIGHTENING_POWER, scaled.name_cap)
    out: list[Sized] = []
    for position in positions:
        column = panel.index(position.ticker)
        letter = GRADES[3 - int(graded_today[column])]
        out.append(
            Sized(
                position=position,
                grade=letter,
                multiplier=SIZE_MULTIPLIER[letter],
                exposure=regime.exposure,
            )
        )
    out.sort(key=lambda s: -abs(s.weight))
    return out


# The same names, reweighted so the steadier ones take more of the book.
# The engine already weights by the inverse of volatility; raising that
# to `power` and renormalising keeps the gross exposure unchanged.
#
# The cap is re-applied afterwards. Renormalising moves weight onto the
# calmest names, and `size_today` had already capped them, so without this
# the tilt could carry a position past `name_cap` - 18.75% against a 15%
# cap on the paper book, found by a review after the same defect had been
# fixed in the simulator alone. Both paths call `apply_name_cap` now, so
# the backtest and the book being traded obey the same limit.
def _steepen(
    positions: list[Position], power: float, cap: float | None = None
) -> list[Position]:
    gross_before = sum(abs(p.weight) for p in positions)
    if gross_before <= 0:
        return positions
    adjusted = []
    for p in positions:
        vol = max(p.volatility, 0.10)
        adjusted.append(abs(p.weight) * (0.10 / vol) ** (power - 1.0))
    total = sum(adjusted)
    if total <= 0:
        return positions
    scaled = np.array(adjusted, dtype=float) / total * gross_before
    if cap:
        scaled = apply_name_cap(scaled, cap, gross_before)
    out = []
    for p, weight in zip(positions, scaled, strict=True):
        note = p.note + "; steadier while money tightens"
        out.append(replace(p, weight=float(weight), note=note))
    out.sort(key=lambda p: -abs(p.weight))
    return out


# Gross exposure of a sized book.
def gross(sized: list[Sized]) -> float:
    """Return the sum of absolute final weights."""
    return float(sum(abs(s.weight) for s in sized))
