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
from backend.market.sizing import Position, SizingConfig, size_today

# The book's knobs. Measured since 2021-06 on the 90 names: the top tenth
# at a 25% volatility target made 31% a year at Sharpe 1.55 and a -20%
# worst drawdown, against 16% at 1.25 and -16.5% for the top fifth at 15%,
# and 41% at 1.28 and -39% for equal weight. The concentration is what
# the grade is for; the volatility target is what keeps the drawdown
# at half the theme's.
BOOK_CONFIG = SizingConfig(
    top_fraction=0.1, short_fraction=0.0, target_volatility=0.25, name_cap=0.15
)


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


# Gross exposure of a sized book.
def gross(sized: list[Sized]) -> float:
    """Return the sum of absolute final weights."""
    return float(sum(abs(s.weight) for s in sized))
