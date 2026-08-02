"""Add durable scheduled discovery runs.

Revision ID: 20260801_0017
Revises: 20260801_0016
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0017"
down_revision: str | Sequence[str] | None = "20260801_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# A schedule states when sweeps happen; a run is one durable, leased instance of
# a sweep. The slot uniqueness on runs is what makes a sweep exactly-once.
def upgrade() -> None:
    op.create_table(
        "discovery_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column(
            "cadence", sa.String(length=10), server_default="weekly", nullable=False
        ),
        sa.Column("hour", sa.Integer(), server_default="9", nullable=False),
        sa.Column("weekday", sa.Integer(), server_default="4", nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="America/New_York",
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_discovery_schedule_user"),
    )
    op.create_index(
        "ix_discovery_schedules_due",
        "discovery_schedules",
        ["enabled", "next_run_at"],
    )

    op.create_table(
        "discovery_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="queued", nullable=False
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("requests_spent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("candidate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("digest_json", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["discovery_schedules.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "schedule_id", "scheduled_for", name="uq_discovery_run_slot"
        ),
    )
    op.create_index(
        "ix_discovery_runs_claimable",
        "discovery_runs",
        ["status", "lease_expires_at"],
    )
    op.create_index("ix_discovery_runs_user", "discovery_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_discovery_runs_user", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_claimable", table_name="discovery_runs")
    op.drop_table("discovery_runs")
    op.drop_index("ix_discovery_schedules_due", table_name="discovery_schedules")
    op.drop_table("discovery_schedules")
