"""Add an active travel destination without changing the home locality.

Revision ID: 20260802_0021
Revises: 20260802_0020
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0021"
down_revision: str | Sequence[str] | None = "20260802_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the reversible travel-mode flag with existing localities remaining inactive.
def upgrade() -> None:
    op.add_column(
        "discovery_localities",
        sa.Column(
            "is_travel_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


# Remove the travel-mode flag when rolling back this schema revision.
def downgrade() -> None:
    op.drop_column("discovery_localities", "is_travel_active")
