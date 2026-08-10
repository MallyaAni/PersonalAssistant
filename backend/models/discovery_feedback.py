"""What was sent as its own message, and what the recipient made of it.

A digest used to be one message, which can only be judged as a whole. Sent as a
bubble per find, each one can carry a tapback — the reaction Messages already
offers on any bubble — and that is the first signal in this system that means
*I liked this* rather than *I already knew that*.

One row per bubble, and the reaction is written back onto it. A tapback is one
per person per message, so a second table would only ever hold one row per row
here.

Two things this deliberately does not store:

- **no address.** The subscriber is referenced by id, exactly as delivery does.
  A feedback table is a poor place to grow a second copy of who is being written
  to, and it needs the subscriber only to know whose opinion this is;
- **no message body.** The find is referenced by the same `item_digest` that
  novelty and familiarity key on, so a like, a dismissal and a suppression all
  name the same thing and can be compared later without reconciling three
  different notions of identity. The label is kept only because a digest can be
  rehearsed against finds that were never persisted.

The GUID is Apple's own message identifier, which is what a tapback points at.
It is the join between a bubble we sent and a reaction we later read, and it is
useless outside the Mac that holds that database.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText


class DiscoverySentFind(Base):
    """One find, sent as its own message, and the reaction it drew."""

    __tablename__ = "discovery_sent_finds"
    __table_args__ = (
        # A GUID identifies one bubble on one Mac. Unique so a tapback read
        # twice updates one row rather than creating a second opinion.
        UniqueConstraint("message_guid", name="uq_discovery_sent_find_guid"),
        # How the poller finds what is still worth asking about: recent bubbles
        # with no reaction yet.
        Index("ix_discovery_sent_find_pending", "reacted_at", "sent_at"),
        Index("ix_discovery_sent_find_user", "user_id", "item_digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # The run this bubble belonged to, so feedback can be traced to the sweep
    # that produced it and to the aim that chose it.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    subscriber_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # The same identity novelty and familiarity use. Nullable because a find
    # from a rehearsal has no stored identity to carry.
    item_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Sealed: a find's title says what someone is interested in.
    label: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)
    # The locality the find was offered in. A reaction means something in the
    # place it was given, for the same reason familiarity is scoped.
    locality: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Apple's message identifier. Absent when the bridge could not read it back,
    # which costs the feedback for that bubble and nothing else.
    message_guid: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # "liked" or "disliked". Null until a tapback is read, which is different
    # from a considered no opinion and must stay distinguishable from one.
    reaction: Mapped[str | None] = mapped_column(String(12), nullable=True)
    reacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
