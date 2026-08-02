"""Owned persistence and rules for who may receive a digest."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.errors import DiscoveryProfileLimitError
from backend.discovery.types import label_digest
from backend.models.discovery_subscriber import DiscoverySubscriber

# "imessage" delivers through an Apple device the operator controls.
# "shortcuts_pull" delivers nothing: the recipient's own device fetches, so
# AniOS makes no outbound connection at all.
SUBSCRIBER_CHANNELS = ("imessage", "shortcuts_pull")

# Small on purpose. This is a personal loop for people the user knows, and a
# bound is the difference between a digest and a broadcast.
MAX_SUBSCRIBERS_PER_USER = 15


@dataclass(frozen=True, slots=True)
class Subscriber:
    """One revocable delivery permission, independent of how it is stored."""

    id: str
    channel: str
    address: str
    label: str | None
    token: str
    active: bool
    deliverable: bool
    delivery_count: int
    last_error: str | None


class SubscriberRepository:
    """Persist delivery permissions for one user."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_subscribers(
        self, user_id: str, deliverable_only: bool = False
    ) -> tuple[Subscriber, ...]:
        stmt = select(DiscoverySubscriber).where(DiscoverySubscriber.user_id == user_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        selected = [row for row in rows if row.deliverable or not deliverable_only]
        return tuple(_to_subscriber(row) for row in selected)

    # Enroll or update one permission. Consent is passed explicitly and never
    # inferred: an address arriving without it is stored inactive, so the
    # default outcome of a mistake is that nothing is sent.
    async def enroll(
        self,
        user_id: str,
        channel: str,
        address: str,
        label: str | None = None,
        consented: bool = False,
    ) -> Subscriber:
        if channel not in SUBSCRIBER_CHANNELS:
            raise ValueError(f"Unsupported subscriber channel: {channel}")
        cleaned = address.strip()
        if not cleaned:
            raise ValueError("A subscriber address must not be blank.")

        digest = label_digest(cleaned)
        row = await self._by_digest(user_id, channel, digest)
        now = datetime.now(UTC)
        if row is None:
            await self._guard_capacity(user_id)
            row = DiscoverySubscriber(
                user_id=user_id,
                channel=channel,
                address=cleaned,
                address_digest=digest,
                label=label,
                token=secrets.token_urlsafe(32)[:64],
                active=consented,
                consented_at=now if consented else None,
            )
            self.session.add(row)
        else:
            row.label = label if label is not None else row.label
            if consented:
                # Re-consenting after a revocation restores delivery, but the
                # original consent timestamp is what the record keeps.
                row.consented_at = row.consented_at or now
                row.revoked_at = None
                row.active = True
        await self.session.commit()
        await self.session.refresh(row)
        return _to_subscriber(row)

    # Stop delivery immediately while keeping the record of what was already
    # sent. This is the operation the whole design exists to make cheap.
    async def revoke(self, user_id: str, subscriber_id: uuid.UUID) -> bool:
        row = await self.session.get(DiscoverySubscriber, subscriber_id)
        if row is None or row.user_id != user_id:
            return False
        row.active = False
        row.revoked_at = datetime.now(UTC)
        # Rotating the token invalidates any calendar link already shared, so
        # revocation covers what was handed out as well as what comes next.
        row.token = secrets.token_urlsafe(32)[:64]
        await self.session.commit()
        return True

    async def delete(self, user_id: str, subscriber_id: uuid.UUID) -> bool:
        row = await self.session.get(DiscoverySubscriber, subscriber_id)
        if row is None or row.user_id != user_id:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    # Resolve a subscriber by its own token, for the pull path where the
    # recipient's device asks rather than being sent to. Revoked tokens resolve
    # to nothing.
    async def by_token(self, token: str) -> tuple[str, Subscriber] | None:
        stmt = select(DiscoverySubscriber).where(DiscoverySubscriber.token == token)
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None or not row.deliverable:
            return None
        return row.user_id, _to_subscriber(row)

    async def record_delivery(self, subscriber_id: str, error_code: str | None) -> None:
        row = await self.session.get(DiscoverySubscriber, uuid.UUID(subscriber_id))
        if row is None:
            return
        row.last_error = error_code
        if error_code is None:
            row.last_delivered_at = datetime.now(UTC)
            row.delivery_count += 1
        await self.session.commit()

    async def _by_digest(
        self, user_id: str, channel: str, digest: str
    ) -> DiscoverySubscriber | None:
        stmt = select(DiscoverySubscriber).where(
            DiscoverySubscriber.user_id == user_id,
            DiscoverySubscriber.channel == channel,
            DiscoverySubscriber.address_digest == digest,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _guard_capacity(self, user_id: str) -> None:
        existing = await self.list_subscribers(user_id)
        if len(existing) >= MAX_SUBSCRIBERS_PER_USER:
            raise DiscoveryProfileLimitError(
                f"At most {MAX_SUBSCRIBERS_PER_USER} subscribers are supported."
            )


def _to_subscriber(row: DiscoverySubscriber) -> Subscriber:
    return Subscriber(
        id=str(row.id),
        channel=row.channel,
        address=row.address,
        label=row.label,
        token=row.token,
        active=row.active,
        deliverable=row.deliverable,
        delivery_count=row.delivery_count,
        last_error=row.last_error,
    )
