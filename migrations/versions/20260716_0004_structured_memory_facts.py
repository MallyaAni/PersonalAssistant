"""Add structured, versioned durable memory facts.

Revision ID: 20260716_0004
Revises: 20260716_0003
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0004"
down_revision: str | Sequence[str] | None = "20260716_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("fact_type", sa.String(length=50), nullable=False),
        sa.Column("fact_key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("approval_state", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column(
            "source_conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("source_trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("embedding_model", sa.String(length=200), nullable=True),
        sa.Column("embedding_version", sa.String(length=100), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
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
        sa.Column("extra_data", postgresql.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["memory_facts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "fact_key",
            "version",
            name="uq_memory_facts_user_key_version",
        ),
    )
    op.create_index("ix_memory_facts_user_id", "memory_facts", ["user_id"])
    op.create_index(
        "ix_memory_facts_user_key_state",
        "memory_facts",
        ["user_id", "fact_key", "approval_state"],
    )
    op.create_index("ix_memory_facts_expires_at", "memory_facts", ["expires_at"])

    op.execute("""
        INSERT INTO memory_facts (
            id, user_id, fact_type, fact_key, value, normalized_value,
            approval_state, confidence, purpose, version, extra_data
        )
        SELECT
            gen_random_uuid(), user_id, 'profile', 'preferred_name', name,
            lower(trim(name)), 'approved', 1.0, 'personalization', 1,
            '{"source":"legacy_profile_backfill"}'::json
        FROM user_profiles
        WHERE name IS NOT NULL AND trim(name) <> ''
        """)


def downgrade() -> None:
    op.drop_index("ix_memory_facts_expires_at", table_name="memory_facts")
    op.drop_index("ix_memory_facts_user_key_state", table_name="memory_facts")
    op.drop_index("ix_memory_facts_user_id", table_name="memory_facts")
    op.drop_table("memory_facts")
