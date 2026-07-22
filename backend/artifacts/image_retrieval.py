from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ImageRetrievalPolicy:
    """Decide which ranked image hits are real matches rather than nearest noise.

    Cross-modal distances are compressed into a narrow band, so an absolute
    cutoff alone cannot separate a genuine weak match from the least-bad result
    for an unrelated query: measured on this system a true match reached 0.9531
    while an unrelated query reached 0.9518.

    The discriminating signal is the margin between the best hit and the runner
    up. A real match pulls clearly ahead; an unrelated query leaves every image
    roughly equidistant. Measured separation was 0.0211 minimum for relevant
    queries against 0.0107 maximum for distractors, so both bounds are applied:
    a coarse absolute ceiling, then a required margin.
    """

    max_distance: float
    min_margin: float

    # Candidates must be fetched without a distance pre-filter, otherwise the
    # runner up can be removed before the margin can be measured and a weak hit
    # is mistaken for the only result.
    CANDIDATE_CEILING = 2.0

    # Keep only hits that clear the ceiling and show a discriminating margin.
    def select(self, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
        within = [
            hit
            for hit in ranked
            if float(hit.get("distance", 1.0)) <= self.max_distance
        ]
        if not within:
            return []

        # A single stored image has no runner up, so the ceiling is all we have.
        if len(ranked) < 2:
            return within

        best = float(ranked[0].get("distance", 1.0))
        runner_up = float(ranked[1].get("distance", 1.0))
        if (runner_up - best) < self.min_margin:
            # Everything is roughly equidistant: the query has no visual match.
            return []
        return within
