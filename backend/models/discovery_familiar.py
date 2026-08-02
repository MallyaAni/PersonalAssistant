"""What the user already knows about, scoped to where they know it.

Novelty and familiarity are different questions. The seen store answers "have I
shown you this before"; this answers "did you already know it". For someone who
has lived somewhere for years those diverge sharply — a trail they walk weekly is
new to the database and worthless to them.

Familiarity is recorded **per locality**, which is the part that matters. Someone
who knows every trail in Arlington knows none in Denver, so the same happening is
noise at home and a genuine find while travelling. Scoping globally would make
the agent progressively useless exactly when it is most valuable.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText


class DiscoveryFamiliarItem(Base):
    """One thing the user has said they already know, in one place."""

    __tablename__ = "discovery_familiar_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "locality_digest",
            "item_digest",
            name="uq_discovery_familiar_item",
        ),
        Index("ix_discovery_familiar_scope", "user_id", "locality_digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # SHA-256 of the normalized locality label. A digest rather than a foreign
    # key so familiarity survives a place being renamed or removed, and so it can
    # be looked up without decrypting every locality row.
    locality_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # Identifies the dismissed thing. Derived from its title so dismissing the
    # same thing twice is one record.
    item_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # What the user dismissed, kept so the list can be reviewed and undone.
    label: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    # The whole point: dismissing one trail directory should suppress the family,
    # not just that instance.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "label": self.label,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
