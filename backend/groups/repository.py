"""Groups as accounts: provision, look up, and disband a group.

A group is provisioned in one transaction: an account row that cannot log in
(`group:<slug>`), the group row naming its chat, its members, a profile row,
and a subscriber row whose address is the chat itself so digests and
reminders post there. Everything else the group owns is created the way any
account's rows are - by the ordinary services, under the group's user_id.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging_config import get_logger
from backend.discovery.addressing import address_digest
from backend.discovery.subscribers import SubscriberRepository
from backend.memory.repository import MemoryRepository
from backend.models.auth import UserAccount
from backend.models.conversation_group import ConversationGroup, ConversationGroupMember
from backend.services.auth_service import hash_password

logger = get_logger(__name__)

GROUP_PREFIX = "group:"
# Which delivery channel a group's chat is on: the same Messages channel, its
# own name so the runner and the channel map can tell a room from a person.
GROUP_CHANNEL = "imessage_group"


@dataclass(frozen=True, slots=True)
class Group:
    """A group as the worker and the pipeline see it."""

    user_id: str
    chat_address: str
    chat_digest: str
    display_name: str
    enabled: bool
    members: tuple[str, ...]


# Whether a user id names a group account.
def is_group_id(user_id: str) -> bool:
    return str(user_id or "").startswith(GROUP_PREFIX)


# The account id for a chat: a short, stable slug of the chat's keyed digest.
def group_user_id(chat_address: str) -> str:
    return GROUP_PREFIX + address_digest(chat_address)[:12]


class ConversationGroupRepository:
    """Groups and their members, owned like everything else by a user_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # The group for a chat, or None.
    async def by_chat_digest(self, chat_digest: str) -> Group | None:
        row = await self.session.scalar(
            select(ConversationGroup).where(ConversationGroup.chat_digest == chat_digest)
        )
        return await self._as_group(row) if row else None

    # The group by its account id, or None.
    async def by_user_id(self, user_id: str) -> Group | None:
        row = await self.session.scalar(select(ConversationGroup).where(ConversationGroup.user_id == user_id))
        return await self._as_group(row) if row else None

    # The current members of a group, oldest first.
    async def members(self, group_user_id: str) -> tuple[str, ...]:
        rows = (
            await self.session.execute(
                select(ConversationGroupMember.member_user_id)
                .where(
                    ConversationGroupMember.group_user_id == group_user_id,
                    ConversationGroupMember.left_at.is_(None),
                )
                .order_by(ConversationGroupMember.joined_at)
            )
        ).scalars().all()
        return tuple(str(item) for item in rows)

    # Every group an account belongs to.
    async def groups_for_member(self, member_user_id: str) -> tuple[Group, ...]:
        rows = (
            await self.session.execute(
                select(ConversationGroup)
                .join(ConversationGroupMember, ConversationGroupMember.group_user_id == ConversationGroup.user_id)
                .where(
                    ConversationGroupMember.member_user_id == member_user_id,
                    ConversationGroupMember.left_at.is_(None),
                )
                .order_by(ConversationGroup.created_at)
            )
        ).scalars().all()
        return tuple([await self._as_group(row) for row in rows])

    # Every group, for the operator's list. Read column by column: the name
    # and address are sealed, and one row this process cannot unseal (a key
    # rotated, a test container without the key beside a live row) must not
    # cost the operator the whole list - it is listed as unreadable instead.
    async def list_all(self) -> tuple[Group, ...]:
        rows = (
            await self.session.execute(
                select(
                    ConversationGroup.user_id,
                    ConversationGroup.chat_digest,
                    ConversationGroup.enabled,
                ).order_by(ConversationGroup.created_at)
            )
        ).all()
        groups: list[Group] = []
        for user_id, chat_digest, enabled in rows:
            groups.append(
                Group(
                    user_id=str(user_id),
                    chat_address="",
                    chat_digest=str(chat_digest),
                    display_name=await self._display_name(str(user_id)),
                    enabled=bool(enabled),
                    members=await self.members(str(user_id)),
                )
            )
        return tuple(groups)

    # A group's sealed name, or "(unreadable)" when this process lacks the
    # key that sealed it.
    async def _display_name(self, user_id: str) -> str:
        try:
            name = await self.session.scalar(
                select(ConversationGroup.display_name).where(ConversationGroup.user_id == user_id)
            )
            return str(name or "")
        except Exception:
            logger.warning("conversation_group_name_unreadable", extra={"user": user_id})
            return "(unreadable)"

    # Create the group's account and rows in one transaction, or return the
    # existing group for this chat. Idempotent per chat.
    async def provision(
        self, chat_address: str, display_name: str, member_user_ids: tuple[str, ...]
    ) -> Group:
        digest = address_digest(chat_address)
        existing = await self.by_chat_digest(digest)
        if existing is not None:
            return existing
        user_id = group_user_id(chat_address)
        slug = user_id[len(GROUP_PREFIX):]
        # An account that cannot log in: a random password nobody knows, and
        # never an operator. `normalize_user_id` would refuse the colon, which
        # is deliberate - a group id is not something sign-up can produce.
        account = UserAccount(
            user_id=user_id,
            username=f"group-{slug}",
            password_hash=hash_password("Gr0up-" + secrets.token_urlsafe(24)),
            is_active=True,
            is_admin=False,
        )
        self.session.add(account)
        self.session.add(
            ConversationGroup(
                user_id=user_id,
                chat_address=chat_address,
                chat_digest=digest,
                chat_channel="imessage",
                display_name=display_name or None,
                enabled=True,
            )
        )
        for member in dict.fromkeys(member_user_ids):
            self.session.add(ConversationGroupMember(group_user_id=user_id, member_user_id=member))
        await self.session.flush()
        await MemoryRepository(self.session).upsert_user_profile(user_id, display_name or "the group", {})
        await SubscriberRepository(self.session).enroll(
            user_id, GROUP_CHANNEL, chat_address, label="Group chat", consented=True
        )
        await self.session.commit()
        return Group(
            user_id=user_id,
            chat_address=chat_address,
            chat_digest=digest,
            display_name=display_name,
            enabled=True,
            members=tuple(dict.fromkeys(member_user_ids)),
        )

    # Bring the membership in line with who is in the chat now: newcomers
    # join, the departed are marked as left (never deleted - provenance on
    # what they said stays meaningful).
    async def sync_members(self, group_user_id: str, member_user_ids: tuple[str, ...]) -> tuple[str, ...]:
        wanted = set(member_user_ids)
        rows = (
            await self.session.execute(
                select(ConversationGroupMember).where(ConversationGroupMember.group_user_id == group_user_id)
            )
        ).scalars().all()
        now = datetime.now(UTC)
        seen: set[str] = set()
        for row in rows:
            seen.add(row.member_user_id)
            if row.member_user_id in wanted:
                row.left_at = None
            elif row.left_at is None:
                row.left_at = now
        for member in wanted - seen:
            self.session.add(ConversationGroupMember(group_user_id=group_user_id, member_user_id=member))
        await self.session.commit()
        return await self.members(group_user_id)

    # Note that the group was spoken to, for the operator's list.
    async def touch(self, group_user_id: str) -> None:
        row = await self.session.scalar(select(ConversationGroup).where(ConversationGroup.user_id == group_user_id))
        if row is not None:
            row.last_message_at = datetime.now(UTC)
            await self.session.commit()

    # Silence or restore a group without forgetting it.
    async def set_enabled(self, group_user_id: str, enabled: bool) -> bool:
        row = await self.session.scalar(select(ConversationGroup).where(ConversationGroup.user_id == group_user_id))
        if row is None:
            return False
        row.enabled = enabled
        await self.session.commit()
        return True

    # Remove the group's own rows; the caller purges the account's memory the
    # way it purges any account's (the schema-driven purge reaches everything
    # keyed by the group's user_id).
    async def delete(self, group_user_id: str) -> bool:
        row = await self.session.scalar(select(ConversationGroup).where(ConversationGroup.user_id == group_user_id))
        if row is None:
            return False
        await self.session.delete(row)
        account = await self.session.get(UserAccount, group_user_id)
        if account is not None:
            await self.session.delete(account)
        await self.session.commit()
        return True

    async def _as_group(self, row: ConversationGroup) -> Group:
        return Group(
            user_id=row.user_id,
            chat_address=row.chat_address,
            chat_digest=row.chat_digest,
            display_name=row.display_name or "",
            enabled=bool(row.enabled),
            members=await self.members(row.user_id),
        )


# What a repository result looks like as plain data, for the admin route.
def as_dict(group: Group) -> dict[str, Any]:
    return {
        "user_id": group.user_id,
        "display_name": group.display_name,
        "enabled": group.enabled,
        "members": list(group.members),
    }
