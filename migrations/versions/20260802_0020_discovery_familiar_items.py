"""Add place-scoped familiarity.

Revision ID: 20260802_0020
Revises: 20260801_0019
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260802_0020"
down_revision: str | Sequence[str] | None = "20260801_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Familiarity is scoped by locality digest rather than by a foreign key, so it
# survives a place being renamed or removed and can be looked up without
# decrypting every locality row.
def upgrade() -> None:
    op.create_table(
        "discovery_familiar_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("locality_digest", sa.String(length=64), nullable=False),
        sa.Column("item_digest", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "locality_digest",
            "item_digest",
            name="uq_discovery_familiar_item",
        ),
    )
    op.create_index(
        "ix_discovery_familiar_scope",
        "discovery_familiar_items",
        ["user_id", "locality_digest"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discovery_familiar_scope", table_name="discovery_familiar_items"
    )
    op.drop_table("discovery_familiar_items")
