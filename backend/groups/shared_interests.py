"""What a group's Scout starts from: the interests its members share.

A group is an account, so its Scout sweeps run on the group's own interest
rows. Until the room says "we're all into climbing", those rows would be
empty - and the operator's point of a group is schedules on common
interests and shared cooking. So when a group is provisioned, and whenever
its membership changes, the interests that two or more members hold are
written to the group with provenance `shared_by_members`, and the ones no
longer shared are removed again. The room can add its own on top; those
carry a different provenance and are never touched here. A home locality is
seeded only when every member's primary locality agrees - a room with
members in two cities is asked where, rather than guessed.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging_config import get_logger
from backend.discovery.types import normalize_label

logger = get_logger(__name__)

SHARED_PROVENANCE = "shared_by_members"
# How many members must hold an interest for the group to hold it.
MIN_MEMBERS = 2


# Bring the group's shared interests and, when unanimous, its home locality
# in line with its members. Returns the shared labels now on the group.
async def refresh_shared_interests(
    session: AsyncSession, group_user_id: str, member_ids: tuple[str, ...]
) -> tuple[str, ...]:
    from backend.discovery.repository import DiscoveryProfileRepository

    repository = DiscoveryProfileRepository(session)
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    strengths: dict[str, list[int]] = {}
    localities: list[Any] = []
    for member in dict.fromkeys(member_ids):
        try:
            profile = await repository.get_profile(member)
        except Exception:
            logger.warning("shared_interests_member_unreadable", extra={"user": member})
            continue
        seen: set[str] = set()
        for interest in getattr(profile, "interests", ()) or ():
            label = str(getattr(interest, "label", "") or "").strip()
            key = normalize_label(label)
            if not key or key in seen:
                continue
            seen.add(key)
            counts[key] += 1
            display.setdefault(key, label)
            strengths.setdefault(key, []).append(int(getattr(interest, "strength", 2) or 2))
        primary = getattr(profile, "primary_locality", None)
        if callable(primary):
            primary = primary()
        if primary is not None:
            localities.append(primary)
    shared = {key for key, n in counts.items() if n >= min(MIN_MEMBERS, max(1, len(set(member_ids))))}

    group = await repository.get_profile(group_user_id)
    existing = {
        normalize_label(str(getattr(i, "label", "") or "")): i
        for i in (getattr(group, "interests", ()) or ())
        if str(getattr(i, "provenance", "") or "") == SHARED_PROVENANCE
    }
    for key in shared:
        strength = max(strengths.get(key, [2]))
        await repository.upsert_interest(group_user_id, display[key], strength, SHARED_PROVENANCE)
    for key, interest in existing.items():
        if key not in shared and getattr(interest, "id", None) is not None:
            await repository.delete_interest(group_user_id, interest.id)

    members_total = len(set(member_ids))
    if localities and len(localities) == members_total:
        labels = {normalize_label(str(getattr(item, "label", "") or "")) for item in localities}
        if len(labels) == 1 and not (getattr(group, "primary_locality", None)):
            first = localities[0]
            await repository.upsert_locality(
                user_id=group_user_id,
                label=str(getattr(first, "label", "") or ""),
                region=getattr(first, "region", None),
                radius_km=int(getattr(first, "radius_km", 25) or 25),
                timezone=str(getattr(first, "timezone", "") or "UTC"),
                is_primary=True,
            )
    await session.commit()
    return tuple(sorted(display[key] for key in shared))
