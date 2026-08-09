"""Rank novel candidates against the user's approved profile.

Ranking is deterministic and runs outside the model, matching how search routing
already works here. Two reasons, both practical rather than stylistic: a sweep
happens while nobody is watching, so a sampled judgement would make the same
feed produce different results on different days; and scoring in vector space
costs one embedding call for the batch instead of one generation per candidate.

The model is not absent from the feature — it writes the digest a user reads.
It just does not decide what qualifies.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.url_dates import looks_past

# How far ahead a sweep looks. Something happening tonight is not actionable
# from a weekly digest, and something a year out is not yet a plan.
MIN_LEAD_HOURS = 12
MAX_LEAD_DAYS = 60

# A candidate must clear this to be shown at all. An empty digest is a better
# outcome than a padded one: the loop's credibility rests on not crying wolf.
MIN_SCORE = 0.25

# How far the best interest must beat the second best before it is named as the
# reason a find was chosen. Below this the find still ranks on its score, but it
# is reported with no matched interest rather than a confidently wrong one.
#
# Measured rather than picked, against this user's five interests:
#
#   Water Lantern Festival    -> Line Dancing 0.616, margin 0.010   wrong
#   Nat'l Building Museum Party -> Concerts   0.600, margin 0.005   wrong
#   Planet Word Afterhours    -> Concerts     0.604, margin 0.021   wrong
#   Live Jazz Trio, Blues Alley -> Concerts   0.612, margin 0.045   right
#   Guided Sunrise Hike       -> Hiking       0.582, margin 0.059   right
#   Country Dance, Faith Lutheran -> Line Dancing 0.592, margin 0.078  right
#   Beginner Line Dancing     -> Line Dancing 0.778, margin 0.262   right
#   Virginia Wine Festival    -> Wine Tasting 0.787, margin 0.236   right
#
# Note the absolute scores separate nothing: the three wrong matches score
# 0.600-0.616 and a real concert scores 0.612. Only the gap to the runner-up
# tells them apart, which is why this is a margin and not a floor. The wrong
# ones stop at 0.021 and the right ones start at 0.045, so the bound sits in
# between with room on both sides.
MIN_ATTRIBUTION_MARGIN = 0.035

# How many events one digest may carry.
MAX_SELECTED = 8

# Undated finds are capped separately and lower. They cannot become calendar
# entries, so they are a weaker offer than a dated one and must not crowd it out.
MAX_UNDATED = 3


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


# Cut ranked finds to a digest's size, capping dated finds and undated mentions
# separately and always listing the dated ones first.
#
# An undated find cannot become a calendar entry, so however well it reads it
# must never displace one. That rule is why a single cap cannot serve both, and
# every place that truncates a ranked list has to apply it — ranking, the
# memory re-ranker, and the runner's own fallback all pass through here so they
# cannot drift apart. Relative order within each group is preserved, so the
# caller decides the order and this decides only what fits.
def cap_by_lead_time(
    items: Sequence["RankedCandidate"],
    now: datetime,
    limit: int = MAX_SELECTED,
    undated_limit: int = MAX_UNDATED,
) -> tuple["RankedCandidate", ...]:
    dated = [item for item in items if within_lead_time(item.event.starts_at, now)]
    undated = [
        item for item in items if not within_lead_time(item.event.starts_at, now)
    ]
    return tuple(dated[:limit]) + tuple(undated[:undated_limit])


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
        undated_limit: int = MAX_UNDATED,
    ) -> tuple[RankedCandidate, ...]:
        """Dated events first, then a bounded tail of undated finds.

        A search result about a group hike with no published date cannot become
        a calendar entry, but it is still the kind of thing this loop exists to
        surface. It is admitted as a mention, capped lower than dated events so
        it never displaces one.
        """
        moment = now or datetime.now(UTC)
        admitted: list[RankedCandidate] = []
        for candidate in candidates:
            starts_at = candidate.event.starts_at
            schedulable = within_lead_time(starts_at, moment)
            # An event with a start that is past or too far out is genuinely
            # excluded; only one with no start at all becomes a mention.
            if not schedulable and starts_at is not None:
                continue
            # A mention still has to be about something that has not happened.
            # The lead-time check above cannot see this: it reads `starts_at`,
            # and these have none. The publisher's own URL often does.
            if starts_at is None and looks_past(candidate.event.url, moment.date()):
                continue
            score, matched = self._score(candidate)
            if score < MIN_SCORE:
                continue
            admitted.append(
                RankedCandidate(
                    candidate=candidate, score=score, matched_interest=matched
                )
            )

        admitted.sort(key=self._order)
        return cap_by_lead_time(admitted, moment, limit, undated_limit)

    # Score first, then soonest. A tie resolves toward the thing the user must
    # decide about first; an undated entry sorts last within its own group.
    @staticmethod
    def _order(item: RankedCandidate) -> tuple[float, datetime]:
        return (
            -item.score,
            item.candidate.event.starts_at or datetime.max.replace(tzinfo=UTC),
        )

    # The best single interest match, scaled by how strongly the user holds it.
    # Summing across interests would let a candidate that weakly resembles
    # everything outrank one that strongly matches a single stated interest.
    # How well this matches the user's stated interests, and which one. Public
    # so the notable path can ask the same question the matcher asks rather
    # than approximating it with a second scorer.
    def score(self, candidate: ScoredCandidate) -> tuple[float, str | None]:
        return self._score(candidate)

    def _score(self, candidate: ScoredCandidate) -> tuple[float, str | None]:
        if candidate.embedding is None or not self.interest_vectors:
            return 0.0, None
        best = 0.0
        runner_up = 0.0
        matched: str | None = None
        for label, vector in self.interest_vectors.items():
            similarity = cosine_similarity(candidate.embedding, vector)
            # Strength is 1 to 3; normalize so a mid-strength interest neither
            # inflates nor suppresses an otherwise good match.
            weight = self.interest_strengths.get(label, 2) / 2.0
            weighted = similarity * weight
            if weighted > best:
                best, runner_up = weighted, best
                matched = label
            elif weighted > runner_up:
                runner_up = weighted
        # A near-tie is not a match, it is a nearest neighbour.
        #
        # Every interest sits somewhere in the same space, so the best one is
        # always *something* — "Water Lantern Festival" scored 0.616 against
        # Line Dancing, and a jazz soirée scored 0.612 against Wine Tasting.
        # Both were the top of a cluster where every interest scored within a
        # hair of every other. Naming one of those is worse than naming none:
        # it is a stated reason that happens to be wrong.
        if best - runner_up < MIN_ATTRIBUTION_MARGIN:
            return best, None
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
