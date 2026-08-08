import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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


class DiscoverySchedule(Base):
    """How often one user wants an ambient discovery sweep."""

    __tablename__ = "discovery_schedules"
    __table_args__ = (
        # One schedule per user keeps "when is my next sweep" unambiguous.
        UniqueConstraint("user_id", name="uq_discovery_schedule_user"),
        Index("ix_discovery_schedules_due", "enabled", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    cadence: Mapped[str] = mapped_column(String(10), nullable=False, default="weekly")
    hour: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    # Minutes past the hour, so a sweep can sit at 9:15 rather than only on the
    # hour. Defaulted rather than nullable: an existing schedule keeps the exact
    # time it already had.
    minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Monday is 0, matching datetime.weekday(). Ignored for a daily cadence.
    weekday: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="America/New_York"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
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
            "cadence": self.cadence,
            "hour": self.hour,
            "minute": self.minute,
            "weekday": self.weekday,
            "timezone": self.timezone,
            "enabled": self.enabled,
            "next_run_at": self.next_run_at,
        }


class DiscoveryRun(Base):
    """One durable sweep, leased by a worker and resumable after a crash."""

    __tablename__ = "discovery_runs"
    __table_args__ = (
        # A slot is claimed exactly once. This is the guarantee that a restarted
        # producer, or a producer racing another, cannot queue the same sweep
        # twice and deliver a digest the user has already seen.
        UniqueConstraint("schedule_id", "scheduled_for", name="uq_discovery_run_slot"),
        Index("ix_discovery_runs_claimable", "status", "lease_expires_at"),
        Index("ix_discovery_runs_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("discovery_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    # The slot this run belongs to, not the moment work began.
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Outbound requests this run actually spent, so the free-tier claim is
    # checkable after the fact rather than only asserted in advance.
    requests_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The digest is user content, so it is sealed like every other stored text.
    digest_json: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    # Set once, when the digest actually reaches the user. A resumed run that
    # already carries this must never deliver again.
    #
    # Cleared in exactly one case: the channel proved the message never left the
    # machine. That is not a weakening of the write-once rule but the same rule
    # stated precisely — this marks a send that was *committed to*, and a send
    # that provably never happened was never committed to.
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When the next delivery attempt becomes allowed. Null means nothing is
    # waiting: either the digest was delivered, or it was given up on.
    deliver_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The exact text of a pending digest, kept so a retry sends what the first
    # attempt would have sent.
    #
    # Re-rendering later would not be the same message: rendering drops events
    # that have already started, so a digest retried at 9pm would silently lose
    # the evening it was written to announce. Stored sealed, like the digest.
    delivery_message: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
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
            "schedule_id": str(self.schedule_id),
            "user_id": self.user_id,
            "status": self.status,
            "scheduled_for": self.scheduled_for,
            "attempt_count": self.attempt_count,
            "cancel_requested": self.cancel_requested,
            "error_code": self.error_code,
            "requests_spent": self.requests_spent,
            "candidate_count": self.candidate_count,
            "delivered_at": self.delivered_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }
