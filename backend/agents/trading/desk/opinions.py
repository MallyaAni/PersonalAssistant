"""What an analyst says about every name: a score, a stance, and why."""

from dataclasses import dataclass, field

import numpy as np

from backend.market.baselines import percentile_rank

BULLISH = 1
NEUTRAL = 0
BEARISH = -1

# A stance is bullish in the top `STANCE_FRACTION` of an analyst's scores on
# the session and bearish in the bottom fraction; the middle is neutral.
STANCE_FRACTION = 0.3
# A stance must hold this many consecutive sessions before it replaces
# the previous one, so a view that flickers on a threshold does not
# change a grade every day.
PERSISTENCE = 3


@dataclass(frozen=True)
class Opinion:
    """One analyst's view of the whole panel over time."""

    analyst: str
    # (T, N) score; NaN where the analyst has no view of the name that day.
    scores: np.ndarray
    # {feature name: (T, N) array} the analyst would cite for a name.
    evidence: dict[str, np.ndarray] = field(default_factory=dict)

    # Ranks in [0, 1] across the names with a score on each session.
    def ranks(self) -> np.ndarray:
        """Return (T, N) percentile ranks of the scores per session."""
        return percentile_rank(self.scores)

    # Bullish, neutral or bearish per name and session; neutral where the
    # analyst has no score.
    def stances(
        self, fraction: float = STANCE_FRACTION, persistence: int = PERSISTENCE
    ) -> np.ndarray:
        """Return (T, N) stances in {-1, 0, 1}, persisted."""
        return persist(stances_from_ranks(self.ranks(), fraction), persistence)

    # The evidence for one name on one session, as plain floats.
    def cite(self, t: int, column: int) -> dict[str, float]:
        """Return {feature: value} for the name at session t."""
        return {
            name: float(values[t, column])
            for name, values in self.evidence.items()
            if np.isfinite(values[t, column])
        }


# A raw stance becomes the held stance only once it has repeated for
# `sessions` consecutive sessions; until then the previous stance holds.
def persist(raw: np.ndarray, sessions: int) -> np.ndarray:
    """Return (T, N) persisted stances."""
    if sessions <= 1 or raw.shape[0] == 0:
        return raw
    held = raw.copy()
    run = np.ones(raw.shape[1], dtype=int)
    for t in range(1, raw.shape[0]):
        run = np.where(raw[t] == raw[t - 1], run + 1, 1)
        held[t] = np.where(run >= sessions, raw[t], held[t - 1])
    return held


# Top fraction bullish, bottom fraction bearish, NaN neutral.
def stances_from_ranks(ranks: np.ndarray, fraction: float) -> np.ndarray:
    """Return (T, N) stances from percentile ranks."""
    out = np.zeros(ranks.shape, dtype=int)
    known = np.isfinite(ranks)
    out[known & (ranks >= 1.0 - fraction)] = BULLISH
    out[known & (ranks <= fraction)] = BEARISH
    return out
