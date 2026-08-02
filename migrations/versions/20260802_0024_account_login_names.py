"""Separate login names from stable owned user IDs.

Revision ID: 20260802_0024
Revises: 20260802_0023
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0024"
down_revision: str | Sequence[str] | None = "20260802_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add unique login names while preserving every account's stable owner ID.
def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("username", sa.String(length=50), nullable=True),
    )
    op.execute("UPDATE user_accounts SET username = lower(user_id)")
    op.alter_column("user_accounts", "username", nullable=False)
    op.create_index(
        "ix_user_accounts_username",
        "user_accounts",
        ["username"],
        unique=True,
    )


# Remove only the login alias during an explicitly requested rollback.
def downgrade() -> None:
    op.drop_index("ix_user_accounts_username", table_name="user_accounts")
    op.drop_column("user_accounts", "username")
