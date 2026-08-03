"""Suppress what the user already knows, in the place they know it.

The seen store answers "have I shown you this before". This answers a different
and harder question: "did you already know it". They diverge for anyone who has
lived somewhere a while — a trail they walk weekly is new to the database and
worthless to them, and a digest full of those is a digest that gets ignored.

Two properties carry the design:

- **a dismissal means the thing it names.** The control says "I know <this
  happening>", so it records that happening's own identity — the same
  `source_id`/`external_id` digest novelty uses. It previously keyed on the
  cleaned title, which let a real page title collapse to a common word and
  become the key: after dismissing one county's trails page, any later find
  whose cleaned title was also "Trails" was dropped, including listings from
  other counties that had never been shown. Similarity still runs, but only far
  enough to catch the same happening carried by a second source;
- **familiarity is scoped to a place.** Someone who knows every trail in
  Arlington knows none in Denver. A global list would make the agent
  progressively useless exactly when travel makes it most valuable, so the same
  happening can be noise at home and a find away from it.

Suppression is also counted and reported. A hide the user did not intend is
otherwise undiscoverable: the panel lists what was dismissed, never what those
dismissals removed from this sweep.
"""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.novelty import (
    EMBEDDING_DIMENSIONS,
    NEAR_DUPLICATE_DISTANCE,
    ScoredCandidate,
)
from backend.discovery.summarize import clean_title
from backend.discovery.types import label_digest, normalize_label
from backend.models.discovery_familiar import DiscoveryFamiliarItem

# The same happening, listed by a second source. Not "the same kind of thing":
# a dismissal is keyed on the happening's own identity, and this exists only
# because that identity is per-source, so one 5K carried by both a parks feed
# and a running club has two external ids and would otherwise return.
#
# It was 0.16, chosen to suppress a whole family on the reasoning that the user
# had asked to see less of it. They had not: the control says "I know <this
# thing>" and names one item. A radius that wide silently answers a question
# nobody was asked, and a wrong hide is invisible by construction — the list
# shows what was dismissed, never what the dismissal cost. This is the bound
# novelty already uses for "same happening, relisted", which is the actual job.
FAMILIAR_DISTANCE = NEAR_DUPLICATE_DISTANCE


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
        item_digest: str | None = None,
    ) -> None:
        vector = embedding
        if vector is not None and len(vector) != EMBEDDING_DIMENSIONS:
            # A misconfigured embedding model must not fail the dismissal. The
            # record still suppresses by identity, just not by similarity.
            vector = None
        stmt = insert(DiscoveryFamiliarItem).values(
            user_id=user_id,
            locality_digest=locality_scope(locality_label),
            # The happening's own identity when the caller has it. Keying on the
            # title instead meant a title that cleaned down to a common word
            # became the key: dismissing one county's page left "trails" as the
            # suppression key, so any later find whose cleaned title was also
            # "Trails" — a different county, a different park authority, a
            # listing never seen before — was dropped without a trace. The same
            # identity novelty already uses cannot collide that way.
            item_digest=item_digest or familiar_digest(label),
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
        surviving, _ = await self.filter_known(user_id, locality_label, candidates)
        return surviving

    # Drop what the user knows and report how many went, so a suppression the
    # user did not intend is visible instead of being inferred from an
    # unexpectedly thin digest.
    async def filter_known(
        self,
        user_id: str,
        locality_label: str | None,
        candidates: tuple[ScoredCandidate, ...],
    ) -> tuple[tuple[ScoredCandidate, ...], int]:
        if not candidates:
            return (), 0
        # One query for the exact matches, then similarity only for survivors.
        known = await self.repository.known_digests(user_id, locality_label)
        surviving: list[ScoredCandidate] = []
        hidden = 0
        for candidate in candidates:
            # The happening's own identity, with the legacy title key still
            # honoured so dismissals made before this change keep working.
            if candidate.digest in known or familiar_digest(candidate.event.title) in (
                known
            ):
                hidden += 1
                continue
            if candidate.embedding is not None and await self.repository.is_familiar(
                user_id, locality_label, candidate.embedding
            ):
                hidden += 1
                continue
            surviving.append(candidate)
        return tuple(surviving), hidden
