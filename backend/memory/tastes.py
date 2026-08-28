"""What a group may know about its members: tastes, and nothing else.

A member's memory is theirs. In a group the assistant still has to suggest
a restaurant everyone will like, so this projects a small, fixed allowlist
of each member's profile into the group turn - their name and the interests
they follow - and never a fact, an address, a relationship, or anything a
member said in a private conversation (ADR 0016). The allowlist is the
whole of this module; a field not read here does not reach the room.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.core.logging_config import get_logger

logger = get_logger(__name__)

MAX_INTERESTS = 8


@dataclass(frozen=True, slots=True)
class Taste:
    """One member as the room may know them."""

    user_id: str
    name: str
    interests: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "name": self.name, "interests": list(self.interests)}


class TasteProjection:
    """Read-only door from a member's profile to the group turn."""

    def __init__(self, memory: Any, discovery_profile: Any | None) -> None:
        self.memory = memory
        self.discovery_profile = discovery_profile

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
        if self.discovery_profile is not None:
            try:
                scout = await self.discovery_profile.get_profile(user_id)
                interests = tuple(
                    str(interest.label) for interest in scout.interests[:MAX_INTERESTS]
                )
            except Exception:
                logger.warning("taste_projection_interests_unreadable", extra={"user": user_id})
        return Taste(user_id=user_id, name=name or f"Member {position}", interests=interests)

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
