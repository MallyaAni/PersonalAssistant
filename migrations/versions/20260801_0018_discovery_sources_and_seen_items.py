"""Add discovery feed sources and the seen-item store.

Revision ID: 20260801_0018
Revises: 20260801_0017
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0018"
down_revision: str | Sequence[str] | None = "20260801_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Sources say what a sweep reads; seen items say what it has already accounted
# for. Both identify a sealed value by a digest, because EncryptedText seals
# every value with a fresh nonce and so cannot back a unique constraint.
def upgrade() -> None:
    op.create_table(
        "discovery_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_digest", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_error", sa.String(length=60), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("user_id", "url_digest", name="uq_discovery_source_url"),
    )
    op.create_index(
        "ix_discovery_sources_user", "discovery_sources", ["user_id", "enabled"]
    )

    op.create_table(
        "discovery_seen_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("item_digest", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "item_digest", name="uq_discovery_seen_item"),
    )
    op.create_index(
        "ix_discovery_seen_user_time",
        "discovery_seen_items",
        ["user_id", "first_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_discovery_seen_user_time", table_name="discovery_seen_items")
    op.drop_table("discovery_seen_items")
    op.drop_index("ix_discovery_sources_user", table_name="discovery_sources")
    op.drop_table("discovery_sources")
