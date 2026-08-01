"""Add revocable discovery subscribers.

Revision ID: 20260801_0019
Revises: 20260801_0018
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0019"
down_revision: str | Sequence[str] | None = "20260801_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# A subscriber is a revocable permission to deliver, not an account. Consent and
# revocation are columns rather than conventions so a delivery path cannot check
# one and forget the other.
def upgrade() -> None:
    op.create_table(
        "discovery_subscribers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("address_digest", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=60), nullable=True),
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
            "user_id", "channel", "address_digest", name="uq_discovery_subscriber"
        ),
        sa.UniqueConstraint("token", name="uq_discovery_subscriber_token"),
    )
    op.create_index(
        "ix_discovery_subscribers_user", "discovery_subscribers", ["user_id", "active"]
    )


def downgrade() -> None:
    op.drop_index("ix_discovery_subscribers_user", table_name="discovery_subscribers")
    op.drop_table("discovery_subscribers")
