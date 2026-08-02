"""Who a discovery digest may be delivered to.

A subscriber is not an AniOS user. It is a revocable permission to send one
person one kind of message, and nothing more: no account, no memory, no ability
to ask the assistant anything. Keeping it that small is what lets outbound
delivery exist before multi-user identity does.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText


class DiscoverySubscriber(Base):
    """One revocable permission to deliver digests to one address."""

    __tablename__ = "discovery_subscribers"
    __table_args__ = (
        # Enrolling the same address twice updates that permission rather than
        # creating a second one, so revoking cannot leave a forgotten duplicate
        # still receiving messages.
        UniqueConstraint(
            "user_id", "channel", "address_digest", name="uq_discovery_subscriber"
        ),
        # The token is how a subscriber's own calendar feed is addressed, so it
        # must resolve without knowing which user it belongs to.
        UniqueConstraint("token", name="uq_discovery_subscriber_token"),
        Index("ix_discovery_subscribers_user", "user_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # "imessage", "shortcuts_pull", and so on. Not sensitive, and a delivery
    # attempt must be able to select by it without decrypting every row.
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    # A phone number or handle: someone else's contact detail, and the most
    # sensitive thing this table holds. Sealed, and identified by digest for the
    # same reason every other sealed value here is.
    address: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    address_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    # Unguessable, and the only thing a subscriber's calendar URL contains. A
    # leaked link exposes one person's feed and is revoked by rotating this.
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    # False stops delivery immediately without destroying the audit of what was
    # already sent. Deleting the row is a separate, also-supported action.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Recorded rather than assumed. Sending to someone who never agreed is the
    # failure this column exists to make visible.
    consented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Whether this permission currently allows delivery. Consent and revocation
    # are both checked here so no caller can accidentally test only one.
    @property
    def deliverable(self) -> bool:
        return self.active and self.revoked_at is None and self.consented_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "channel": self.channel,
            "address": self.address,
            "label": self.label,
            "active": self.active,
            "deliverable": self.deliverable,
            "consented_at": (
                self.consented_at.isoformat() if self.consented_at else None
            ),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "last_delivered_at": (
                self.last_delivered_at.isoformat() if self.last_delivered_at else None
            ),
            "delivery_count": self.delivery_count,
            "last_error": self.last_error,
        }
