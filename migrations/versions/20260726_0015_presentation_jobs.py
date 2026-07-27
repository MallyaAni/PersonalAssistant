"""Add durable presentation generation jobs.

Revision ID: 20260726_0015
Revises: 20260724_0014
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0015"
down_revision: str | Sequence[str] | None = "20260724_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add durable ownership, progress, cancellation, and worker-lease state.
def upgrade() -> None:
    op.create_table(
        "presentation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("presentation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("expected_slide_count", sa.Integer(), nullable=True),
        sa.Column("draft_specification_json", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["presentation_id"], ["presentations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["presentation_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("presentation_id"),
        sa.UniqueConstraint("revision_id"),
    )
    op.create_index(
        op.f("ix_presentation_jobs_presentation_id"),
        "presentation_jobs",
        ["presentation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_presentation_jobs_status"),
        "presentation_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_presentation_jobs_user_id"),
        "presentation_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_presentation_jobs_claim",
        "presentation_jobs",
        ["status", "lease_expires_at", "created_at"],
        unique=False,
    )


# Remove presentation jobs while preserving the older presentation tables.
def downgrade() -> None:
    op.drop_index("ix_presentation_jobs_claim", table_name="presentation_jobs")
    op.drop_index(op.f("ix_presentation_jobs_user_id"), table_name="presentation_jobs")
    op.drop_index(op.f("ix_presentation_jobs_status"), table_name="presentation_jobs")
    op.drop_index(
        op.f("ix_presentation_jobs_presentation_id"),
        table_name="presentation_jobs",
    )
    op.drop_table("presentation_jobs")
