"""Add the ambient discovery interest and locality profile.

Revision ID: 20260801_0016
Revises: 20260726_0015
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0016"
down_revision: str | Sequence[str] | None = "20260726_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Store what the user likes and where they live as sealed text, keyed by a
# digest because a sealed column cannot carry a unique constraint.
def upgrade() -> None:
    op.create_table(
        "discovery_interests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("label_digest", sa.String(length=64), nullable=False),
        sa.Column("strength", sa.Integer(), server_default="2", nullable=False),
        sa.Column(
            "provenance",
            sa.String(length=40),
            server_default="user_explicit",
            nullable=False,
        ),
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
        sa.UniqueConstraint(
            "user_id", "label_digest", name="uq_discovery_interest_label"
        ),
    )
    op.create_index("ix_discovery_interests_user", "discovery_interests", ["user_id"])

    op.create_table(
        "discovery_localities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("label_digest", sa.String(length=64), nullable=False),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("radius_km", sa.Integer(), server_default="25", nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default="America/New_York",
            nullable=False,
        ),
        sa.Column(
            "is_primary", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
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
        sa.UniqueConstraint(
            "user_id", "label_digest", name="uq_discovery_locality_label"
        ),
    )
    op.create_index("ix_discovery_localities_user", "discovery_localities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_discovery_localities_user", table_name="discovery_localities")
    op.drop_table("discovery_localities")
    op.drop_index("ix_discovery_interests_user", table_name="discovery_interests")
    op.drop_table("discovery_interests")
