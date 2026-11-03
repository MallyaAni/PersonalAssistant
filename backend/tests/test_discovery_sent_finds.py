"""Reading back what Scout sent, for the chat tool that answers "what did you
send me?".

Scout is push-only: it writes a digest to a phone and nothing in the chat can
see it, so the question was answered from conversation history, which never
contains a digest, or from guesswork. `SentFindRepository.sent_for` is the read
side. The things worth proving are the ones a naive read gets wrong: one find
reaches every subscriber as its own row and must read back once, and a guest's
tapback must never be reported as the account holder's opinion.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.database.session import AsyncSessionLocal
from backend.discovery.feedback import SentFindRepository
from backend.discovery.subscribers import SubscriberRepository
from backend.models.discovery_feedback import DiscoverySentFind
from backend.models.discovery_subscriber import DiscoverySubscriber

_SENT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DiscoverySentFind).where(DiscoverySentFind.user_id == user_id)
        )
        await session.execute(
            delete(DiscoverySubscriber).where(DiscoverySubscriber.user_id == user_id)
        )
        await session.commit()


async def _subscribers(session, user_id: str) -> tuple[str, str]:
    """The account holder's own subscription and one guest's, as ids."""
    people = SubscriberRepository(session)
    owner = await people.enroll(user_id, "imessage", "+15550100")
    guest = await people.enroll(user_id, "imessage", "+15550101")
    return owner.id, guest.id


# A digest goes to every subscriber, and each recipient gets its own row. The
# account holder asks what *they* were sent, so the copies must collapse to one
# line - otherwise a digest to two phones reads back twice.
@pytest.mark.asyncio
async def test_one_find_sent_to_two_phones_reads_back_once():
    user_id = f"sent_{uuid.uuid4().hex[:12]}"
    run_id = str(uuid.uuid4())
    try:
        async with AsyncSessionLocal() as session:
            owner_id, guest_id = await _subscribers(session, user_id)
            sent = SentFindRepository(session)
            for subscriber_id in (owner_id, guest_id):
                await sent.record_sent(
                    user_id=user_id,
                    item_digest="d" * 64,
                    label="A jazz trio plays",
                    locality="Arlington, Virginia",
                    message_guid=f"GUID-{subscriber_id}",
                    run_id=run_id,
                    subscriber_id=subscriber_id,
                )
            await session.commit()

        async with AsyncSessionLocal() as session:
            finds = await SentFindRepository(session).sent_for(user_id)

        assert len(finds) == 1
        assert finds[0].title == "A jazz trio plays"
        assert finds[0].locality == "Arlington, Virginia"
    finally:
        await _cleanup(user_id)


# The boundary the owner flag exists for. The owner's copy carries no tapback
# and the guest's carries a thumbs-down; reporting that as the owner's opinion
# would teach the model something false about the person it writes for.
@pytest.mark.asyncio
async def test_a_guest_reaction_is_not_reported_as_the_owners():
    user_id = f"sent_{uuid.uuid4().hex[:12]}"
    run_id = str(uuid.uuid4())
    try:
        async with AsyncSessionLocal() as session:
            owner_id, guest_id = await _subscribers(session, user_id)
            sent = SentFindRepository(session)
            await sent.record_sent(
                user_id=user_id,
                item_digest="e" * 64,
                label="A winery evening",
                locality=None,
                message_guid="GUID-OWNER",
                run_id=run_id,
                subscriber_id=owner_id,
            )
            await sent.record_sent(
                user_id=user_id,
                item_digest="e" * 64,
                label="A winery evening",
                locality=None,
                message_guid="GUID-GUEST",
                run_id=run_id,
                subscriber_id=guest_id,
            )
            guest_row = await session.scalar(
                select(DiscoverySentFind).where(
                    DiscoverySentFind.message_guid == "GUID-GUEST"
                )
            )
            await sent.record_reaction(guest_row.id, "disliked")
            await session.commit()

        async with AsyncSessionLocal() as session:
            finds = await SentFindRepository(session).sent_for(user_id)

        assert len(finds) == 1
        assert finds[0].reaction is None
    finally:
        await _cleanup(user_id)


# The owner's own tapback is the one the read-back reports, and the date bounds
# are the model's words resolved by the caller: "yesterday's digest" must not
# reach back a week.
@pytest.mark.asyncio
async def test_the_owners_reaction_is_reported_and_the_window_is_honoured():
    user_id = f"sent_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            owner_id, _ = await _subscribers(session, user_id)
            sent = SentFindRepository(session)
            await sent.record_sent(
                user_id=user_id,
                item_digest="f" * 64,
                label="An old find",
                locality=None,
                message_guid="GUID-OLD",
                run_id=str(uuid.uuid4()),
                subscriber_id=owner_id,
            )
            await sent.record_sent(
                user_id=user_id,
                item_digest="a" * 64,
                label="A recent find",
                locality=None,
                message_guid="GUID-NEW",
                run_id=str(uuid.uuid4()),
                subscriber_id=owner_id,
            )
            rows = (
                (
                    await session.execute(
                        select(DiscoverySentFind).where(
                            DiscoverySentFind.user_id == user_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            old = next(row for row in rows if row.label == "An old find")
            new = next(row for row in rows if row.label == "A recent find")
            old.sent_at = _SENT - timedelta(days=10)
            new.sent_at = _SENT
            await sent.record_reaction(new.id, "liked")
            await session.commit()

        async with AsyncSessionLocal() as session:
            recent = await SentFindRepository(session).sent_for(
                user_id, since=_SENT - timedelta(days=1)
            )
            everything = await SentFindRepository(session).sent_for(user_id)

        assert [find.title for find in recent] == ["A recent find"]
        assert recent[0].reaction == "liked"
        # Newest first, so the reply reports the freshest send at the top.
        assert [find.title for find in everything] == [
            "A recent find",
            "An old find",
        ]
    finally:
        await _cleanup(user_id)
