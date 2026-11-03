"""Give a seen item the end its payload already recorded.

`discovery_seen_items` stores the whole event as JSON, so `ends_at` was already
present in `payload_json`; the column was not. Novelty and the calendar asked
"is this still live?" and could only compare `starts_at`, so a multi-day
happening vanished from both on its second day. Keeping the end in SQL lets the
query narrow to rows that could still be live before it orders and limits them,
which a Python-side check alone cannot do without reading the whole table.

Backfilled from the payload so rows written before this migration keep the end
they already stated.

Revision ID: 20261031_0022
Revises: 20260924_0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_0022"
down_revision: str | Sequence[str] | None = "20260924_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the end instant, and fill it from the payload every row already carries.
def upgrade() -> None:
    op.add_column(
        "discovery_seen_items",
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Payloads are written by json.dumps in record_seen, so the cast is safe;
    # the LIKE keeps a hand-written non-object row out of the backfill.
    op.execute(
        """
        UPDATE discovery_seen_items
        SET ends_at = (payload_json::jsonb ->> 'ends_at')::timestamptz
        WHERE payload_json LIKE '{%}'
          AND payload_json::jsonb ->> 'ends_at' IS NOT NULL
        """
    )


# Remove the column only during an explicitly authorized schema rollback.
def downgrade() -> None:
    op.drop_column("discovery_seen_items", "ends_at")
