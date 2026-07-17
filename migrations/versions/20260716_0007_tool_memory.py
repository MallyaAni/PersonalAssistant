"""Add safe MCP tool descriptor and user-tool memory tables.

Revision ID: 20260716_0007
Revises: 20260716_0006
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0007"
down_revision: str | Sequence[str] | None = "20260716_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_descriptors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("server_id", sa.String(length=200), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_purpose", sa.Text(), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("tool_version", sa.String(length=100), nullable=False),
        sa.Column("risk_classification", sa.String(length=30), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint(
            "user_id",
            "server_id",
            "tool_name",
            "schema_fingerprint",
            name="uq_tool_descriptor_identity",
        ),
    )
    op.create_index("ix_tool_descriptors_user_id", "tool_descriptors", ["user_id"])
    op.create_index(
        "ix_tool_descriptor_active_lookup",
        "tool_descriptors",
        ["user_id", "server_id", "active"],
    )
    op.create_table(
        "tool_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("server_id", sa.String(length=200), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("preference_key", sa.String(length=50), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("approval_state", sa.String(length=20), nullable=False),
        sa.Column("source_trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "user_id",
            "server_id",
            "tool_name",
            "preference_key",
            name="uq_tool_preference_key",
        ),
    )
    op.create_index("ix_tool_preferences_user_id", "tool_preferences", ["user_id"])
    op.create_index(
        "ix_tool_preferences_expires_at", "tool_preferences", ["expires_at"]
    )
    op.create_table(
        "tool_usage_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("server_id", sa.String(length=200), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("outcome_category", sa.String(length=30), nullable=False),
        sa.Column("source_trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extra_data", postgresql.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_usage_outcomes_user_id", "tool_usage_outcomes", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tool_usage_outcomes_user_id", table_name="tool_usage_outcomes")
    op.drop_table("tool_usage_outcomes")
    op.drop_index("ix_tool_preferences_expires_at", table_name="tool_preferences")
    op.drop_index("ix_tool_preferences_user_id", table_name="tool_preferences")
    op.drop_table("tool_preferences")
    op.drop_index("ix_tool_descriptor_active_lookup", table_name="tool_descriptors")
    op.drop_index("ix_tool_descriptors_user_id", table_name="tool_descriptors")
    op.drop_table("tool_descriptors")
