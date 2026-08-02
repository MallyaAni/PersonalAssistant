"""Add access requests, last-active tracking, and a per-account search limit.

Revision ID: 20260802_0028
Revises: 20260802_0027
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260802_0028"
down_revision: str | Sequence[str] | None = "20260802_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Invert the invitation flow, and give the operator what they need to run it.
#
# Minting a code blind means deciding who gets access before knowing who is
# asking. A request carries the details first and the operator decides after, so
# the approval is informed. Only the digest of the requester's token is stored,
# like every other secret here.
def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("contact", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("invite_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_access_request_token"),
    )
    op.create_index("ix_access_requests_status", "access_requests", ["status"])

    # Monitoring: when an account was last seen, so the operator can tell an
    # active guest from a dormant one without reading logs.
    op.add_column(
        "user_accounts",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Null means "use the deployment default". A per-account override lets the
    # operator give one person more or throttle a runaway without changing the
    # ceiling for everyone.
    op.add_column(
        "user_accounts",
        sa.Column("search_monthly_limit", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_accounts", "search_monthly_limit")
    op.drop_column("user_accounts", "last_seen_at")
    op.drop_index("ix_access_requests_status", table_name="access_requests")
    op.drop_table("access_requests")
