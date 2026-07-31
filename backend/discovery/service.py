"""Application rules for the ambient discovery profile."""

from uuid import UUID

from backend.discovery.errors import DiscoveryProfileLimitError
from backend.discovery.repository import DiscoveryProfileRepository
from backend.discovery.types import (
    INTEREST_PROVENANCE,
    MAX_INTERESTS_PER_USER,
    MAX_LOCALITIES_PER_USER,
    DiscoveryProfile,
    Interest,
    Locality,
    label_digest,
)


class DiscoveryProfileService:
    """Enforce ownership, bounds, and provenance for one user's profile."""

    def __init__(self, repository: DiscoveryProfileRepository) -> None:
        self.repository = repository

    async def get_profile(self, user_id: str) -> DiscoveryProfile:
        return await self.repository.get_profile(user_id)

    # Record an interest the user approved. Provenance is validated here rather
    # than trusted from the caller so an inferred value can never be written
    # under a label that claims the user asked for it.
    async def add_interest(
        self,
        user_id: str,
        label: str,
        strength: int = 2,
        provenance: str = "user_explicit",
    ) -> Interest:
        if provenance not in INTEREST_PROVENANCE:
            raise ValueError(f"Unsupported interest provenance: {provenance}")
        await self._guard_interest_capacity(user_id, label)
        return await self.repository.upsert_interest(
            user_id, label, strength, provenance
        )

    async def add_locality(
        self,
        user_id: str,
        label: str,
        region: str | None = None,
        radius_km: int = 25,
        timezone: str = "America/New_York",
        is_primary: bool = False,
    ) -> Locality:
        await self._guard_locality_capacity(user_id, label)
        existing = await self.repository.list_localities(user_id)
        digest = label_digest(label)
        current = next(
            (item for item in existing if label_digest(item.label) == digest), None
        )
        # Promotion is explicit, but editing a place must not silently demote
        # it: an update that omits the flag keeps whatever it already had. The
        # first place a user records becomes primary so runs have a default
        # without requiring a second step.
        if is_primary:
            primary = True
        elif current is not None:
            primary = current.is_primary
        else:
            primary = not existing
        return await self.repository.upsert_locality(
            user_id, label, region, radius_km, timezone, primary
        )

    async def remove_interest(self, user_id: str, interest_id: UUID) -> bool:
        return await self.repository.delete_interest(user_id, interest_id)

    async def remove_locality(self, user_id: str, locality_id: UUID) -> bool:
        return await self.repository.delete_locality(user_id, locality_id)

    # A capacity check only rejects genuinely new labels, so editing an existing
    # interest still works once a user is at the limit.
    async def _guard_interest_capacity(self, user_id: str, label: str) -> None:
        existing = await self.repository.list_interests(user_id)
        if len(existing) < MAX_INTERESTS_PER_USER:
            return
        digest = label_digest(label)
        if any(label_digest(item.label) == digest for item in existing):
            return
        raise DiscoveryProfileLimitError(
            f"At most {MAX_INTERESTS_PER_USER} interests are supported."
        )

    async def _guard_locality_capacity(self, user_id: str, label: str) -> None:
        existing = await self.repository.list_localities(user_id)
        if len(existing) < MAX_LOCALITIES_PER_USER:
            return
        digest = label_digest(label)
        if any(label_digest(item.label) == digest for item in existing):
            return
        raise DiscoveryProfileLimitError(
            f"At most {MAX_LOCALITIES_PER_USER} localities are supported."
        )


# Render the profile for prompt injection. Only approved labels and their
# strength travel: identifiers, provenance, and timestamps are application
# bookkeeping the assistant has no use for.
def render_profile_context(profile: DiscoveryProfile) -> dict[str, object]:
    rendered: dict[str, object] = {}
    if profile.interests:
        rendered["interests"] = [
            {"label": interest.label, "strength": interest.strength}
            for interest in profile.interests
        ]
    primary = profile.primary_locality
    if primary is not None:
        rendered["lives_near"] = {
            "place": primary.label,
            "region": primary.region,
            "radius_km": primary.radius_km,
        }
    return rendered
