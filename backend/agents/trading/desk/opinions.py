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
# A stance answers a yes-or-no question and throws away how far past
# the line a name sits. `conviction` keeps that: it runs smoothly from
# -1 at the worst rank to +1 at the best, bent by SHARPNESS so the
# middle of the cross-section counts for less than the edges. Measured
# on the ninety-three names, ranking by the summed conviction instead
# of by the grade lifts rank IC from 0.038 to 0.047 at twenty sessions
# and 0.060 to 0.076 at sixty.
#
# That was the whole of the gain a network found, and re-running the
# network against these analysts confirms it. A net trained only to
# imitate the desk's own rule used to beat the rule it copied, which is
# what pointed at the hard edges in the first place. Against the current
# analysts it no longer does - 0.0537 (t 3.31) against the rule's 0.0530
# at twenty sessions, and a lower net Sharpe, 1.00 against 1.03. Trained
# on the real forward rank instead of on the rule, it finds nothing at
# all: 0.0052 (t 0.42) at twenty sessions and 0.0137 (t 0.66) at sixty,
# both at a negative Sharpe. Smoothing was the entire edge, it is in the
# rule now, and there is no case left for a network here.
SHARPNESS = 2.0


@dataclass(frozen=True)
class Opinion:
    """One analyst's view of the whole panel over time."""

    analyst: str
    # (T, N) score; NaN where the analyst has no view of the name that day.
    scores: np.ndarray
    # {feature name: (T, N) array} the analyst would cite for a name.
    evidence: dict[str, np.ndarray] = field(default_factory=dict)
    # Metadata interpreted by the analyst and serialized by the record writer: the
    # data source/version its evidence came from, and per-feature fiscal
    # period ends, so a record can say what a corrected figure actually
    # refers to. Deliberately optional: most analysts carry nothing here.
    meta: dict[str, object] = field(default_factory=dict)
    # Optional (T, N) Boolean mask: discard a held stance and restart its
    # confirmation when that analyst's input validity changes. None keeps
    # legacy persistence, including its handling of temporarily missing scores.
    stance_resets: np.ndarray | None = None

    # Ranks in [0, 1] across the names with a score on each session.
    def ranks(self) -> np.ndarray:
        """Return (T, N) percentile ranks of the scores per session."""
        return percentile_rank(self.scores)

    # Persist rank stances per name, honoring explicit input-validity resets.
    def stances(
        self, fraction: float = STANCE_FRACTION, persistence: int = PERSISTENCE
    ) -> np.ndarray:
        """Return (T, N) stances in {-1, 0, 1}, persisted."""
        return persist(
            stances_from_ranks(self.ranks(), fraction),
            persistence,
            resets=self.stance_resets,
        )

    # How strongly this analyst likes each name, on a continuous scale
    # rather than in three buckets. NaN where it has no view.
    def conviction(self, sharpness: float = SHARPNESS) -> np.ndarray:
        """Return (T, N) conviction in [-1, 1]."""
        return conviction_from_ranks(self.ranks(), sharpness)

    # The evidence for one name on one session, as plain floats.
    def cite(self, t: int, column: int) -> dict[str, float]:
        """Return {feature: value} for the name at session t."""
        return {
            name: float(values[t, column])
            for name, values in self.evidence.items()
            if np.isfinite(values[t, column])
        }


# Confirm repeated raw stances, optionally clearing held votes and runs per ticker.
def persist(
    raw: np.ndarray, sessions: int, *, resets: np.ndarray | None = None
) -> np.ndarray:
    """Return (T, N) persisted stances, with optional explicit validity resets.

    A reset requires a plain Boolean ndarray matching the raw panel exactly;
    malformed masks are rejected without coercion, even for empty/immediate
    paths. It clears the held stance to neutral and counts the current raw
    stance as confirmation one. With three required confirmations, reset day
    and the next matching day remain neutral; the third matching day confirms.
    Repeated resets cannot build a run. Callers must reset every unscored row.

    Without resets, the first raw row is held immediately as before. An
    explicit first-row reset requires confirmation instead. With sessions <= 1,
    the current raw stance already satisfies confirmation, even on reset days.
    """
    if resets is not None and (
        type(resets) is not np.ndarray
        or resets.dtype != np.dtype(bool)
        or resets.ndim != 2
        or resets.shape != raw.shape
    ):
        raise ValueError("resets must be a Boolean ndarray matching raw's (T, N) shape")
    if sessions <= 1 or raw.shape[0] == 0:
        return raw
    held = raw.copy()
    run = np.ones(raw.shape[1], dtype=int)
    if resets is not None:
        held[0] = np.where(resets[0], NEUTRAL, held[0])
    for t in range(1, raw.shape[0]):
        run = np.where(raw[t] == raw[t - 1], run + 1, 1)
        previous = held[t - 1]
        if resets is not None:
            run = np.where(resets[t], 1, run)
            previous = np.where(resets[t], NEUTRAL, previous)
        held[t] = np.where(run >= sessions, raw[t], previous)
    return held


# A rank in [0, 1] mapped smoothly onto [-1, 1]. A sharpness of 1 is a
# straight line; larger values push the middle toward zero, so the
# names an analyst feels strongly about carry more of the weight.
def conviction_from_ranks(ranks: np.ndarray, sharpness: float) -> np.ndarray:
    """Return (T, N) conviction in [-1, 1], NaN where the rank is."""
    centred = np.clip((ranks - 0.5) * 2.0, -1.0, 1.0)
    with np.errstate(all="ignore"):
        return np.sign(centred) * np.abs(centred) ** (1.0 / sharpness)


# Top fraction bullish, bottom fraction bearish, NaN neutral.
def stances_from_ranks(ranks: np.ndarray, fraction: float) -> np.ndarray:
    """Return (T, N) stances from percentile ranks."""
    out = np.zeros(ranks.shape, dtype=int)
    known = np.isfinite(ranks)
    out[known & (ranks >= 1.0 - fraction)] = BULLISH
    out[known & (ranks <= fraction)] = BEARISH
    return out
