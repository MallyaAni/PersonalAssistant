"""Per-account daily search limit.

A month is the billing period but the wrong unit to protect. One account looping
on the first of the month can spend a whole monthly allowance in an afternoon,
and the monthly ceiling only notices once it is already gone. The daily bound
caps what any single bad day can cost and refills tomorrow.

Null means "use the deployment default", never "unlimited" — an unbounded
account is exactly what these columns exist to prevent.

Revision ID: 20260802_0029
Revises: 20260802_0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0029"
down_revision: str | Sequence[str] | None = "20260802_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("search_daily_limit", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_accounts", "search_daily_limit")
