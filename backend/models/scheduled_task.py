"""Scheduled tasks: a person's own instruction, run later as a turn.

Two tables in the shape Scout's queue proved in production. scheduled_tasks
is the standing instruction with its cadence; scheduled_task_runs is one
row per fired slot, unique per (task, slot) so a run can never fire twice,
leased to one worker at a time so a crashed worker's run is reclaimed and
not duplicated. The instruction and the reply are user text and are
encrypted at rest like every other user text here.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
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


class ScheduledTask(Base):
    """One standing instruction and when it runs."""

    __tablename__ = "scheduled_tasks"
    __table_args__ = (Index("ix_scheduled_tasks_due", "enabled", "next_run_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    instruction: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    cadence: Mapped[str] = mapped_column(String(10), nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    minute: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    on_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # Where the reply goes: the channel the person set the task up from.
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    # Every task owns a conversation thread, so each run's reply sits in the
    # sidebar like any other conversation.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ScheduledTaskRun(Base):
    """One fired slot of a task, from queued to delivered."""

    __tablename__ = "scheduled_task_runs"
    __table_args__ = (
        UniqueConstraint("task_id", "scheduled_for", name="uq_scheduled_task_slot"),
        Index("ix_scheduled_task_runs_claimable", "status", "lease_expires_at"),
        Index("ix_scheduled_task_runs_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    output: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
