"""The body of one scheduled discovery sweep.

Stage 3 supplied the durable machinery — leases, exactly-once slots, write-once
delivery. This is the work that machinery carries: read the user's feeds within
a fixed request budget, drop what they have already been shown, rank what
remains against their approved interests, and persist a digest.

The order is deliberate. Novelty is decided before ranking so a repeat cannot
consume a slot in the digest, and the digest is persisted before anything tries
to deliver it, so a crash between the two leaves work to resume rather than work
to redo.

Nothing here reaches outward. A sweep writes a digest; delivering it is a
separate, permissioned stage.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from backend.discovery.errors import DiscoveryError
from backend.discovery.events import DiscoveredEvent, EventSource, FeedError
from backend.discovery.fetching import DEFAULT_RUN_REQUEST_BUDGET, RequestBudget
from backend.discovery.novelty import NoveltyFilter, ScoredCandidate, SeenItemRepository
from backend.discovery.relevance import (
    MAX_SELECTED,
    RankedCandidate,
    RelevanceRanker,
    candidate_text,
)
from backend.discovery.sources.ics import IcsEventSource
from backend.discovery.sources.rss import RssEventSource
from backend.discovery.sources_repository import DiscoverySourceRepository, FeedSource
from backend.discovery.types import DiscoveryProfile


# Only what a sweep needs from the embedding provider, so the runner can be
# tested without one and swapped without touching this module. The provider is
# synchronous, so calls are moved off the event loop rather than awaited.
class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


# How a configured feed becomes something that can be read.
class AdapterFactory(Protocol):
    def __call__(self, source: "FeedSource", budget: RequestBudget) -> EventSource: ...


@dataclass(frozen=True, slots=True)
class SweepResult:
    """What one sweep produced, before anything delivers it."""

    selected: tuple[RankedCandidate, ...]
    candidate_count: int
    novel_count: int
    requests_spent: int
    failed_sources: tuple[str, ...]

    # The persisted form. Deliberately not the model's output: a digest is
    # assembled from typed records so a feed cannot inject text that later
    # reads as instructions.
    def to_digest_json(self) -> str:
        return json.dumps(
            {
                "version": 1,
                "selected": [
                    {
                        "source_id": item.event.source_id,
                        "external_id": item.event.external_id,
                        "title": item.event.title,
                        "starts_at": (
                            item.event.starts_at.isoformat()
                            if item.event.starts_at
                            else None
                        ),
                        "ends_at": (
                            item.event.ends_at.isoformat()
                            if item.event.ends_at
                            else None
                        ),
                        "place": item.event.place,
                        "url": item.event.url,
                        "summary": item.event.summary,
                        "score": round(item.score, 4),
                        "matched_interest": item.matched_interest,
                    }
                    for item in self.selected
                ],
                "candidate_count": self.candidate_count,
                "novel_count": self.novel_count,
                "failed_sources": list(self.failed_sources),
            },
            separators=(",", ":"),
        )


# Rebuild the typed events a persisted digest describes, so stage 5 can render a
# calendar without re-fetching anything.
def events_from_digest(digest_json: str) -> tuple[DiscoveredEvent, ...]:
    try:
        payload = json.loads(digest_json)
    except (TypeError, ValueError) as exc:
        raise DiscoveryError("Stored digest is not readable JSON.") from exc
    events: list[DiscoveredEvent] = []
    for item in payload.get("selected", []):
        starts_at = _parse_moment(item.get("starts_at"))
        events.append(
            DiscoveredEvent(
                source_id=str(item.get("source_id", "")),
                external_id=str(item.get("external_id", "")),
                title=str(item.get("title", "")),
                starts_at=starts_at,
                ends_at=_parse_moment(item.get("ends_at")),
                place=item.get("place"),
                url=item.get("url"),
                summary=item.get("summary"),
            )
        )
    return tuple(events)


class DiscoveryRunner:
    """Execute one sweep for one user."""

    def __init__(
        self,
        sources: DiscoverySourceRepository,
        seen: SeenItemRepository,
        embeddings: EmbeddingClient,
        adapter_factory: AdapterFactory | None = None,
    ) -> None:
        self.sources = sources
        self.seen = seen
        self.embeddings = embeddings
        self.novelty = NoveltyFilter(seen)
        # Injected so a sweep can be exercised end to end without a network,
        # which is what makes the "announce once" guarantee testable at all.
        self.adapter_factory = adapter_factory or _adapter_for

    async def sweep(
        self,
        user_id: str,
        profile: DiscoveryProfile,
        run_id: str | None = None,
        now: datetime | None = None,
        budget_limit: int = DEFAULT_RUN_REQUEST_BUDGET,
        limit: int = MAX_SELECTED,
    ) -> SweepResult:
        moment = now or datetime.now(UTC)
        budget = RequestBudget(limit=budget_limit)

        configured = await self.sources.list_sources(user_id, enabled_only=True)
        events, failed = await self._collect(user_id, configured, budget)

        candidates = await self._embed(events)
        novel = await self.novelty.novel(user_id, candidates, now=moment)

        ranker = RelevanceRanker(
            interest_vectors=await self._interest_vectors(profile),
            interest_strengths={
                interest.label: interest.strength for interest in profile.interests
            },
        )
        selected = ranker.rank(novel, now=moment, limit=limit)

        # Everything considered is recorded, but only what was selected counts
        # as announced. An item ranked out stays eligible for a later sweep,
        # while an announced one suppresses its own near-duplicates.
        chosen = {item.candidate.digest for item in selected}
        for candidate in novel:
            await self.seen.record_seen(
                user_id,
                candidate,
                announced=candidate.digest in chosen,
                run_id=run_id,
                now=moment,
            )
        await self.seen.session.commit()

        return SweepResult(
            selected=selected,
            candidate_count=len(events),
            novel_count=len(novel),
            requests_spent=budget.spent,
            failed_sources=failed,
        )

    # Read every configured feed. One broken source degrades that source rather
    # than failing the sweep, because a user with five feeds should still hear
    # about the four that work.
    async def _collect(
        self,
        user_id: str,
        configured: tuple[FeedSource, ...],
        budget: RequestBudget,
    ) -> tuple[tuple[DiscoveredEvent, ...], tuple[str, ...]]:
        collected: list[DiscoveredEvent] = []
        failed: list[str] = []
        for source in configured:
            if budget.remaining <= 0:
                failed.append(source.id)
                continue
            adapter = self.adapter_factory(source, budget)
            try:
                events = await adapter.fetch()
            except FeedError:
                failed.append(source.id)
                await self.sources.record_fetch(user_id, source.id, "feed_unreadable")
                continue
            await self.sources.record_fetch(user_id, source.id, None)
            collected.extend(events)
        return tuple(collected), tuple(failed)

    # Embed candidates for both novelty and ranking, in one batch rather than
    # one call per event. An embedding failure downgrades the batch to
    # identity-only novelty rather than failing the sweep; those candidates
    # simply never outrank one that embedded.
    async def _embed(
        self, events: tuple[DiscoveredEvent, ...]
    ) -> tuple[ScoredCandidate, ...]:
        if not events:
            return ()
        texts = [
            candidate_text(event.title, event.place, event.summary) for event in events
        ]
        vectors = await self._embed_batch(texts)
        return tuple(
            ScoredCandidate(event=event, embedding=vector)
            for event, vector in zip(events, vectors, strict=True)
        )

    async def _interest_vectors(
        self, profile: DiscoveryProfile
    ) -> dict[str, list[float]]:
        labels = [interest.label for interest in profile.interests]
        if not labels:
            return {}
        vectors = await self._embed_batch(labels)
        return {
            label: vector
            for label, vector in zip(labels, vectors, strict=True)
            if vector is not None
        }

    # The provider is synchronous, so the call moves off the event loop. A
    # failure yields one None per input, keeping positional alignment with the
    # texts the caller supplied.
    async def _embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        try:
            vectors = await asyncio.to_thread(self.embeddings.embed_texts, texts)
        except Exception:
            return [None] * len(texts)
        if len(vectors) != len(texts):
            return [None] * len(texts)
        return list(vectors)


def _adapter_for(source: FeedSource, budget: RequestBudget) -> EventSource:
    if source.kind == "ics":
        return IcsEventSource(source.id, source.url, budget=budget)
    return RssEventSource(source.id, source.url, budget=budget)


def _parse_moment(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
