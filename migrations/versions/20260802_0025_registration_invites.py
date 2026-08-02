"""Add one-time registration invitations.

Revision ID: 20260802_0025
Revises: 20260802_0024
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260802_0025"
down_revision: str | Sequence[str] | None = "20260802_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add expiring one-time invitations without changing any existing account or data.
def upgrade() -> None:
    op.create_table(
        "registration_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by_user_id", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["consumed_by_user_id"],
            ["user_accounts.user_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index(
        "ix_registration_invites_token_digest",
        "registration_invites",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        "ix_registration_invites_expires_at",
        "registration_invites",
        ["expires_at"],
        unique=False,
    )


# Remove only invitation records during an explicitly requested rollback.
def downgrade() -> None:
    op.drop_index(
        "ix_registration_invites_expires_at",
        table_name="registration_invites",
    )
    op.drop_index(
        "ix_registration_invites_token_digest",
        table_name="registration_invites",
    )
    op.drop_table("registration_invites")
