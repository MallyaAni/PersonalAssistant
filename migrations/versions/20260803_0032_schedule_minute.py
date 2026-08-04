"""Let a sweep sit at 9:15 rather than only on the hour.

The slot was built from the hour alone, so every schedule fired at :00. Nothing
about the loop requires that — the identity of a slot is its instant, and adding
minutes narrows it without changing how exactly-once works.

Defaulted to 0 rather than nullable, so every schedule that already exists keeps
firing at precisely the time it fired before this ran.

Revision ID: 20260803_0032
Revises: 20260803_0031
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0032"
down_revision: str | Sequence[str] | None = "20260803_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the minute a scheduled sweep starts at.
def upgrade() -> None:
    op.add_column(
        "discovery_schedules",
        sa.Column("minute", sa.Integer(), nullable=False, server_default="0"),
    )


# Drop it; every schedule returns to firing on the hour.
def downgrade() -> None:
    op.drop_column("discovery_schedules", "minute")
