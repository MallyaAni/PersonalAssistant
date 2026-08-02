"""Suppress what the user already knows, in the place they know it.

The seen store answers "have I shown you this before". This answers a different
and harder question: "did you already know it". They diverge for anyone who has
lived somewhere a while — a trail they walk weekly is new to the database and
worthless to them, and a digest full of those is a digest that gets ignored.

Two properties carry the design:

- **dismissing one thing suppresses the family.** Marking a trail directory as
  known is only useful if the next four like it are also gone, so suppression is
  by embedding proximity rather than by identity;
- **familiarity is scoped to a place.** Someone who knows every trail in
  Arlington knows none in Denver. A global list would make the agent
  progressively useless exactly when travel makes it most valuable, so the same
  happening can be noise at home and a find away from it.
"""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.novelty import EMBEDDING_DIMENSIONS, ScoredCandidate
from backend.discovery.summarize import clean_title
from backend.discovery.types import label_digest, normalize_label
from backend.models.discovery_familiar import DiscoveryFamiliarItem

# Wider than the near-duplicate threshold, and deliberately so. Novelty asks
# "is this the same event", where a false positive silently hides something new.
# Familiarity asks "is this the same kind of thing I already know", where the
# user has explicitly asked to see less of it, so a broader sweep is what they
# requested rather than a risk taken on their behalf.
FAMILIAR_DISTANCE = 0.16


# Identify a dismissed thing by its normalized title, so dismissing the same
# thing twice is one record.
#
# The title is cleaned first, and both sides must do it. The user dismisses the
# title they were shown, which has already had its CMS site name stripped, while
# a candidate still carries the raw one from search. Comparing those directly
# means a dismissal silently does nothing — which is what happened the first
# time this ran.
def familiar_digest(label: str) -> str:
    return hashlib.sha256(
        normalize_label(clean_title(label)).encode("utf-8")
    ).hexdigest()


# Which place this familiarity belongs to. A digest of the locality label rather
# than a foreign key, so it survives the place being renamed or removed.
def locality_scope(locality_label: str | None) -> str:
    # No place yet means one unnamed scope rather than a crash; it merges into a
    # real locality the moment one is set.
    return label_digest(locality_label or "")


class FamiliarItemRepository:
    """Persist and query what the user already knows, per place."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def remember_known(
        self,
        user_id: str,
        locality_label: str | None,
        label: str,
        embedding: list[float] | None,
        now: datetime | None = None,
    ) -> None:
        vector = embedding
        if vector is not None and len(vector) != EMBEDDING_DIMENSIONS:
            # A misconfigured embedding model must not fail the dismissal. The
            # record still suppresses by identity, just not by similarity.
            vector = None
        stmt = insert(DiscoveryFamiliarItem).values(
            user_id=user_id,
            locality_digest=locality_scope(locality_label),
            item_digest=familiar_digest(label),
            label=clean_title(label),
            embedding=vector,
            created_at=now or datetime.now(UTC),
        )
        await self.session.execute(
            stmt.on_conflict_do_nothing(constraint="uq_discovery_familiar_item")
        )
        await self.session.commit()

    async def list_known(
        self, user_id: str, locality_label: str | None
    ) -> tuple[dict[str, object], ...]:
        stmt = (
            select(DiscoveryFamiliarItem)
            .where(
                DiscoveryFamiliarItem.user_id == user_id,
                DiscoveryFamiliarItem.locality_digest == locality_scope(locality_label),
            )
            .order_by(DiscoveryFamiliarItem.created_at.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(row.to_dict() for row in rows)

    async def forget(self, user_id: str, item_id: str) -> bool:
        import uuid as _uuid

        try:
            key = _uuid.UUID(item_id)
        except ValueError:
            return False
        row = await self.session.get(DiscoveryFamiliarItem, key)
        if row is None or row.user_id != user_id:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    async def count_known(self, user_id: str, locality_label: str | None) -> int:
        value = await self.session.scalar(
            select(func.count(DiscoveryFamiliarItem.id)).where(
                DiscoveryFamiliarItem.user_id == user_id,
                DiscoveryFamiliarItem.locality_digest == locality_scope(locality_label),
            )
        )
        return int(value or 0)

    # Whether anything the user knows *in this place* sits closer than the
    # threshold. Scoping the query is what makes travel work: a different place
    # simply matches no rows.
    async def is_familiar(
        self,
        user_id: str,
        locality_label: str | None,
        embedding: list[float],
        distance: float = FAMILIAR_DISTANCE,
    ) -> bool:
        stmt = (
            select(DiscoveryFamiliarItem.id)
            .where(
                DiscoveryFamiliarItem.user_id == user_id,
                DiscoveryFamiliarItem.locality_digest == locality_scope(locality_label),
                DiscoveryFamiliarItem.embedding.is_not(None),
                DiscoveryFamiliarItem.embedding.cosine_distance(embedding) < distance,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first() is not None

    async def known_digests(self, user_id: str, locality_label: str | None) -> set[str]:
        stmt = select(DiscoveryFamiliarItem.item_digest).where(
            DiscoveryFamiliarItem.user_id == user_id,
            DiscoveryFamiliarItem.locality_digest == locality_scope(locality_label),
        )
        return set((await self.session.execute(stmt)).scalars().all())


class FamiliarityFilter:
    """Drop candidates the user has said they already know here."""

    def __init__(self, repository: FamiliarItemRepository) -> None:
        self.repository = repository

    async def unfamiliar(
        self,
        user_id: str,
        locality_label: str | None,
        candidates: tuple[ScoredCandidate, ...],
    ) -> tuple[ScoredCandidate, ...]:
        if not candidates:
            return ()
        # One query for the exact matches, then similarity only for survivors.
        known = await self.repository.known_digests(user_id, locality_label)
        surviving: list[ScoredCandidate] = []
        for candidate in candidates:
            if familiar_digest(candidate.event.title) in known:
                continue
            if candidate.embedding is not None and await self.repository.is_familiar(
                user_id, locality_label, candidate.embedding
            ):
                continue
            surviving.append(candidate)
        return tuple(surviving)
