"""User-scoped persistence for the ambient discovery profile."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.types import (
    DiscoveryProfile,
    Interest,
    Locality,
    label_digest,
)
from backend.models.discovery import DiscoveryInterest, DiscoveryLocality


class DiscoveryProfileRepository:
    """Read and write one user's interests and localities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Load the whole profile in one place so callers cannot forget a scope.
    async def get_profile(self, user_id: str) -> DiscoveryProfile:
        interests = await self.list_interests(user_id)
        localities = await self.list_localities(user_id)
        return DiscoveryProfile(interests=interests, localities=localities)

    async def list_interests(self, user_id: str) -> tuple[Interest, ...]:
        stmt = (
            select(DiscoveryInterest)
            .where(DiscoveryInterest.user_id == user_id)
            .order_by(
                DiscoveryInterest.strength.desc(),
                DiscoveryInterest.created_at.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(_to_interest(row) for row in rows)

    async def list_localities(self, user_id: str) -> tuple[Locality, ...]:
        stmt = (
            select(DiscoveryLocality)
            .where(DiscoveryLocality.user_id == user_id)
            .order_by(
                DiscoveryLocality.is_primary.desc(),
                DiscoveryLocality.created_at.asc(),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(_to_locality(row) for row in rows)

    async def count_interests(self, user_id: str) -> int:
        return len(await self.list_interests(user_id))

    async def count_localities(self, user_id: str) -> int:
        return len(await self.list_localities(user_id))

    # Add or update by normalized label so re-adding an interest adjusts it
    # rather than creating a second row the user would have to delete twice.
    async def upsert_interest(
        self,
        user_id: str,
        label: str,
        strength: int,
        provenance: str,
    ) -> Interest:
        digest = label_digest(label)
        existing = await self._find_interest(user_id, digest)
        if existing is None:
            existing = DiscoveryInterest(
                user_id=user_id,
                label=label,
                label_digest=digest,
                strength=strength,
                provenance=provenance,
            )
            self.session.add(existing)
        else:
            existing.label = label
            existing.strength = strength
            existing.provenance = provenance
        await self.session.commit()
        await self.session.refresh(existing)
        return _to_interest(existing)

    async def upsert_locality(
        self,
        user_id: str,
        label: str,
        region: str | None,
        radius_km: int,
        timezone: str,
        is_primary: bool,
    ) -> Locality:
        digest = label_digest(label)
        existing = await self._find_locality(user_id, digest)
        if existing is None:
            existing = DiscoveryLocality(
                user_id=user_id,
                label=label,
                label_digest=digest,
                region=region,
                radius_km=radius_km,
                timezone=timezone,
                is_primary=is_primary,
            )
            self.session.add(existing)
        else:
            existing.label = label
            existing.region = region
            existing.radius_km = radius_km
            existing.timezone = timezone
            existing.is_primary = is_primary
        if is_primary:
            await self._clear_other_primaries(user_id, digest)
        await self.session.commit()
        await self.session.refresh(existing)
        return _to_locality(existing)

    # Deletes are scoped by user as well as id so one user's identifier can
    # never remove another user's row.
    async def delete_interest(self, user_id: str, interest_id: UUID) -> bool:
        stmt = delete(DiscoveryInterest).where(
            DiscoveryInterest.user_id == user_id,
            DiscoveryInterest.id == interest_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return int(getattr(result, "rowcount", 0)) > 0

    async def delete_locality(self, user_id: str, locality_id: UUID) -> bool:
        stmt = delete(DiscoveryLocality).where(
            DiscoveryLocality.user_id == user_id,
            DiscoveryLocality.id == locality_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return int(getattr(result, "rowcount", 0)) > 0

    # Select one owned travel destination, or clear travel mode with no id.
    async def set_travel_mode(
        self, user_id: str, locality_id: UUID | None
    ) -> Locality | None:
        rows = list(
            (
                await self.session.execute(
                    select(DiscoveryLocality).where(
                        DiscoveryLocality.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        selected = next((row for row in rows if row.id == locality_id), None)
        if locality_id is not None and selected is None:
            return None
        if selected is not None and selected.is_primary:
            raise ValueError("Choose a destination other than the home locality")
        for row in rows:
            row.is_travel_active = row is selected
        await self.session.commit()
        if selected is None:
            return None
        await self.session.refresh(selected)
        return _to_locality(selected)

    async def _find_interest(
        self, user_id: str, digest: str
    ) -> DiscoveryInterest | None:
        stmt = select(DiscoveryInterest).where(
            DiscoveryInterest.user_id == user_id,
            DiscoveryInterest.label_digest == digest,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _find_locality(
        self, user_id: str, digest: str
    ) -> DiscoveryLocality | None:
        stmt = select(DiscoveryLocality).where(
            DiscoveryLocality.user_id == user_id,
            DiscoveryLocality.label_digest == digest,
        )
        return (await self.session.execute(stmt)).scalars().first()

    # Exactly one locality is primary, so promoting one demotes the rest.
    async def _clear_other_primaries(self, user_id: str, keep_digest: str) -> None:
        stmt = select(DiscoveryLocality).where(
            DiscoveryLocality.user_id == user_id,
            DiscoveryLocality.label_digest != keep_digest,
            DiscoveryLocality.is_primary.is_(True),
        )
        for row in (await self.session.execute(stmt)).scalars().all():
            row.is_primary = False


def _to_interest(row: DiscoveryInterest) -> Interest:
    return Interest(
        id=str(row.id),
        label=row.label,
        strength=row.strength,
        provenance=row.provenance,
    )


def _to_locality(row: DiscoveryLocality) -> Locality:
    return Locality(
        id=str(row.id),
        label=row.label,
        region=row.region,
        radius_km=row.radius_km,
        timezone=row.timezone,
        is_primary=row.is_primary,
        is_travel_active=row.is_travel_active,
    )
