"""Rank novel candidates against the user's approved profile.

Ranking is deterministic and runs outside the model, matching how search routing
already works here. Two reasons, both practical rather than stylistic: a sweep
happens while nobody is watching, so a sampled judgement would make the same
feed produce different results on different days; and scoring in vector space
costs one embedding call for the batch instead of one generation per candidate.

The model is not absent from the feature — it writes the digest a user reads.
It just does not decide what qualifies.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate

# How far ahead a sweep looks. Something happening tonight is not actionable
# from a weekly digest, and something a year out is not yet a plan.
MIN_LEAD_HOURS = 12
MAX_LEAD_DAYS = 60

# A candidate must clear this to be shown at all. An empty digest is a better
# outcome than a padded one: the loop's credibility rests on not crying wolf.
MIN_SCORE = 0.25

# How many events one digest may carry.
MAX_SELECTED = 8


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """One candidate with the score that admitted it, and why."""

    candidate: ScoredCandidate
    score: float
    matched_interest: str | None

    @property
    def event(self) -> DiscoveredEvent:
        return self.candidate.event


# Cosine similarity between two equal-length vectors. Returns 0.0 rather than
# raising for a degenerate vector, since a source that yields one should be
# ranked last, not fail the sweep.
def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return float(dot / ((left_norm**0.5) * (right_norm**0.5)))


# Whether an event is far enough out to act on and near enough to care about.
# An event with no start is not schedulable and is excluded here rather than
# being carried to stage 5 where it could not become a VEVENT anyway.
def within_lead_time(
    starts_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if starts_at is None:
        return False
    moment = now or datetime.now(UTC)
    if starts_at.tzinfo is None:
        return False
    lead = starts_at - moment
    if lead.total_seconds() < MIN_LEAD_HOURS * 3_600:
        return False
    return lead.days <= MAX_LEAD_DAYS


class RelevanceRanker:
    """Score candidates against interest vectors weighted by their strength."""

    def __init__(
        self,
        interest_vectors: dict[str, list[float]],
        interest_strengths: dict[str, int],
    ) -> None:
        self.interest_vectors = interest_vectors
        self.interest_strengths = interest_strengths

    # Rank and truncate. Sorting is by score, then by how soon the event is, so
    # a tie resolves toward the thing the user must decide about first.
    def rank(
        self,
        candidates: tuple[ScoredCandidate, ...],
        now: datetime | None = None,
        limit: int = MAX_SELECTED,
    ) -> tuple[RankedCandidate, ...]:
        moment = now or datetime.now(UTC)
        ranked: list[RankedCandidate] = []
        for candidate in candidates:
            if not within_lead_time(candidate.event.starts_at, moment):
                continue
            score, matched = self._score(candidate)
            if score < MIN_SCORE:
                continue
            ranked.append(
                RankedCandidate(
                    candidate=candidate, score=score, matched_interest=matched
                )
            )
        ranked.sort(
            key=lambda item: (
                -item.score,
                item.candidate.event.starts_at or datetime.max.replace(tzinfo=UTC),
            )
        )
        return tuple(ranked[:limit])

    # The best single interest match, scaled by how strongly the user holds it.
    # Summing across interests would let a candidate that weakly resembles
    # everything outrank one that strongly matches a single stated interest.
    def _score(self, candidate: ScoredCandidate) -> tuple[float, str | None]:
        if candidate.embedding is None or not self.interest_vectors:
            return 0.0, None
        best = 0.0
        matched: str | None = None
        for label, vector in self.interest_vectors.items():
            similarity = cosine_similarity(candidate.embedding, vector)
            # Strength is 1 to 3; normalize so a mid-strength interest neither
            # inflates nor suppresses an otherwise good match.
            weight = self.interest_strengths.get(label, 2) / 2.0
            weighted = similarity * weight
            if weighted > best:
                best = weighted
                matched = label
        return best, matched


# The text a candidate is embedded as. Title carries the signal; place and
# summary disambiguate two events sharing a name. Bounded because it enters an
# embedding request.
def candidate_text(title: str, place: str | None, summary: str | None) -> str:
    parts = [title]
    if place:
        parts.append(place)
    if summary:
        parts.append(summary[:400])
    return " — ".join(parts)
