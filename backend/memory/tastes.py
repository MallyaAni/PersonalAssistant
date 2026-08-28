"""What a group may know about its members: the non-sensitive.

A member's memory is theirs, and a room has other people in it. The
operator's decision (2026-08-28, widening the first cut's "tastes only"):
in a group where everyone is approved, a member's non-sensitive memory is
known automatically - their name, what they like, their home area, and the
everyday things they have told the assistant - and only what is sensitive
stays theirs to share. This module is the one door from a member's store to
a group turn: profile name (or account name), Scout interests, city-level
home, and remembered statements read through Scout's own
`PersonalContextReader` (approved, screened for secrets and personal
medical/financial/legal framing, bounded) and then judged by meaning
(`share_screen`) before any of them reaches the room. What is not read here
does not reach the room; what is judged private does not either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.core.logging_config import get_logger

logger = get_logger(__name__)

MAX_INTERESTS = 8
# Everyday statements per member, after the share screen. Few: a room's
# prompt carries every member.
MAX_FACTS = 6


@dataclass(frozen=True, slots=True)
class Taste:
    """One member as the room may know them."""

    user_id: str
    name: str
    interests: tuple[str, ...]
    home: str = ""
    facts: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "interests": list(self.interests),
            "home": self.home,
            "facts": list(self.facts),
        }


class TasteProjection:
    """Read-only door from a member's profile and memory to the group turn."""

    # `judge` is the routing model that decides what is private; without one
    # no remembered statement reaches the room (fail closed).
    def __init__(self, memory: Any, discovery_profile: Any | None, judge: Any | None = None) -> None:
        self.memory = memory
        self.discovery_profile = discovery_profile
        self.judge = judge

    # Each member's name and interests, in roster order. A member whose
    # profile cannot be read is still on the roster, by a placeholder name,
    # so attribution can name everyone who is in the room.
    async def for_members(self, member_ids: tuple[str, ...]) -> tuple[Taste, ...]:
        tastes: list[Taste] = []
        for position, user_id in enumerate(member_ids, start=1):
            tastes.append(await self._one(user_id, position))
        return tuple(tastes)

    async def _one(self, user_id: str, position: int) -> Taste:
        name = ""
        try:
            profile = await self.memory.get_user_profile(user_id)
            name = str(getattr(profile, "name", "") or "").strip() if profile else ""
        except Exception:
            logger.warning("taste_projection_profile_unreadable", extra={"user": user_id})
        if not name:
            # No preferred name on record: the account's username, made
            # readable ("ani.mallya" → "Ani"), before any placeholder. The
            # operator's first live group turn addressed them as "Member 2".
            name = await self._username(user_id)
        interests: tuple[str, ...] = ()
        home = ""
        if self.discovery_profile is not None:
            try:
                scout = await self.discovery_profile.get_profile(user_id)
                interests = tuple(
                    str(interest.label) for interest in scout.interests[:MAX_INTERESTS]
                )
                locality = scout.primary_locality() if hasattr(scout, "primary_locality") else None
                home = str(getattr(locality, "label", "") or "") if locality else ""
            except Exception:
                logger.warning("taste_projection_interests_unreadable", extra={"user": user_id})
        facts = await self._facts(user_id)
        return Taste(user_id=user_id, name=name or f"Member {position}", interests=interests, home=home, facts=facts)

    # The member's remembered statements that may be said in the room: read
    # through Scout's door (approved, screened, bounded), then judged.
    async def _facts(self, user_id: str) -> tuple[str, ...]:
        if self.judge is None:
            return ()
        try:
            statements = await self._statements(user_id)
        except Exception:
            logger.warning("taste_projection_memory_unreadable", extra={"user": user_id})
            return ()
        if not statements:
            return ()
        from backend.memory.share_screen import shareable

        allowed = await shareable(self.judge, statements)
        return tuple(allowed[:MAX_FACTS])

    async def _statements(self, user_id: str) -> tuple[str, ...]:
        from backend.database.session import AsyncSessionLocal
        from backend.discovery.personal_context import PersonalContextReader

        async with AsyncSessionLocal() as db:
            context = await PersonalContextReader(db).read(user_id)
        return tuple(context.statements)

    # The account's username as a first name: the part before the first
    # separator, trailing digits dropped, capitalised. Empty when unreadable.
    async def _username(self, user_id: str) -> str:
        try:
            from backend.database.session import AsyncSessionLocal
            from backend.models.auth import UserAccount

            async with AsyncSessionLocal() as db:
                account = await db.get(UserAccount, user_id)
            return humanize_username(str(getattr(account, "username", "") or ""))
        except Exception:
            return ""


# "ani.mallya" → "Ani", "jenos1" → "Jenos", "amanda_k" → "Amanda". Empty in,
# empty out.
def humanize_username(username: str) -> str:
    first = re.split(r"[._\-\s]+", username.strip())[0] if username.strip() else ""
    first = re.sub(r"\d+$", "", first)
    return first[:1].upper() + first[1:] if first else ""
