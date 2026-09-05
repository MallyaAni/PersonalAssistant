"""Agent runs: a job that outlives a turn, as durable leased rows.

Revision ID: 20260905_0019
Revises: 20260905_0018

Four new tables and nothing the running system reads is changed, so this is
safe to apply ahead of the deploy whose gate will start exercising it. A run
is an agent's loop hosted by a worker over these rows: claimed with a lease,
resumed after a restart from its recorded actions, parked while a person
approves a step, cancellable from outside. See backend/models/agent_run.py.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_0019"
down_revision: str | Sequence[str] | None = "20260905_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=False, server_default="default"),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("actor", sa.String(60), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("acceptance", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("budget_seconds", sa.Float(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("max_creates", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("prompt_versions", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_id", sa.String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False, server_default="web"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_agent_runs_claimable", "agent_runs", ["status", "lease_expires_at"])
    op.create_index("ix_agent_runs_user_created", "agent_runs", ["user_id", "created_at"])

    op.create_table(
        "agent_run_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False, server_default="step"),
        sa.Column("arguments", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.String(300), nullable=True),
        sa.Column("creates", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="dispatched"),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("line", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "dispatched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_action_sequence"),
    )
    op.create_index(
        "ix_agent_run_actions_key", "agent_run_actions", ["run_id", "idempotency_key"]
    )

    op.create_table(
        "agent_run_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("tool", sa.String(120), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("target", sa.String(300), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(50), nullable=True),
    )
    op.create_index(
        "ix_agent_run_approvals_run_status", "agent_run_approvals", ["run_id", "status"]
    )

    op.create_table(
        "agent_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index("ix_agent_run_events_run_at", "agent_run_events", ["run_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_events_run_at", table_name="agent_run_events")
    op.drop_table("agent_run_events")
    op.drop_index("ix_agent_run_approvals_run_status", table_name="agent_run_approvals")
    op.drop_table("agent_run_approvals")
    op.drop_index("ix_agent_run_actions_key", table_name="agent_run_actions")
    op.drop_table("agent_run_actions")
    op.drop_index("ix_agent_runs_user_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_claimable", table_name="agent_runs")
    op.drop_table("agent_runs")
