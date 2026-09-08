"""The trade grade: how many analysts agree, and how much that is worth.

The rule is fixed in advance and then measured, never fitted:

* A+: the company itself said the quarter was strong (sentiment bullish) and
  the other analysts agree on balance (votes >= 2).
* A: strong agreement without the release (fundamental and technical both
  bullish), or a bullish release with the others neutral on balance.
* B: one analyst bullish, nobody bearish.
* C: no bullish view, or the views cancel.
The valuation analyst votes like a core analyst and can veto: the desk
was buying names the market already priced richly, and cheapness against
the side of the book is information none of the other analysts had.

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
# The weight each analyst carries in the desk's sum: equal, rotation at
# half. A ridge fit toward these (`market_weights`, shrink 1) wanted
# value 0.60, fundamental 0.50, sentiment 0.42, technical 0.38, rotation
# 0.30, and applied across the whole history made a better book, 1.90
# against 1.85. Graded walk-forward, each year by weights fit only on the
# years before it, the same fit made a worse one from 2018: 25.0% a year
# at 1.61 against 27.2% at 1.65, with a shallower drawdown. The first
# number was development evidence; the second is the test. The ridge set
# stays available as RIDGE_WEIGHTS for the comparison the forward record
# will eventually settle.
ANALYST_WEIGHTS = {
    "fundamental": 1.0,
    "technical": 1.0,
    "sentiment": 1.0,
    "value": 1.0,
    "rotation": ROTATION_WEIGHT,
}
RIDGE_WEIGHTS = {
    "value": 0.60,
    "fundamental": 0.50,
    "sentiment": 0.42,
    "technical": 0.38,
    "rotation": 0.30,
}


@dataclass(frozen=True)
class Graded:
    """Every name's grade on every session, with the votes behind it."""

    grades: np.ndarray  # (T, N) ordinal in {0, 1, 2, 3}
    votes: np.ndarray  # (T, N) the weighted sum of stances
    stances: dict[str, np.ndarray]  # analyst -> (T, N) stance
    # The same sum over the analysts' continuous convictions. The grade
    # is what a person reads and what sizes a position; this is what
    # orders the names, because a rank built from four buckets throws
    # away most of what the analysts actually said.
    conviction: np.ndarray | None = None

    # The letter grade of one name on one session.
    def letter(self, t: int, column: int) -> str:
        """Return "A+", "A", "B" or "C"."""
        return GRADES[3 - int(self.grades[t, column])]

    # A score for the harness: the grade first, the vote total as tie-break.
    def as_scores(self, tie_break: np.ndarray | None = None) -> np.ndarray:
        """Return (T, N) scores: the summed conviction, or the grade."""
        if self.conviction is not None:
            return self.conviction
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
    value: Opinion | None = None,
    weights: dict[str, float] | None = None,
) -> Graded:
    """Return the Graded panel; `weights` per analyst, equal when None."""
    convictions = {
        "fundamental": fundamental.conviction(),
        "technical": technical.conviction(),
        "sentiment": sentiment.conviction(),
    }
    if rotation is not None:
        convictions["rotation"] = rotation.conviction()
    if value is not None:
        convictions["value"] = value.conviction()
    return grade_stances(
        fundamental.stances(),
        technical.stances(),
        sentiment.stances(),
        None if rotation is None else rotation.stances(),
        None if value is None else value.stances(),
        convictions,
        weights,
    )


# One name's grade from its stances alone, by the same rule as the panel:
# for the page's live re-grade, where one analyst's stance has moved
# with the price and the others stand. No persistence is applied; it is
# "if the session closed here".
def grade_from_stances(
    stances: dict[str, int], weights: dict[str, float] | None = None
) -> tuple[str, float]:
    """Return (letter, votes) for one name from {analyst: stance}."""
    w = analyst_weights(weights, tuple(stances))
    votes = float(sum(w[name] * int(stance) for name, stance in stances.items()))
    f = int(stances.get("fundamental", 0))
    t = int(stances.get("technical", 0))
    s_ = int(stances.get("sentiment", 0))
    v = int(stances.get("value", 0))
    release_bullish = s_ == BULLISH
    letter = C
    if votes >= 0.5:
        letter = B
    if (
        votes >= 2
        or (release_bullish and votes >= 1)
        or (f == BULLISH and t == BULLISH and votes >= 1.5)
    ):
        letter = A
    if release_bullish and votes >= 2:
        letter = A_PLUS
    if BEARISH in (f, t, s_, v) and ORDINAL[letter] > ORDINAL[B]:
        letter = B
    return letter, votes


# The weight each analyst's stance and conviction carry in the sum. Equal
# weights, rotation at half, is the rule; a different set is scaled to the
# same total so the grade thresholds keep their meaning.
def analyst_weights(weights: dict[str, float] | None, names) -> dict[str, float]:
    """Return {analyst: weight} over `names`, scaled to the equal-weight total."""
    equal = {n: ROTATION_WEIGHT if n == "rotation" else 1.0 for n in names}
    if not weights:
        return equal
    raw = {n: float(weights.get(n, equal[n])) for n in names}
    scale = sum(equal.values()) / max(sum(raw.values()), 1e-12)
    return {n: w * scale for n, w in raw.items()}


# The rule itself, on stances already taken.
def grade_stances(
    f: np.ndarray,
    t: np.ndarray,
    s: np.ndarray,
    r: np.ndarray | None = None,
    v: np.ndarray | None = None,
    convictions: dict[str, np.ndarray] | None = None,
    weights: dict[str, float] | None = None,
) -> Graded:
    """Return the Graded panel from (T, N) stance arrays."""
    stances = {"fundamental": f, "technical": t, "sentiment": s}
    if r is not None:
        stances["rotation"] = r
    if v is not None:
        stances["value"] = v
    w = analyst_weights(weights, tuple(stances))
    votes = np.zeros(f.shape, dtype=float)
    for name, stance in stances.items():
        votes = votes + w[name] * stance
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
    # The continuous counterpart of `votes`, weighted the same way.
    summed = None
    if convictions:
        summed = np.zeros(votes.shape)
        for name, values in convictions.items():
            summed = summed + w.get(name, 1.0) * np.nan_to_num(values)
    # A bearish core analyst vetoes the top grades: the trade is at most B.
    vetoed = (f == BEARISH) | (t == BEARISH) | (s == BEARISH)
    if v is not None:
        vetoed = vetoed | (v == BEARISH)
    grades[vetoed & (grades > ORDINAL[B])] = ORDINAL[B]
    return Graded(grades, votes, stances, summed)
