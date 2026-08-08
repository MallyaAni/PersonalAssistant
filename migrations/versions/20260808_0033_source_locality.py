"""Scope a feed to the place it is about.

Familiarity is already per-locality: knowing every trail in Arlington suppresses
nothing in Denver. Sources were not, so a hand-curated page of DC events kept
being read after someone moved or travelled — quietly filling a digest with
things happening several hundred miles away.

Nullable, and null means everywhere. Every source that exists today was added
without a scope and keeps behaving exactly as it does now; only a source
deliberately tied to a place is narrowed.

Revision ID: 20260808_0033
Revises: 20260803_0032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0033"
down_revision: str | Sequence[str] | None = "20260803_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the place a source belongs to, as a digest of the locality label.
def upgrade() -> None:
    op.add_column(
        "discovery_sources",
        # A digest rather than a foreign key, matching how familiarity scopes
        # itself: it survives a place being renamed or removed.
        sa.Column("locality_digest", sa.String(length=64), nullable=True),
    )


# Drop it; every source becomes everywhere again, which is where it started.
def downgrade() -> None:
    op.drop_column("discovery_sources", "locality_digest")
