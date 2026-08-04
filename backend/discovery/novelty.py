"""Decide which candidates the user has not already been shown.

"Unique" is the product requirement, and repetition is the failure mode that
makes a proactive assistant worse than none. Two mechanisms carry it, in order
of cost:

1. exact identity — the source's own id, digested with the source id. Free, and
   catches the ordinary case of a feed re-listing the same event every sweep;
2. near-duplicate similarity — the same happening published under a new
   identifier, or by a second feed. Only an *announced* item suppresses a
   candidate this way, so an item that was merely seen and ranked out cannot
   silently mask a later one.

Similarity runs in Postgres against the same 768-dimensional space memory and
visual artifacts already use, so this needs no second embedding model.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.events import DiscoveredEvent
from backend.models.discovery_source import DiscoverySeenItem

# Cosine distance below which two events are treated as the same happening.
# Deliberately strict: wrongly suppressing something the user has never seen is
# invisible to them and therefore worse than an occasional near-repeat.
NEAR_DUPLICATE_DISTANCE = 0.08

# How far back a near-duplicate check looks. An annual event recurring next year
# is genuinely new, and comparing against all history would suppress it.
NEAR_DUPLICATE_HORIZON_DAYS = 120

# The stored column is fixed-width, matching the shared text/image space.
EMBEDDING_DIMENSIONS = 768


# Identify an event by its source's own identity. Digested rather than stored
# raw so the seen table carries no searchable copy of what a user follows.
def item_digest(source_id: str, external_id: str) -> str:
    payload = f"{source_id}\x1f{external_id}".encode()
    return hashlib.sha256(payload).hexdigest()


# What a candidate carries once it has been embedded, before novelty is decided.
@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    event: DiscoveredEvent
    embedding: list[float] | None

    @property
    def digest(self) -> str:
        return item_digest(self.event.source_id, self.event.external_id)


class SeenItemRepository:
    """Persist and query what a user has already been shown."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Which of these digests this user has already seen, in one round trip.
    async def known_digests(
        self, user_id: str, digests: tuple[str, ...]
    ) -> frozenset[str]:
        if not digests:
            return frozenset()
        stmt = select(DiscoverySeenItem.item_digest).where(
            DiscoverySeenItem.user_id == user_id,
            DiscoverySeenItem.item_digest.in_(digests),
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return frozenset(rows)

    # Whether an announced item within the horizon sits closer than the
    # threshold. Unannounced rows are excluded: being ranked out once must not
    # permanently mask a happening the user never actually saw.
    async def has_near_duplicate(
        self,
        user_id: str,
        embedding: list[float],
        now: datetime | None = None,
        distance: float = NEAR_DUPLICATE_DISTANCE,
    ) -> bool:
        moment = now or datetime.now(UTC)
        horizon = moment - timedelta(days=NEAR_DUPLICATE_HORIZON_DAYS)
        stmt = (
            select(DiscoverySeenItem.id)
            .where(
                DiscoverySeenItem.user_id == user_id,
                DiscoverySeenItem.announced_at.is_not(None),
                DiscoverySeenItem.announced_at >= horizon,
                DiscoverySeenItem.embedding.is_not(None),
                DiscoverySeenItem.embedding.cosine_distance(embedding) < distance,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first() is not None

    # How far this sits from the nearest thing the user has ever been shown.
    #
    # Novelty asks whether something is the same happening. This asks something
    # else: whether it is the same *kind* of thing. A forty-first trail listing
    # is novel and unremarkable, because forty like it came before; a hot-air
    # balloon festival is novel and genuinely unusual, because nothing like it
    # has. The distance to the nearest neighbour separates them, where a
    # distance to the centroid would not — the centroid of a varied history is
    # a point resembling nothing.
    #
    # Everything seen counts here, announced or not, because the question is
    # what this account's stream normally looks like rather than what was sent.
    async def nearest_seen_distance(
        self, user_id: str, embedding: list[float]
    ) -> float | None:
        stmt = (
            select(DiscoverySeenItem.embedding.cosine_distance(embedding).label("d"))
            .where(
                DiscoverySeenItem.user_id == user_id,
                DiscoverySeenItem.embedding.is_not(None),
            )
            .order_by("d")
            .limit(1)
        )
        value = (await self.session.execute(stmt)).scalars().first()
        # No history yet means nothing to be unlike, so the caller decides.
        return float(value) if value is not None else None

    # Record a candidate as seen. Concurrent sweeps for one user are possible
    # after a lease lapses, so insertion tolerates the row already existing
    # rather than failing the run.
    async def record_seen(
        self,
        user_id: str,
        candidate: ScoredCandidate,
        announced: bool,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> None:
        moment = now or datetime.now(UTC)
        event = candidate.event
        # A vector of the wrong width cannot be stored, and a misconfigured
        # embedding model must degrade this candidate to identity-only novelty
        # rather than fail the whole sweep at the insert.
        embedding = candidate.embedding
        if embedding is not None and len(embedding) != EMBEDDING_DIMENSIONS:
            embedding = None
        values: dict[str, object] = {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "item_digest": candidate.digest,
            "source_id": event.source_id,
            "title": event.title,
            "starts_at": event.starts_at,
            "embedding": embedding,
            "payload_json": json.dumps(_payload(event), separators=(",", ":")),
        }
        if announced:
            values["announced_at"] = moment
            if run_id is not None:
                values["announced_run_id"] = uuid.UUID(run_id)

        stmt = insert(DiscoverySeenItem).values(**values)
        # An item seen on an earlier sweep and announced on this one must record
        # the announcement; anything already announced keeps its first
        # timestamp, since that is what the horizon is measured from.
        update: dict[str, object] = {}
        if announced:
            update["announced_at"] = func.coalesce(
                DiscoverySeenItem.announced_at, stmt.excluded.announced_at
            )
            update["announced_run_id"] = func.coalesce(
                DiscoverySeenItem.announced_run_id, stmt.excluded.announced_run_id
            )
        if update:
            stmt = stmt.on_conflict_do_update(
                constraint="uq_discovery_seen_item", set_=update
            )
        else:
            stmt = stmt.on_conflict_do_nothing(constraint="uq_discovery_seen_item")
        await self.session.execute(stmt)

    # Rebuild one stored event so a calendar file can be produced without
    # re-fetching the feed. Scoped by user, so a digest from someone else's
    # sweep is simply not found rather than served.
    async def event_for_digest(
        self, user_id: str, digest: str
    ) -> DiscoveredEvent | None:
        stmt = select(DiscoverySeenItem).where(
            DiscoverySeenItem.user_id == user_id,
            DiscoverySeenItem.item_digest == digest,
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            return None
        return _event_from_payload(row.payload_json)

    # Every future event this user was actually announced, newest start first.
    # A subscription feed reconciles by UID against exactly this set, so an
    # item that leaves it leaves the subscriber's calendar.
    async def announced_events(
        self, user_id: str, now: datetime | None = None, limit: int = 100
    ) -> tuple[DiscoveredEvent, ...]:
        moment = now or datetime.now(UTC)
        stmt = (
            select(DiscoverySeenItem)
            .where(
                DiscoverySeenItem.user_id == user_id,
                DiscoverySeenItem.announced_at.is_not(None),
                DiscoverySeenItem.starts_at.is_not(None),
                # Past events are dropped rather than accumulating forever in
                # someone else's calendar.
                DiscoverySeenItem.starts_at >= moment,
            )
            .order_by(DiscoverySeenItem.starts_at.asc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        events: list[DiscoveredEvent] = []
        for row in rows:
            event = _event_from_payload(row.payload_json)
            if event is not None:
                events.append(event)
        return tuple(events)

    async def count_seen(self, user_id: str) -> int:
        stmt = select(func.count(DiscoverySeenItem.id)).where(
            DiscoverySeenItem.user_id == user_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # Scoped deletion, so a user can clear the loop's history without touching
    # their profile.
    async def forget_all(self, user_id: str) -> int:
        stmt = select(DiscoverySeenItem).where(DiscoverySeenItem.user_id == user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            await self.session.delete(row)
        await self.session.commit()
        return len(rows)


class NoveltyFilter:
    """Reduce a sweep's candidates to the ones worth showing."""

    def __init__(self, repository: SeenItemRepository) -> None:
        self.repository = repository

    # Returns the novel candidates in the order given. Exact identity is
    # resolved for the whole batch first, then similarity is asked only about
    # what survived, so the expensive check runs on the smallest set.
    async def novel(
        self,
        user_id: str,
        candidates: tuple[ScoredCandidate, ...],
        now: datetime | None = None,
    ) -> tuple[ScoredCandidate, ...]:
        if not candidates:
            return ()
        known = await self.repository.known_digests(
            user_id, tuple(candidate.digest for candidate in candidates)
        )
        # A feed can list the same event twice within one response, so identity
        # is also tracked within this batch.
        seen_in_batch: set[str] = set()
        novel: list[ScoredCandidate] = []
        for candidate in candidates:
            digest = candidate.digest
            if digest in known or digest in seen_in_batch:
                continue
            seen_in_batch.add(digest)
            if candidate.embedding is not None:
                duplicate = await self.repository.has_near_duplicate(
                    user_id, candidate.embedding, now=now
                )
                if duplicate:
                    continue
            novel.append(candidate)
        return tuple(novel)


# Rebuild one typed event from its stored payload, or None when the record is
# unusable. A single unreadable row must not take out a whole feed.
def _event_from_payload(payload_json: str | None) -> DiscoveredEvent | None:
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return DiscoveredEvent(
        source_id=str(payload.get("source_id", "")),
        external_id=str(payload.get("external_id", "")),
        title=str(payload.get("title", "")),
        starts_at=_parse_moment(payload.get("starts_at")),
        ends_at=_parse_moment(payload.get("ends_at")),
        place=payload.get("place"),
        url=payload.get("url"),
        summary=payload.get("summary"),
    )


def _parse_moment(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


# Only the fields a digest or calendar entry needs. The stored copy is not a
# second source of truth for the feed.
def _payload(event: DiscoveredEvent) -> dict[str, object]:
    return {
        "source_id": event.source_id,
        "external_id": event.external_id,
        "title": event.title,
        "starts_at": event.starts_at.isoformat() if event.starts_at else None,
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "place": event.place,
        "url": event.url,
        "summary": event.summary,
    }
