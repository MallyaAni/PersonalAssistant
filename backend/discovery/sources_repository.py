"""Persist the feeds one user's sweeps read."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.errors import DiscoveryProfileLimitError
from backend.discovery.types import label_digest
from backend.models.discovery_source import DiscoverySource

# `links` is a hand-curated page of links rather than a feed: someone who
# follows a city keeps one, search will not surface it, and its entries are
# undated by nature.
SOURCE_KINDS = ("ics", "rss", "links")

# Bounds a sweep's cost before it starts. The request budget is the runtime
# guard; this is the one the user sees when they add a feed too many.
MAX_SOURCES_PER_USER = 20


@dataclass(frozen=True, slots=True)
class FeedSource:
    """One configured feed, independent of how it is stored."""

    id: str
    kind: str
    url: str
    label: str | None
    enabled: bool
    last_error: str | None
    # None means everywhere. A page of DC events is worth nothing in Denver, and
    # a national feed is worth the same in both.
    locality_digest: str | None = None


class DiscoverySourceRepository:
    """Owned persistence for discovery feeds."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # `locality_label` narrows the list to feeds worth reading where the user
    # currently is: those tied to that place, plus those tied to none. Omitted,
    # every source is returned — which is what the management screen wants, and
    # what a sweep must not do.
    async def list_sources(
        self,
        user_id: str,
        enabled_only: bool = False,
        locality_label: str | None = None,
        scoped: bool = False,
    ) -> tuple[FeedSource, ...]:
        stmt = select(DiscoverySource).where(DiscoverySource.user_id == user_id)
        if enabled_only:
            stmt = stmt.where(DiscoverySource.enabled.is_(True))
        if scoped:
            digest = label_digest(locality_label) if locality_label else None
            stmt = stmt.where(
                or_(
                    DiscoverySource.locality_digest.is_(None),
                    DiscoverySource.locality_digest == digest,
                )
            )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(_to_source(row) for row in rows)

    # Adding the same URL twice edits the existing row rather than creating a
    # second fetch of the same feed.
    async def upsert_source(
        self,
        user_id: str,
        kind: str,
        url: str,
        label: str | None = None,
        enabled: bool = True,
        locality_label: str | None = None,
    ) -> FeedSource:
        if kind not in SOURCE_KINDS:
            raise ValueError(f"Unsupported source kind: {kind}")
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("A feed URL must be http or https.")

        digest = label_digest(url)
        existing = await self._by_digest(user_id, digest)
        if existing is None:
            await self._guard_capacity(user_id)
            existing = DiscoverySource(
                user_id=user_id,
                kind=kind,
                url=url,
                url_digest=digest,
                label=label,
                enabled=enabled,
                locality_digest=(
                    label_digest(locality_label) if locality_label else None
                ),
            )
            self.session.add(existing)
        else:
            existing.kind = kind
            existing.label = label if label is not None else existing.label
            existing.enabled = enabled
            existing.locality_digest = (
                label_digest(locality_label) if locality_label else None
            )
        await self.session.commit()
        await self.session.refresh(existing)
        return _to_source(existing)

    async def delete_source(self, user_id: str, source_id: uuid.UUID) -> bool:
        row = await self.session.get(DiscoverySource, source_id)
        if row is None or row.user_id != user_id:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    # Record the outcome of a fetch so a persistently broken feed is visible
    # rather than silently contributing nothing to every sweep.
    async def record_fetch(
        self, user_id: str, source_id: str, error_code: str | None
    ) -> None:
        try:
            key = uuid.UUID(source_id)
        except ValueError:
            return
        row = await self.session.get(DiscoverySource, key)
        if row is None or row.user_id != user_id:
            return
        row.last_error = error_code
        row.last_fetched_at = datetime.now(UTC)
        await self.session.commit()

    async def _by_digest(self, user_id: str, digest: str) -> DiscoverySource | None:
        stmt = select(DiscoverySource).where(
            DiscoverySource.user_id == user_id,
            DiscoverySource.url_digest == digest,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _guard_capacity(self, user_id: str) -> None:
        existing = await self.list_sources(user_id)
        if len(existing) >= MAX_SOURCES_PER_USER:
            raise DiscoveryProfileLimitError(
                f"At most {MAX_SOURCES_PER_USER} discovery sources are supported."
            )


def _to_source(row: DiscoverySource) -> FeedSource:
    return FeedSource(
        id=str(row.id),
        kind=row.kind,
        url=row.url,
        label=row.label,
        enabled=row.enabled,
        last_error=row.last_error,
        locality_digest=row.locality_digest,
    )
