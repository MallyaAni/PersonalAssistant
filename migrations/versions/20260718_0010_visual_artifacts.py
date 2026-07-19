"""Add user-scoped visual artifact lifecycle storage.

Revision ID: 20260718_0010
Revises: 20260718_0009
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0010"
down_revision: str | Sequence[str] | None = "20260718_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Create the scoped lifecycle table used by generated visual artifacts.
def upgrade() -> None:
    op.create_table(
        "visual_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("source_format", sa.String(length=30), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("extra_data", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("kind IN ('diagram')", name="ck_visual_artifacts_kind"),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')",
            name="ck_visual_artifacts_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_visual_artifacts_conversation_id",
        "visual_artifacts",
        ["conversation_id"],
    )
    op.create_index("ix_visual_artifacts_trace_id", "visual_artifacts", ["trace_id"])
    op.create_index(
        "ix_visual_artifacts_user_conversation_created",
        "visual_artifacts",
        ["user_id", "conversation_id", "created_at"],
    )
    op.create_index("ix_visual_artifacts_user_id", "visual_artifacts", ["user_id"])


# Remove visual artifact storage when rolling back this capability.
def downgrade() -> None:
    op.drop_index("ix_visual_artifacts_user_id", table_name="visual_artifacts")
    op.drop_index(
        "ix_visual_artifacts_user_conversation_created",
        table_name="visual_artifacts",
    )
    op.drop_index("ix_visual_artifacts_trace_id", table_name="visual_artifacts")
    op.drop_index("ix_visual_artifacts_conversation_id", table_name="visual_artifacts")
    op.drop_table("visual_artifacts")
