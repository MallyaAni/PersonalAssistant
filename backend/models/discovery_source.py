"""Feeds a discovery run reads, and the items it has already accounted for.

Both tables follow the profile's sealing pattern: the value the user supplied is
sealed with `EncryptedText` and identified by a SHA-256 digest of its normalized
form, because a sealed column carries a fresh nonce per value and therefore
cannot back a unique constraint or an equality lookup.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText


class DiscoverySource(Base):
    """One feed a user's sweeps read."""

    __tablename__ = "discovery_sources"
    __table_args__ = (
        # Adding the same feed twice is an update, not a second fetch. This is
        # also what bounds a run's request budget: sources are deduplicated
        # before a sweep counts them.
        UniqueConstraint("user_id", "url_digest", name="uq_discovery_source_url"),
        Index("ix_discovery_sources_user", "user_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # "ics" or "rss". Which adapter parses this feed is not sensitive, and
    # keeping it in the clear lets a run select sources without decrypting.
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    # The feed address is the user's own choice of what to follow, which is as
    # revealing as an interest, so it is sealed like one.
    url: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    url_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Which place this feed is about. Null means everywhere, which is what every
    # source added before scoping existed still means. A digest rather than a
    # foreign key, matching familiarity: it survives a place being renamed.
    locality_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Why a feed last failed, so a persistently broken source is visible to the
    # user rather than silently contributing nothing to every sweep.
    last_error: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "kind": self.kind,
            "url": self.url,
            "label": self.label,
            "enabled": self.enabled,
            "last_error": self.last_error,
            "last_fetched_at": (
                self.last_fetched_at.isoformat() if self.last_fetched_at else None
            ),
        }


class DiscoverySeenItem(Base):
    """One event this user has already been shown.

    The whole point of the ambient loop is that it does not repeat itself, so
    this table is the record that makes "announce once" enforceable rather than
    hoped for.
    """

    __tablename__ = "discovery_seen_items"
    __table_args__ = (
        # Identity as the source states it. This is the cheap, exact half of
        # novelty; the embedding handles the same event relisted under a new id.
        UniqueConstraint("user_id", "item_digest", name="uq_discovery_seen_item"),
        Index("ix_discovery_seen_user_time", "user_id", "first_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # SHA-256 over the source identity and the source's own external id.
    item_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # Which events a user was shown is personal even though each event is
    # public, so the title travels sealed.
    title: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Same 768-dimensional space as memory and visual artifacts, so a
    # near-duplicate check needs no second embedding model.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    # Set when the item actually reached the user. An item can be seen and
    # ranked without being announced, and only an announced one suppresses a
    # near-duplicate later.
    announced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    announced_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "item_digest": self.item_digest,
            "source_id": self.source_id,
            "title": self.title,
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "announced_at": (
                self.announced_at.isoformat() if self.announced_at else None
            ),
        }
