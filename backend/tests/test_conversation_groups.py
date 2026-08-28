"""A group is an account: provisioning, membership, switching off, deletion.

Runs against the test database like the admin boundary tests do.
"""

import uuid

import pytest
from sqlalchemy import delete, select

from backend.database.session import AsyncSessionLocal
from backend.discovery.addressing import address_digest
from backend.groups.repository import GROUP_CHANNEL, ConversationGroupRepository, group_user_id, is_group_id
from backend.models.auth import UserAccount
from backend.models.conversation_group import ConversationGroup, ConversationGroupMember
from backend.models.discovery_subscriber import DiscoverySubscriber
from backend.models.memory import UserProfile


def _chat() -> str:
    return f"imessage;+;chat{uuid.uuid4().int % 10**15:015d}"


async def _cleanup(chat: str) -> None:
    gid = group_user_id(chat)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConversationGroupMember).where(ConversationGroupMember.group_user_id == gid))
        await db.execute(delete(ConversationGroup).where(ConversationGroup.user_id == gid))
        await db.execute(delete(DiscoverySubscriber).where(DiscoverySubscriber.user_id == gid))
        await db.execute(delete(UserProfile).where(UserProfile.user_id == gid))
        await db.execute(delete(UserAccount).where(UserAccount.user_id == gid))
        await db.commit()


def test_group_ids_have_their_own_shape():
    chat = _chat()
    gid = group_user_id(chat)
    assert gid.startswith("group:") and len(gid) == len("group:") + 12
    assert gid == group_user_id(chat)
    assert gid != group_user_id(_chat())
    assert is_group_id(gid) and not is_group_id("ani") and not is_group_id("")


@pytest.mark.asyncio
async def test_provisioning_creates_the_account_profile_and_subscriber_once():
    chat = _chat()
    try:
        async with AsyncSessionLocal() as db:
            repo = ConversationGroupRepository(db)
            group = await repo.provision(chat, "Lunch crew", ("u-ani", "u-jen", "u-ani"))
            again = await repo.provision(chat, "Renamed", ("u-jen",))
        assert group.user_id == group_user_id(chat)
        assert group.members == ("u-ani", "u-jen")
        assert group.display_name == "Lunch crew" and group.enabled
        # Idempotent: the second call returns the group as it is, unchanged.
        assert again.user_id == group.user_id and again.display_name == "Lunch crew"
        assert again.members == ("u-ani", "u-jen")
        async with AsyncSessionLocal() as db:
            account = await db.get(UserAccount, group.user_id)
            assert account is not None and account.is_active and not account.is_admin
            subscriber = await db.scalar(select(DiscoverySubscriber).where(DiscoverySubscriber.user_id == group.user_id))
            assert subscriber is not None and subscriber.channel == GROUP_CHANNEL
            assert subscriber.address_digest == address_digest(chat)
            assert subscriber.approved_at is not None and subscriber.active
            profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == group.user_id))
            assert profile is not None and profile.name == "Lunch crew"
            found = await ConversationGroupRepository(db).by_chat_digest(address_digest(chat))
            assert found is not None and found.user_id == group.user_id
            assert await ConversationGroupRepository(db).by_user_id(group.user_id) is not None
            assert [g.user_id for g in await ConversationGroupRepository(db).groups_for_member("u-jen") if g.user_id == group.user_id]
    finally:
        await _cleanup(chat)


@pytest.mark.asyncio
async def test_membership_follows_the_chat_and_the_departed_are_kept_as_left():
    chat = _chat()
    try:
        async with AsyncSessionLocal() as db:
            repo = ConversationGroupRepository(db)
            group = await repo.provision(chat, "Trip", ("u-ani", "u-jen"))
            members = await repo.sync_members(group.user_id, ("u-ani", "u-sam"))
            assert members == ("u-ani", "u-sam")
            rows = (await db.execute(select(ConversationGroupMember).where(ConversationGroupMember.group_user_id == group.user_id))).scalars().all()
            left = {row.member_user_id: row.left_at for row in rows}
            assert left["u-jen"] is not None and left["u-ani"] is None and left["u-sam"] is None
            # Coming back clears the departure.
            assert await repo.sync_members(group.user_id, ("u-ani", "u-jen", "u-sam")) == ("u-ani", "u-jen", "u-sam")
    finally:
        await _cleanup(chat)


@pytest.mark.asyncio
async def test_a_group_can_be_silenced_restored_and_deleted():
    chat = _chat()
    try:
        async with AsyncSessionLocal() as db:
            repo = ConversationGroupRepository(db)
            group = await repo.provision(chat, "Trip", ("u-ani",))
            assert await repo.set_enabled(group.user_id, False)
            assert (await repo.by_user_id(group.user_id)).enabled is False
            assert await repo.set_enabled(group.user_id, True)
            assert await repo.set_enabled("group:nothere", False) is False
            await repo.touch(group.user_id)
            assert await repo.delete(group.user_id)
            assert await repo.by_user_id(group.user_id) is None
            assert await db.get(UserAccount, group.user_id) is None
            assert await repo.delete(group.user_id) is False
    finally:
        await _cleanup(chat)
