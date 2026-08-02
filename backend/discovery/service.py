"""Application rules for the ambient discovery profile."""

from typing import Protocol
from uuid import UUID

from backend.discovery.errors import DiscoveryProfileLimitError
from backend.discovery.projection import (
    LOCALITY_KEY,
    ProjectedFact,
    interest_fact,
    locality_fact,
)
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


# What this needs from memory: somewhere to put an approved fact. Narrow on
# purpose, so the profile service does not gain access to memory retrieval.
class FactRecorder(Protocol):
    # Persist one approved profile fact.
    async def record(self, user_id: str, fact: ProjectedFact) -> None: ...

    # Clear one removed profile fact by stable key.
    async def forget(self, user_id: str, fact_key: str) -> None: ...


class DiscoveryProfileService:
    """Enforce ownership, bounds, and provenance for one user's profile."""

    def __init__(
        self,
        repository: DiscoveryProfileRepository,
        facts: "FactRecorder | None" = None,
    ) -> None:
        self.repository = repository
        # Editing the profile here also records the fact in memory, so the user
        # does not maintain the same thing twice and the assistant knows what
        # the agent was told. Optional, so a caller with no memory access — a
        # background worker, a test — still works.
        self.facts = facts

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
        # The approved fact owns the typed projection. Record it first so a
        # memory failure cannot leave a profile value with no owning fact.
        await self._record(user_id, interest_fact(label))
        interest = await self.repository.upsert_interest(
            user_id, label, strength, provenance
        )
        return interest

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
        # Only the primary place is a fact about where the user lives; a
        # secondary one is somewhere they also watch.
        if primary:
            await self._record(user_id, locality_fact(label, region))
        locality = await self.repository.upsert_locality(
            user_id, label, region, radius_km, timezone, primary
        )
        return locality

    async def remove_interest(self, user_id: str, interest_id: UUID) -> bool:
        current = next(
            (
                interest
                for interest in await self.repository.list_interests(user_id)
                if UUID(interest.id) == interest_id
            ),
            None,
        )
        if current is not None and self.facts is not None:
            await self._forget(user_id, interest_fact(current.label).fact_key)
            return True
        return await self.repository.delete_interest(user_id, interest_id)

    async def remove_locality(self, user_id: str, locality_id: UUID) -> bool:
        current = next(
            (
                locality
                for locality in await self.repository.list_localities(user_id)
                if UUID(locality.id) == locality_id
            ),
            None,
        )
        if current is not None and current.is_primary and self.facts is not None:
            await self._forget(user_id, LOCALITY_KEY)
            return True
        return await self.repository.delete_locality(user_id, locality_id)

    # Start or stop travel mode without changing the approved home-locality fact.
    async def set_travel_mode(
        self, user_id: str, locality_id: UUID | None
    ) -> Locality | None:
        return await self.repository.set_travel_mode(user_id, locality_id)

    # Write the fact that owns a profile projection before returning success.
    async def _record(self, user_id: str, fact: ProjectedFact) -> None:
        if self.facts is None:
            return
        await self.facts.record(user_id, fact)

    # Clear the owning fact and its projection as one memory operation.
    async def _forget(self, user_id: str, fact_key: str) -> None:
        if self.facts is None:
            return
        await self.facts.forget(user_id, fact_key)

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
    active = profile.active_locality
    if active is not None and active.is_travel_active:
        rendered["currently_exploring"] = {
            "place": active.label,
            "region": active.region,
            "radius_km": active.radius_km,
        }
    return rendered
