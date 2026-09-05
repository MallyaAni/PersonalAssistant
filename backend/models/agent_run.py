"""A run: an agent's job that outlives a turn, as durable rows.

A chat turn's loop lives in one process for a few seconds. A run is the same
loop - decide, act, observe, decide - hosted by a worker over these rows, so
it survives a restart, waits for a person when a step needs approval, and
can be cancelled from outside. The shape is the one the scheduled-task and
discovery queues proved: a row claimed with a lease, a lapsed lease reclaimed
by the next worker, one closing write.

Every effect the run has on the world is an action row with the tool, the
arguments, the natural key the tool declares, and what happened. That is
what makes a resume safe: a step whose row says it succeeded is not redone,
and one whose row says it was dispatched and never heard from is reconciled
before anything that would repeat it.

`tenant_id` is carried from the first migration and single-valued today, so
a later multi-tenant split is a data migration rather than a rewrite.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText

RUN_STATUSES = ("queued", "running", "waiting_approval", "completed", "failed", "cancelled")
ACTION_STATUSES = ("dispatched", "succeeded", "failed", "refused", "unknown")
APPROVAL_STATUSES = ("pending", "granted", "denied", "expired", "consumed")


class AgentRun(Base):
    """One job under one person's authority, and how far it has got."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_claimable", "status", "lease_expires_at"),
        Index("ix_agent_runs_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(
        String(50), nullable=False, default="default", server_default="default"
    )
    # The principal: whose authority the run acts under.
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # The actor: which agent or channel is acting for them.
    actor: Mapped[str] = mapped_column(String(60), nullable=False)
    # Which world runs it: the agent's kind, looked up in the worker's registry.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    objective: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    # Acceptance criteria, as JSON; completion is evidence against these.
    acceptance: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    budget_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_creates: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    prompt_versions: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    # What the run produced, as JSON: the evidence the verifier found, the
    # summary for the person.
    result: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AgentRunAction(Base):
    """One step a run took: the call, its key, and what happened."""

    __tablename__ = "agent_run_actions"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_action_sequence"),
        Index("ix_agent_run_actions_key", "run_id", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(120), nullable=False)
    # What the step belongs to for the reply: task, search, tool, ...
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="step")
    arguments: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="{}")
    idempotency_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    creates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="dispatched")
    outcome: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    # The line the next decision reads about this step.
    line: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentRunApproval(Base):
    """A person's yes or no to one exact action, with an expiry."""

    __tablename__ = "agent_run_approvals"
    __table_args__ = (Index("ix_agent_run_approvals_run_status", "run_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    tool: Mapped[str] = mapped_column(String(120), nullable=False)
    # The approval is bound to exactly these arguments: a different call needs
    # a different yes.
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # What the person sees when asked.
    summary: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(50), nullable=True)


class AgentRunEvent(Base):
    """One thing that happened to a run, in order: the audit trail."""

    __tablename__ = "agent_run_events"
    __table_args__ = (Index("ix_agent_run_events_run_at", "run_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
