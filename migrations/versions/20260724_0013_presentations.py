"""Add editable presentations with append-only revisions.

Revision ID: 20260724_0013
Revises: 20260721_0012
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_0013"
down_revision: str | Sequence[str] | None = "20260721_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Create owned decks and immutable revision lineage with opaque PPTX storage.
def upgrade() -> None:
    op.create_table(
        "presentations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_presentations_user_id", "presentations", ["user_id"])
    op.create_index(
        "ix_presentations_conversation_id",
        "presentations",
        ["conversation_id"],
    )
    op.create_index("ix_presentations_trace_id", "presentations", ["trace_id"])
    op.create_table(
        "presentation_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("presentation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("specification_json", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("renderer", sa.String(length=80), nullable=True),
        sa.Column("renderer_version", sa.String(length=40), nullable=True),
        sa.Column("storage_key", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["presentation_revisions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["presentation_id"],
            ["presentations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "presentation_id",
            "revision_number",
            name="uq_presentation_revisions_number",
        ),
    )
    op.create_index(
        "ix_presentation_revisions_presentation_id",
        "presentation_revisions",
        ["presentation_id"],
    )
    op.create_foreign_key(
        "fk_presentations_current_revision",
        "presentations",
        "presentation_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )


# Remove the presentation subsystem tables during an explicit rollback.
def downgrade() -> None:
    op.drop_constraint(
        "fk_presentations_current_revision",
        "presentations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_presentation_revisions_presentation_id",
        table_name="presentation_revisions",
    )
    op.drop_table("presentation_revisions")
    op.drop_index("ix_presentations_trace_id", table_name="presentations")
    op.drop_index("ix_presentations_conversation_id", table_name="presentations")
    op.drop_index("ix_presentations_user_id", table_name="presentations")
    op.drop_table("presentations")
