"""Allow at most one active travel destination per user.

Revision ID: 20260802_0022
Revises: 20260802_0021
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0022"
down_revision: str | Sequence[str] | None = "20260802_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enforce the one-active-destination invariant during concurrent requests.
def upgrade() -> None:
    op.create_index(
        "uq_discovery_localities_active_travel",
        "discovery_localities",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_travel_active IS TRUE"),
    )


# Remove the travel-destination uniqueness constraint during rollback.
def downgrade() -> None:
    op.drop_index(
        "uq_discovery_localities_active_travel",
        table_name="discovery_localities",
    )
