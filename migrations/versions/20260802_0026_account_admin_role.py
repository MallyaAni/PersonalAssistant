"""Add an administrator role to accounts.

Revision ID: 20260802_0026
Revises: 20260802_0025
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0026"
down_revision: str | Sequence[str] | None = "20260802_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the role, defaulting to false, then promote the oldest existing account.
#
# Defaulting to false matters: every account created before this migration and
# every account created after it is an ordinary guest unless someone says
# otherwise. Promoting the oldest account is what keeps the operator able to
# administer their own machine after the upgrade — without it, an existing
# deployment would have no administrator at all.
def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column(
            "is_admin", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.execute(
        """
        UPDATE user_accounts
        SET is_admin = TRUE
        WHERE user_id = (
            SELECT user_id FROM user_accounts ORDER BY created_at ASC LIMIT 1
        )
        """
    )


# Remove the role during rollback.
def downgrade() -> None:
    op.drop_column("user_accounts", "is_admin")
