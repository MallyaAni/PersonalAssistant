"""The trade grade: how many analysts agree, and how much that is worth.

The rule is fixed in advance and then measured, never fitted:

* A+: the company itself said the quarter was strong (sentiment bullish) and
  the other analysts agree on balance (votes >= 2).
* A: strong agreement without the release (fundamental and technical both
  bullish), or a bullish release with the others neutral on balance.
* B: one analyst bullish, nobody bearish.
* C: no bullish view, or the views cancel.
* Any bearish core analyst caps the grade at B: a bullish release and a
  strong tape over bearish filings was the losing trade in the history
  (IREN, January 2026), and measured, the cap raises the A grade's
  return from 17 to 53 bp per 20 sessions without touching A+.

The rotation analyst's stance counts half a vote: it is a view about the
side, not the name. `calibrate` in desk.py reports what each grade earned.
"""

from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk.opinions import BEARISH, BULLISH, Opinion

A_PLUS = "A+"
A = "A"
B = "B"
C = "C"
GRADES: tuple[str, ...] = (A_PLUS, A, B, C)
# Ordinal for ranking: higher is better.
ORDINAL: dict[str, int] = {A_PLUS: 3, A: 2, B: 1, C: 0}
# How much of a full position each grade earns.
SIZE_MULTIPLIER: dict[str, float] = {A_PLUS: 1.0, A: 0.75, B: 0.5, C: 0.0}
ROTATION_WEIGHT = 0.5


@dataclass(frozen=True)
class Graded:
    """Every name's grade on every session, with the votes behind it."""

    grades: np.ndarray  # (T, N) ordinal in {0, 1, 2, 3}
    votes: np.ndarray  # (T, N) the weighted sum of stances
    stances: dict[str, np.ndarray]  # analyst -> (T, N) stance

    # The letter grade of one name on one session.
    def letter(self, t: int, column: int) -> str:
        """Return "A+", "A", "B" or "C"."""
        return GRADES[3 - int(self.grades[t, column])]

    # A score for the harness: the grade first, the vote total as tie-break.
    def as_scores(self, tie_break: np.ndarray | None = None) -> np.ndarray:
        """Return (T, N) scores ordered by grade, then by `tie_break`."""
        scores = self.grades.astype(float)
        if tie_break is not None:
            with np.errstate(all="ignore"):
                spread = np.nanmax(tie_break, axis=1, keepdims=True) - np.nanmin(
                    tie_break, axis=1, keepdims=True
                )
            unit = np.where(
                np.isfinite(tie_break) & (spread > 0),
                (tie_break - np.nanmin(tie_break, axis=1, keepdims=True)) / spread,
                0.5,
            )
            scores = scores + 0.5 * unit
        return scores


# Grade every name on every session from the analysts' stances.
def grade(
    fundamental: Opinion,
    technical: Opinion,
    sentiment: Opinion,
    rotation: Opinion | None = None,
) -> Graded:
    """Return the Graded panel."""
    return grade_stances(
        fundamental.stances(),
        technical.stances(),
        sentiment.stances(),
        None if rotation is None else rotation.stances(),
    )


# The rule itself, on stances already taken.
def grade_stances(
    f: np.ndarray,
    t: np.ndarray,
    s: np.ndarray,
    r: np.ndarray | None = None,
) -> Graded:
    """Return the Graded panel from (T, N) stance arrays."""
    stances = {"fundamental": f, "technical": t, "sentiment": s}
    votes = (f + t + s).astype(float)
    if r is not None:
        stances["rotation"] = r
        votes = votes + ROTATION_WEIGHT * r
    grades = np.zeros(votes.shape, dtype=int)
    release_bullish = s == BULLISH
    both_bullish = (f == BULLISH) & (t == BULLISH)
    grades[votes >= 0.5] = ORDINAL[B]
    a_grade = (
        (votes >= 2)
        | (release_bullish & (votes >= 1))
        | (both_bullish & (votes >= 1.5))
    )
    grades[a_grade] = ORDINAL[A]
    grades[release_bullish & (votes >= 2)] = ORDINAL[A_PLUS]
    # A bearish core analyst vetoes the top grades: the trade is at most B.
    vetoed = (f == BEARISH) | (t == BEARISH) | (s == BEARISH)
    grades[vetoed & (grades > ORDINAL[B])] = ORDINAL[B]
    return Graded(grades, votes, stances)
