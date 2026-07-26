from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ImageRetrievalPolicy:
    """Return the leading cluster of closest image matches.

    Image search only runs after routing has already decided the turn refers to a
    stored image, so the job here is to return the best match(es), not to
    re-litigate whether the user wants an image at all.

    Cross-modal distances sit in a compressed band, and a user can own several
    similar images (two red cars). The earlier best-vs-runner-up margin therefore
    rejected genuine matches as "equidistant" precisely when more than one image
    was relevant - the multi-image failure. Instead, keep every hit within a small
    delta of the closest: one clear match, or several near-identical ones, and
    nothing when the nearest image is beyond the absolute ceiling.
    """

    max_distance: float
    cluster_delta: float
    max_results: int = 5

    # Candidates are fetched without a distance pre-filter so the leading cluster
    # is measured against the true nearest neighbours, not a truncated list.
    CANDIDATE_CEILING = 2.0

    def select(self, ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
        within = [
            hit
            for hit in ranked
            if float(hit.get("distance", 1.0)) <= self.max_distance
        ]
        if not within:
            return []
        best = float(within[0].get("distance", 1.0))
        cluster = [
            hit
            for hit in within
            if float(hit.get("distance", 1.0)) - best <= self.cluster_delta
        ]
        return cluster[: self.max_results]
