"""Things worth knowing about that match no stated interest.

Every other part of ranking is anchored to what the user said they like, which
is what keeps a digest from becoming noise. It also means the loop can only
return more of what it already knew about: a meteor shower, a one-night exhibit,
a festival nobody thought to list scores near zero against "hiking" and is
dropped before anyone sees it.

"Unusual" needs two things to be true at once, and the first is the important
one:

- **it matches no stated interest.** Something the matcher would take belongs in
  the matched section; surfacing it here as a surprise is just showing it twice
  under a heading that misdescribes it;
- **it is unlike this account's history**, measured as the distance to the
  nearest thing already shown. Not the distance to a centroid — the centroid of
  a varied history resembles nothing, so everything looks far from it.

The first criterion was missing at first, and measurement against real data
showed why it mattered: a guided night hike scored 0.362 against a ten-item
history and a hot air balloon festival scored 0.328, so the bar admitted the
hiking event and rejected the balloon festival — precisely backwards. Distance
from history is a weak signal on a short history; "the matcher did not want it"
is not.

The quota is small and separate on purpose. The subsystem's own rule is that an
empty digest beats a padded one, and an unanchored axis is the most likely way
to break that. One or two clearly-labelled extras can be ignored; a diluted
digest cannot.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.relevance import (
    MIN_SCORE,
    RankedCandidate,
    within_lead_time,
)

# How unlike the account's history something must be before it is worth
# interrupting for. Below this it is a variation on something already seen, and
# the interest-matched section is the right place for it if it belongs anywhere.
#
# Calibrated against the same scale novelty uses: 0.08 means "the same
# happening" and 0.16 was once "the same kind of thing", so this sits above
# both while staying low enough to admit a real find on a short history — the
# balloon festival measured 0.328, and a bar set by intuition at 0.35 excluded
# it. The interest ceiling below is what actually does the discriminating.
MIN_UNLIKENESS = 0.25

# Never more than this per sweep, whatever the sweep found.
MAX_NOTABLE = 2

# A candidate the matcher would have taken is not a surprise. Anything at or
# above the matcher's own floor belongs in the matched section instead, so this
# section carries only what interest-matching would have thrown away.
MAX_INTEREST_SCORE = MIN_SCORE


@dataclass(frozen=True, slots=True)
class NotableCandidate:
    """One find surfaced for being unusual rather than for matching."""

    candidate: ScoredCandidate
    unlikeness: float

    @property
    def event(self) -> DiscoveredEvent:
        return self.candidate.event


# What this needs from the seen store: one distance. Narrow on purpose, so the
# selector stays a policy object testable without a database.
class SeenHistory(Protocol):
    # How far a candidate sits from the nearest thing already shown.
    async def nearest_seen_distance(
        self, user_id: str, embedding: list[float]
    ) -> float | None: ...


class NotableSelector:
    """Pick the few finds least like anything the user has been shown."""

    # The repository is injected rather than queried directly so this stays a
    # policy object, testable without a database.
    def __init__(
        self,
        seen: SeenHistory,
        min_unlikeness: float = MIN_UNLIKENESS,
        limit: int = MAX_NOTABLE,
        max_interest_score: float = MAX_INTEREST_SCORE,
    ) -> None:
        self.seen = seen
        self.min_unlikeness = min_unlikeness
        self.limit = limit
        self.max_interest_score = max_interest_score

    # Choose the unusual few from what survived novelty and familiarity.
    #
    # `already_selected` is excluded rather than re-ranked: something that
    # matched an interest is already being shown, and showing it twice under a
    # second heading would make the digest look padded, which is the exact
    # failure this quota exists to avoid.
    async def select(
        self,
        user_id: str,
        candidates: tuple[ScoredCandidate, ...],
        already_selected: tuple[RankedCandidate, ...] = (),
        now: datetime | None = None,
        interest_scores: dict[str, float] | None = None,
    ) -> tuple[NotableCandidate, ...]:
        if not candidates:
            return ()
        taken = {item.candidate.digest for item in already_selected}
        scores = interest_scores or {}
        scored: list[NotableCandidate] = []
        for candidate in candidates:
            if candidate.digest in taken or candidate.embedding is None:
                continue
            # Something the matcher would have taken is not a surprise. Without
            # this the section filled with interest-adjacent finds — a guided
            # night hike for someone whose interest is hiking — which is the
            # matched section's job and reads as padding here.
            if scores.get(candidate.digest, 0.0) >= self.max_interest_score:
                continue
            # A dated find still has to be actionable; an undated one is shown
            # as a link, exactly as in the matched section.
            starts_at = candidate.event.starts_at
            if starts_at is not None and not within_lead_time(starts_at, now):
                continue
            distance = await self.seen.nearest_seen_distance(
                user_id, candidate.embedding
            )
            # No history means nothing to be unlike yet. Staying quiet is right:
            # on a fresh account every find would qualify, and a first digest
            # made entirely of "unusual" items teaches the wrong thing about
            # what this section means.
            if distance is None or distance < self.min_unlikeness:
                continue
            scored.append(NotableCandidate(candidate=candidate, unlikeness=distance))

        scored.sort(key=lambda item: -item.unlikeness)
        return tuple(scored[: self.limit])
