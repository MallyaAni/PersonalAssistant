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
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText

# What the user likes and where they live is the profile an ambient discovery
# run is scored against. Both are sealed at the persistence boundary, and both
# carry a digest of their normalized label because `EncryptedText` seals each
# value with a fresh nonce and therefore cannot support a unique constraint.


class DiscoveryInterest(Base):
    """One approved thing the user is interested in."""

    __tablename__ = "discovery_interests"
    __table_args__ = (
        # Adding the same interest twice is a no-op rather than a duplicate.
        UniqueConstraint("user_id", "label_digest", name="uq_discovery_interest_label"),
        Index("ix_discovery_interests_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    # SHA-256 of the normalized label. Deduplicates and enforces uniqueness
    # without storing a searchable copy of the plaintext.
    label_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    strength: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # Mirrors the memory subsystem's vocabulary: the profile records how a value
    # arrived so an approved proposal is never confused with a silent inference.
    provenance: Mapped[str] = mapped_column(
        String(40), nullable=False, default="user_explicit"
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
            "label": self.label,
            "strength": self.strength,
            "provenance": self.provenance,
        }


class DiscoveryLocality(Base):
    """One place the user wants discoveries near."""

    __tablename__ = "discovery_localities"
    __table_args__ = (
        UniqueConstraint("user_id", "label_digest", name="uq_discovery_locality_label"),
        Index("ix_discovery_localities_user", "user_id"),
        # The active destination is single-valued even under concurrent requests.
        Index(
            "uq_discovery_localities_active_travel",
            "user_id",
            unique=True,
            postgresql_where=text("is_travel_active IS TRUE"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    label_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # Disambiguates the place name for a source that needs more than a city.
    region: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    radius_km: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    # Needed to write a correct calendar entry, and not sensitive on its own.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="America/New_York"
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Travel mode changes where Scout looks without rewriting where the user lives.
    is_travel_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Coordinates are deliberately absent. A home latitude/longitude is the most
    # sensitive value this application could hold, and nothing consumes one yet;
    # add it when a source actually requires it rather than storing it early.

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "label": self.label,
            "region": self.region,
            "radius_km": self.radius_km,
            "timezone": self.timezone,
            "is_primary": self.is_primary,
            "is_travel_active": self.is_travel_active,
        }
