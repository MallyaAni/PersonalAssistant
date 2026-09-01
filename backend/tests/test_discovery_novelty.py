"""Stage 4: novelty and relevance.

The product requirement is that the loop does not repeat itself, so the tests
that matter run a real sweep twice over an unchanged feed and assert the second
one announces nothing. Everything else here supports that claim.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.database.session import AsyncSessionLocal
from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import (
    NoveltyFilter,
    ScoredCandidate,
    SeenItemRepository,
    item_digest,
)
from backend.discovery.relevance import (
    MIN_SCORE,
    RelevanceRanker,
    cosine_similarity,
    within_lead_time,
)
from backend.discovery.runner import DiscoveryRunner, events_from_digest
from backend.discovery.sources_repository import DiscoverySourceRepository
from backend.discovery.types import DiscoveryProfile, Interest
from backend.models.discovery_source import DiscoverySeenItem, DiscoverySource


# The spread keeps a digest from being eight of the same thing: the top find of
# each distinct interest leads, in the order it was ranked, and everything else
# fills behind it in that same order. Never admits anything — only reorders what
# the caller already qualified.
def test_spread_puts_one_find_of_each_interest_first():
    from backend.discovery.runner import _spread_by_interest

    vectors = {
        "jazz": [1.0, 0.0],
        "hiking": [0.0, 1.0],
    }
    # Ranked order: two jazz, one hiking, then a second jazz.
    def _candidate(title: str, vector: list[float]) -> ScoredCandidate:
        return ScoredCandidate(
            _event(title.replace(" ", "-"), title), vector
        )

    jazz_a = _candidate("Jazz night", [0.9, 0.1])
    jazz_b = _candidate("Jazz brunch", [0.8, 0.2])
    hike = _candidate("Trail walk", [0.1, 0.9])
    from backend.discovery.runner import RankedCandidate

    shortlist = (
        RankedCandidate(jazz_a, 0.9, "jazz"),
        RankedCandidate(hike, 0.8, "hiking"),
        RankedCandidate(jazz_b, 0.7, "jazz"),
    )
    spread = _spread_by_interest(shortlist, vectors, 8, 3, now=_NOW)

    # The overall best leads, then the other interest's best, then the repeat.
    assert [item.event.title for item in spread] == [
        "Jazz night",
        "Trail walk",
        "Jazz brunch",
    ]


# These tests are about novelty, so they state the setting they need. Reading it
# from the deployment's own configuration made the suite pass or fail depending
# on what an operator had switched off that afternoon — which it did.
@pytest.fixture(autouse=True)
def _novelty_enabled(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "DISCOVERY_NOVELTY_ENABLED", True)


_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


# The stored column is fixed at 768 dimensions, so test vectors are the real
# width with the signal in the leading components.
def _vec(*values: float) -> list[float]:
    vector = [0.0] * 768
    for index, value in enumerate(values):
        vector[index] = value
    return vector


# A deterministic stand-in for the embedding service. Vectors are constructed so
# similarity is predictable, which is what lets these tests assert ranking
# behaviour rather than a model's opinion.
class _StubEmbeddings:
    def __init__(self, vectors: dict[str, list[float]] | None = None) -> None:
        self.vectors = vectors or {}
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        for key, vector in self.vectors.items():
            if key.lower() in text.lower():
                return vector
        return _vec(0.0, 0.0, 1.0)


class _FailingEmbeddings:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding service unavailable")


class _StubSource:
    def __init__(self, source_id: str, events: tuple[DiscoveredEvent, ...]) -> None:
        self.id = source_id
        self.kind = "ics"
        self.url = "https://example.org/feed.ics"
        self.label = None
        self.enabled = True
        self.last_error = None
        self._events = events
        self.fetches = 0

    async def fetch(self) -> tuple[DiscoveredEvent, ...]:
        self.fetches += 1
        return self._events


def _event(external_id: str, title: str, days_ahead: int = 10) -> DiscoveredEvent:
    return DiscoveredEvent(
        source_id="src-1",
        external_id=external_id,
        title=title,
        starts_at=_NOW + timedelta(days=days_ahead),
        ends_at=None,
        place="New Haven, CT",
        url="https://example.org/e",
        summary=None,
    )


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DiscoverySeenItem).where(DiscoverySeenItem.user_id == user_id)
        )
        await session.execute(
            delete(DiscoverySource).where(DiscoverySource.user_id == user_id)
        )
        await session.commit()


def test_identity_digest_depends_on_both_source_and_external_id():
    # Two feeds can legitimately use the same internal id, so the source must
    # participate in identity or one feed would mask the other.
    assert item_digest("a", "1") != item_digest("b", "1")
    assert item_digest("a", "1") == item_digest("a", "1")


def test_lead_time_excludes_tonight_and_next_year():
    assert not within_lead_time(_NOW + timedelta(hours=2), _NOW)
    assert within_lead_time(_NOW + timedelta(days=5), _NOW)
    assert not within_lead_time(_NOW + timedelta(days=400), _NOW)
    # An event with no start cannot become a calendar entry, so it never ranks.
    assert not within_lead_time(None, _NOW)


def test_cosine_similarity_handles_degenerate_vectors():
    # A zero vector must rank last rather than raise: one bad embedding should
    # not fail a sweep that is otherwise fine.
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0


def test_ranking_prefers_the_strongest_single_interest_match():
    # Summing across interests would let something weakly resembling everything
    # beat something strongly matching one stated interest.
    ranker = RelevanceRanker(
        interest_vectors={"jazz": _vec(1.0), "pottery": _vec(0.0, 1.0)},
        interest_strengths={"jazz": 3, "pottery": 1},
    )
    strong = ScoredCandidate(_event("1", "Jazz night"), _vec(1.0))
    diffuse = ScoredCandidate(_event("2", "Mixed"), _vec(0.7, 0.7))

    ranked = ranker.rank((diffuse, strong), now=_NOW)

    assert ranked[0].candidate is strong
    assert ranked[0].matched_interest == "jazz"


def test_ranking_drops_candidates_below_the_floor():
    # An empty digest beats a padded one: the loop's credibility depends on not
    # announcing things the user never expressed interest in.
    ranker = RelevanceRanker(
        interest_vectors={"jazz": _vec(1.0)},
        interest_strengths={"jazz": 2},
    )
    unrelated = ScoredCandidate(_event("1", "Tax seminar"), _vec(0.0, 0.0, 1.0))

    assert ranker.rank((unrelated,), now=_NOW) == ()
    assert MIN_SCORE > 0.0


@pytest.mark.asyncio
async def test_a_repeated_sweep_over_an_unchanged_feed_reoffers_still_upcoming():
    """A quiet day is not a silent one: nothing new is announced, and the
    digest re-offers the still-upcoming finds already suggested."""
    user_id = f"nov_{uuid.uuid4().hex[:12]}"
    events = (_event("evt-1", "Jazz at the Green"), _event("evt-2", "Jazz brunch"))
    try:
        async with AsyncSessionLocal() as session:
            sources = DiscoverySourceRepository(session)
            source = await sources.upsert_source(
                user_id, "ics", "https://example.org/feed.ics"
            )
            stub = _StubSource(source.id, events)
            runner = DiscoveryRunner(
                sources=sources,
                seen=SeenItemRepository(session),
                embeddings=_StubEmbeddings({"jazz": _vec(1.0)}),
                adapter_factory=lambda _source, _budget: stub,
            )
            profile = DiscoveryProfile(
                interests=(
                    Interest(
                        id="i1",
                        label="jazz",
                        strength=3,
                        provenance="user_explicit",
                    ),
                ),
                localities=(),
            )
            first = await runner.sweep(user_id, profile, now=_NOW)
            second = await runner.sweep(user_id, profile, now=_NOW)

            assert len(first.selected) == 2
            # The feed was read again, and produced nothing new.
            assert stub.fetches == 2
            assert second.candidate_count == 2
            assert second.novel_count == 0
            # Novelty still decides what is new — nothing is — but a day with
            # nothing new is not a silent one: the fallback re-offers the
            # still-upcoming finds this account was already shown, so a quality
            # suggestion that has not passed returns.
            assert {item.event.title for item in second.selected} == {
                "Jazz at the Green",
                "Jazz brunch",
            }
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_an_announced_item_suppresses_a_near_duplicate():
    user_id = f"nov_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            seen = SeenItemRepository(session)
            announced = ScoredCandidate(_event("evt-1", "Jazz at the Green"), _vec(1.0))
            await seen.record_seen(user_id, announced, announced=True, now=_NOW)
            await session.commit()

            # Same happening, new identifier and a near-identical vector.
            relisted = ScoredCandidate(
                _event("evt-1-repost", "Jazz at the Green"), _vec(0.999, 0.01)
            )
            novel = await NoveltyFilter(seen).novel(user_id, (relisted,), now=_NOW)

            assert novel == ()
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_an_item_only_seen_does_not_suppress_a_later_one():
    # Being ranked out once must not permanently mask a happening the user was
    # never actually shown, or the store silently eats candidates.
    user_id = f"nov_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            seen = SeenItemRepository(session)
            unannounced = ScoredCandidate(
                _event("evt-1", "Jazz at the Green"), _vec(1.0)
            )
            await seen.record_seen(user_id, unannounced, announced=False, now=_NOW)
            await session.commit()

            similar = ScoredCandidate(
                _event("evt-2", "Jazz at the Green again"), _vec(0.999, 0.01)
            )
            novel = await NoveltyFilter(seen).novel(user_id, (similar,), now=_NOW)

            assert len(novel) == 1
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_one_feed_listing_the_same_event_twice_yields_one_candidate():
    user_id = f"nov_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            seen = SeenItemRepository(session)
            duplicate = ScoredCandidate(_event("evt-1", "Jazz"), _vec(1.0))

            novel = await NoveltyFilter(seen).novel(
                user_id, (duplicate, duplicate), now=_NOW
            )

            assert len(novel) == 1
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_an_embedding_failure_degrades_to_identity_novelty():
    # A sweep must still work when the embedding service is down; it simply
    # loses similarity suppression and ranking for that run.
    user_id = f"nov_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            sources = DiscoverySourceRepository(session)
            source = await sources.upsert_source(
                user_id, "ics", "https://example.org/feed.ics"
            )
            stub = _StubSource(source.id, (_event("evt-1", "Jazz"),))
            runner = DiscoveryRunner(
                sources=sources,
                seen=SeenItemRepository(session),
                embeddings=_FailingEmbeddings(),
                adapter_factory=lambda _source, _budget: stub,
            )
            result = await runner.sweep(
                user_id,
                DiscoveryProfile(interests=(), localities=()),
                now=_NOW,
            )

            assert result.candidate_count == 1
            assert result.novel_count == 1
            # Nothing ranks without interest vectors, which is correct: an
            # unranked candidate is not announced.
            assert result.selected == ()
    finally:
        await _cleanup(user_id)


def test_a_digest_round_trips_into_typed_events():
    from backend.discovery.relevance import RankedCandidate
    from backend.discovery.runner import SweepResult

    candidate = ScoredCandidate(_event("evt-1", "Jazz"), _vec(1.0))
    result = SweepResult(
        selected=(RankedCandidate(candidate, 0.9, "jazz"),),
        candidate_count=1,
        novel_count=1,
        requests_spent=1,
        failed_sources=(),
    )

    restored = events_from_digest(result.to_digest_json())

    assert len(restored) == 1
    assert restored[0].title == "Jazz"
    # Stage 5 needs an aware start or it cannot emit a DTSTART.
    assert restored[0].starts_at is not None
    assert restored[0].starts_at.tzinfo is not None


@pytest.mark.asyncio
async def test_a_rehearsal_records_nothing_and_repeats_identically():
    """A real sweep is useless for judging quality; a rehearsal is not.

    The novelty filter is working correctly when a second real sweep finds
    nothing, which is exactly what makes it impossible to compare output while
    adjusting interests. A rehearsal runs the whole pipeline, consults no seen
    store, and writes none.
    """
    user_id = f"nov_{uuid.uuid4().hex[:12]}"
    events = (_event("evt-1", "Jazz at the Green"), _event("evt-2", "Jazz brunch"))
    try:
        async with AsyncSessionLocal() as session:
            sources = DiscoverySourceRepository(session)
            source = await sources.upsert_source(
                user_id, "ics", "https://example.org/feed.ics"
            )
            stub = _StubSource(source.id, events)
            seen = SeenItemRepository(session)
            runner = DiscoveryRunner(
                sources=sources,
                seen=seen,
                embeddings=_StubEmbeddings({"jazz": _vec(1.0)}),
                adapter_factory=lambda _source, _budget: stub,
            )
            profile = DiscoveryProfile(
                interests=(
                    Interest(
                        id="i1", label="jazz", strength=3, provenance="user_explicit"
                    ),
                ),
                localities=(),
            )

            first = await runner.sweep(user_id, profile, now=_NOW, persist=False)
            second = await runner.sweep(user_id, profile, now=_NOW, persist=False)

            # Repeatable: the same configuration produces the same answer, which
            # is the whole point of a rehearsal.
            assert len(first.selected) == 2
            assert len(second.selected) == 2
            assert [item.event.title for item in first.selected] == [
                item.event.title for item in second.selected
            ]
            assert await seen.count_seen(user_id) == 0
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_a_real_sweep_after_a_rehearsal_still_behaves_normally():
    # A rehearsal must not have poisoned the seen store, so the real sweep that
    # follows announces everything once and then, on a quiet day, re-offers the
    # still-upcoming find rather than going silent.
    user_id = f"nov_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            sources = DiscoverySourceRepository(session)
            source = await sources.upsert_source(
                user_id, "ics", "https://example.org/feed.ics"
            )
            stub = _StubSource(source.id, (_event("evt-1", "Jazz at the Green"),))
            runner = DiscoveryRunner(
                sources=sources,
                seen=SeenItemRepository(session),
                embeddings=_StubEmbeddings({"jazz": _vec(1.0)}),
                adapter_factory=lambda _source, _budget: stub,
            )
            profile = DiscoveryProfile(
                interests=(
                    Interest(
                        id="i1", label="jazz", strength=3, provenance="user_explicit"
                    ),
                ),
                localities=(),
            )

            await runner.sweep(user_id, profile, now=_NOW, persist=False)
            real = await runner.sweep(user_id, profile, now=_NOW)
            again = await runner.sweep(user_id, profile, now=_NOW)

            assert len(real.selected) == 1
            # Nothing new, so the still-upcoming suggestion is re-offered.
            assert [item.event.title for item in again.selected] == [
                "Jazz at the Green"
            ]
    finally:
        await _cleanup(user_id)


# A real sweep has to record what it weighed, not only what it chose.
#
# The decision log is built inside `sweep`, so this is the only place that shows
# it is wired to the real shortlist rather than to a plausible-looking argument.
@pytest.mark.asyncio
async def test_a_sweep_records_the_decision_behind_its_selection():
    user_id = f"dec_{uuid.uuid4().hex[:12]}"
    events = (_event("evt-1", "Jazz at the Green"), _event("evt-2", "Jazz brunch"))
    async with AsyncSessionLocal() as session:
        sources = DiscoverySourceRepository(session)
        source = await sources.upsert_source(
            user_id, "ics", "https://example.org/feed.ics"
        )
        runner = DiscoveryRunner(
            sources=sources,
            seen=SeenItemRepository(session),
            embeddings=_StubEmbeddings({"jazz": _vec(1.0)}),
            adapter_factory=lambda _source, _budget: _StubSource(source.id, events),
        )
        profile = DiscoveryProfile(
            interests=(
                Interest(id="i1", label="jazz", strength=3, provenance="user_explicit"),
            ),
            localities=(),
        )
        result = await runner.sweep(user_id, profile, now=_NOW, persist=False)

    assert result.decision is not None
    considered = result.decision["considered"]
    # Every selected find appears, with the slot it occupied and the score and
    # interest that put it there — the features a reaction on its own lacks.
    sent = {row["digest"]: row for row in considered if row["selected"]}
    assert len(sent) == len(result.selected)
    for row in sent.values():
        assert row["position"] is not None
        assert row["propensity"] == 1.0
        assert isinstance(row["score"], float)
    # And the context the run ranked against, so a label can be read in it.
    assert result.decision["context"]["interests"]
    assert result.decision["policy"] == "deterministic_top_k"
