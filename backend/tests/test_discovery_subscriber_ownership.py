"""Which subscription belongs to the account holder.

Ownership is a permission boundary, not a label: only the owner's reactions may
shape their feed or the prose of their digest. It used to be inferred from the
earliest row, which inverted as soon as the owner removed their subscription and
a guest was added before they came back - from then on the guest's tapback was
read as the owner's verdict and the owner's own was discarded.

These tests pin the recorded flag, both paths that can set it, and the fact that
it beats the old convention when the two disagree.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.database.session import AsyncSessionLocal
from backend.discovery.feedback_loop import reacted_finds
from backend.discovery.subscribers import SubscriberRepository
from backend.models.discovery_feedback import DiscoverySentFind
from backend.models.discovery_subscriber import DiscoverySubscriber

_NOW = datetime(2026, 11, 1, 18, 0, tzinfo=UTC)


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DiscoverySentFind).where(DiscoverySentFind.user_id == user_id)
        )
        await session.execute(
            delete(DiscoverySubscriber).where(DiscoverySubscriber.user_id == user_id)
        )
        await session.commit()


# The first subscription an account has is its own; one added afterwards is a
# guest. This is the convention the old inference used, recorded instead.
@pytest.mark.asyncio
async def test_the_first_subscription_is_the_owners_and_a_guest_is_not():
    user_id = f"own_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            people = SubscriberRepository(session)
            first = await people.enroll(user_id, "imessage", "+15550100")
            second = await people.enroll(user_id, "imessage", "+15550101")

        assert first.is_owner is True
        assert second.is_owner is False
    finally:
        await _cleanup(user_id)


# The inversion, end to end. The owner removes their subscription, a guest is
# added - and by the first-row rule the guest becomes the owner - then the
# owner's phone is enrolled again, saying which row is the account holder's.
# That is the one moment ownership is known rather than guessed, so it moves
# back and the guest is demoted instead of left holding it.
@pytest.mark.asyncio
async def test_an_owner_enrolled_again_after_a_guest_takes_ownership_back():
    user_id = f"own_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            people = SubscriberRepository(session)
            owner = await people.enroll(user_id, "imessage", "+15550100")
            assert await people.delete(user_id, uuid.UUID(owner.id))

            guest = await people.enroll(user_id, "imessage", "+15550101")
            # The guest is the first remaining row, which is exactly how the
            # old inference lost track of who the account holder was.
            assert guest.is_owner is True

            returning = await people.enroll(
                user_id, "imessage", "+15550100", owner=True
            )
            listed = await people.list_subscribers(user_id)

        assert returning.is_owner is True
        assert [person.id for person in listed if person.is_owner] == [returning.id]
    finally:
        await _cleanup(user_id)


# The account asking for its own digest is the other moment ownership is known.
# A row the first-row rule left unflagged is claimed by the account that asked.
@pytest.mark.asyncio
async def test_the_account_asking_for_its_own_digest_becomes_the_owner():
    user_id = f"own_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            people = SubscriberRepository(session)
            unclaimed = await people.enroll(
                user_id, "imessage", "+15550101", consented=True, owner=False
            )
            assert unclaimed.is_owner is False

            claimed = await people.request_subscription(
                user_id, "imessage", "+15550101"
            )

        assert claimed.is_owner is True
    finally:
        await _cleanup(user_id)


# The recorded owner beats the earliest row. Here the guest's row is older, so
# the convention would read the guest's thumbs-down as the owner's verdict; the
# flag says otherwise, and only the owner's reaction is returned.
@pytest.mark.asyncio
async def test_the_recorded_owner_is_read_back_not_the_earliest_row():
    user_id = f"own_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            guest = DiscoverySubscriber(
                user_id=user_id,
                channel="imessage",
                address="+15550199",
                address_digest="d" * 64,
                token="u" * 64,
                active=True,
                is_owner=False,
                created_at=_NOW - timedelta(days=3),
            )
            owner = DiscoverySubscriber(
                user_id=user_id,
                channel="imessage",
                address="+15550100",
                address_digest="c" * 64,
                token="t" * 64,
                active=True,
                is_owner=True,
                created_at=_NOW,
            )
            session.add_all([guest, owner])
            await session.flush()
            session.add_all(
                [
                    DiscoverySentFind(
                        user_id=user_id,
                        subscriber_id=owner.id,
                        item_digest="e" * 64,
                        label="Jazz at the Green",
                        sent_at=_NOW,
                        reaction="liked",
                        reacted_at=_NOW,
                    ),
                    DiscoverySentFind(
                        user_id=user_id,
                        subscriber_id=guest.id,
                        item_digest="f" * 64,
                        label="Hot-air balloon rally",
                        sent_at=_NOW,
                        reaction="disliked",
                        reacted_at=_NOW,
                    ),
                ]
            )
            await session.commit()

            reacted = await reacted_finds(session, user_id)

        assert [find.title for find in reacted] == ["Jazz at the Green"]
    finally:
        await _cleanup(user_id)


# The one-per-account rule is a constraint, not a convention. A second owner
# cannot be written even by hand, which is what makes the transfer above safe
# to implement as "demote, flush, promote".
@pytest.mark.asyncio
async def test_a_second_owner_cannot_be_written():
    user_id = f"own_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    DiscoverySubscriber(
                        user_id=user_id,
                        channel="imessage",
                        address="+15550100",
                        address_digest="c" * 64,
                        token="t" * 64,
                        active=True,
                        is_owner=True,
                    ),
                    DiscoverySubscriber(
                        user_id=user_id,
                        channel="imessage",
                        address="+15550101",
                        address_digest="d" * 64,
                        token="u" * 64,
                        active=True,
                        is_owner=True,
                    ),
                ]
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await _cleanup(user_id)
