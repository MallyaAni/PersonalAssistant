"""Keep discovery profile rows synchronized with approved personal-memory facts."""

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.errors import (
    DiscoveryProfileLimitError,
    DiscoveryProjectionConflictError,
)
from backend.discovery.types import (
    MAX_INTERESTS_PER_USER,
    MAX_LABEL_CHARS,
    MAX_LOCALITIES_PER_USER,
    MAX_REGION_CHARS,
    label_digest,
)
from backend.models.discovery import DiscoveryInterest, DiscoveryLocality

LOCALITY_KEY = "discovery_locality"
INTEREST_KEY_PREFIX = "discovery_interest_"
# What an unresolvable place falls back to. Named so the assumption is visible
# rather than repeated as a literal in three places.
DEFAULT_TIMEZONE = "America/New_York"
FACT_TYPE = "profile"
PURPOSE = "personalization"


# Collapse a region that repeats a segment ("Arlington, Arlington" ->
# "Arlington"). Shape, not meaning: a doubled town or state reads as a
# copy-paste error however it got written, and the doubled text then turns
# every query into "Courthouse, Arlington, Arlington" and makes a US-state
# check miss a region that is really "Virginia". Only exact repeats are
# removed, so "New York, New York" becomes "New York" and "County Dublin"
# is untouched.
def _collapse_repeated_segments(region: str) -> str:
    parts = [part for part in (piece.strip() for piece in region.split(",")) if part]
    if not parts:
        return ""
    collapsed: list[str] = [parts[0]]
    for part in parts[1:]:
        if part.casefold() != collapsed[-1].casefold():
            collapsed.append(part)
    return ", ".join(collapsed)


@dataclass(frozen=True, slots=True)
class ProjectedFact:
    """Describe one approved fact that owns a discovery profile projection."""

    fact_type: str
    fact_key: str
    value: str
    purpose: str


# Build the approved fact that owns the user's primary locality.
def locality_fact(label: str, region: str | None) -> ProjectedFact:
    value = f"{label}, {region}" if region else label
    return ProjectedFact(
        fact_type=FACT_TYPE, fact_key=LOCALITY_KEY, value=value, purpose=PURPOSE
    )


# Build a stable API-safe fact key for one normalized interest.
def interest_fact(label: str) -> ProjectedFact:
    return ProjectedFact(
        fact_type=FACT_TYPE,
        fact_key=f"{INTEREST_KEY_PREFIX}{label_digest(label)}",
        value=label,
        purpose=PURPOSE,
    )


# Identify fact keys owned by the discovery-interest projection.
def is_interest_key(fact_key: str) -> bool:
    suffix = fact_key.removeprefix(INTEREST_KEY_PREFIX)
    return fact_key.startswith(INTEREST_KEY_PREFIX) and len(suffix) == 64


class DiscoveryProjection:
    """Apply approved memory facts to the typed rows consumed by Scout."""

    # Use the caller's transaction so fact history and its projection stay atomic.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Apply one supported fact and ignore keys owned by other projections.
    async def apply_fact(self, user_id: str, fact_key: str, value: str) -> bool:
        if fact_key == LOCALITY_KEY:
            await self._apply_locality(user_id, value)
            await self.session.flush()
            return True
        if is_interest_key(fact_key):
            await self._apply_interest(user_id, fact_key, value)
            await self.session.flush()
            return True
        return False

    # Remove the typed row owned by a deleted or cleared fact.
    async def revoke_fact(self, user_id: str, fact_key: str) -> bool:
        if fact_key == LOCALITY_KEY:
            result = await self.session.execute(
                delete(DiscoveryLocality).where(
                    DiscoveryLocality.user_id == user_id,
                    DiscoveryLocality.is_primary.is_(True),
                )
            )
            return int(getattr(result, "rowcount", 0)) > 0
        if is_interest_key(fact_key):
            result = await self.session.execute(
                delete(DiscoveryInterest).where(
                    DiscoveryInterest.user_id == user_id,
                    DiscoveryInterest.label_digest
                    == fact_key.removeprefix(INTEREST_KEY_PREFIX),
                )
            )
            return int(getattr(result, "rowcount", 0)) > 0
        return False

    # Replace the primary locality while preserving explicitly watched secondary places.
    async def _apply_locality(self, user_id: str, value: str) -> None:
        label, separator, region = value.partition(",")
        label = label.strip()
        region = _collapse_repeated_segments(region.strip() if separator else "")
        if not label or len(label) > MAX_LABEL_CHARS or len(region) > MAX_REGION_CHARS:
            raise ValueError("The approved locality is outside supported bounds")
        digest = label_digest(label)
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
        existing = next((row for row in rows if row.label_digest == digest), None)
        if existing is None and len(rows) >= MAX_LOCALITIES_PER_USER:
            raise DiscoveryProfileLimitError(
                f"At most {MAX_LOCALITIES_PER_USER} localities are supported."
            )
        for row in rows:
            if row.is_primary and row.label_digest != digest:
                await self.session.delete(row)
        if existing is None:
            existing = DiscoveryLocality(
                user_id=user_id,
                label=label,
                label_digest=digest,
                region=region or None,
                radius_km=25,
                # Resolved from the place itself. Hardcoding a zone here put an
                # account living in Bali on Virginia time, so a digest set for
                # 11:15 fired at 23:15 where they were. The fallback is only
                # what an unresolvable place gets.
                timezone=await self._timezone_for(label, region or None),
                is_primary=True,
            )
            self.session.add(existing)
        else:
            existing.label = label
            existing.region = region or None
            existing.is_primary = True

    # Name the zone a place is in, falling back to the deployment default.
    #
    # A model answers and `zoneinfo` checks the answer, so an invented zone
    # cannot be stored. Kept here rather than at the API boundary because this
    # is the path a place takes when it arrives through a chat approval, which
    # is the path that had no browser timezone to use.
    async def _timezone_for(self, value: str, region: str | None) -> str:
        from backend.agents.scout.timezones import TimezoneResolver
        from backend.core.dependencies import get_llm_client

        try:
            resolved = await TimezoneResolver(get_llm_client()).resolve(value, region)
        except Exception:
            resolved = None
        return resolved or DEFAULT_TIMEZONE

    # Upsert one interest only when its value matches the fact's stable key.
    async def _apply_interest(self, user_id: str, fact_key: str, value: str) -> None:
        label = value.strip()
        digest = fact_key.removeprefix(INTEREST_KEY_PREFIX)
        if not label or len(label) > MAX_LABEL_CHARS or label_digest(label) != digest:
            raise DiscoveryProjectionConflictError(
                "An interest correction must retain its normalized label"
            )
        existing = await self.session.scalar(
            select(DiscoveryInterest).where(
                DiscoveryInterest.user_id == user_id,
                DiscoveryInterest.label_digest == digest,
            )
        )
        if existing is None:
            count = int(
                await self.session.scalar(
                    select(func.count())
                    .select_from(DiscoveryInterest)
                    .where(DiscoveryInterest.user_id == user_id)
                )
                or 0
            )
            if count >= MAX_INTERESTS_PER_USER:
                raise DiscoveryProfileLimitError(
                    f"At most {MAX_INTERESTS_PER_USER} interests are supported."
                )
            self.session.add(
                DiscoveryInterest(
                    user_id=user_id,
                    label=label,
                    label_digest=digest,
                    strength=2,
                    provenance="user_explicit",
                )
            )
        else:
            existing.label = label
