"""Let a trip end by itself.

Being away was a mode: someone typed a destination, and Scout looked there until
they remembered to switch it off. A forgotten one is silent — a weekly digest
about a city the user left in spring still arrives looking like a working
digest, and the finds are all useless.

An expiry makes the default outcome of forgetting the correct one. Nullable, so
a destination set before this migration stays exactly as it was until someone
changes it; the runner treats a null expiry as open-ended, which is the old
behaviour.

Revision ID: 20260803_0031
Revises: 20260802_0030
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0031"
down_revision: str | Sequence[str] | None = "20260802_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the expiry that ends a trip without anyone having to remember to.
def upgrade() -> None:
    op.add_column(
        "discovery_localities",
        sa.Column("travel_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


# Drop the expiry; any destination still active simply becomes open-ended again.
def downgrade() -> None:
    op.drop_column("discovery_localities", "travel_expires_at")
