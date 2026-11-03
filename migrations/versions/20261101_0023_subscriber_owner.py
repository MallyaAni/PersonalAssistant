"""Record which subscription belongs to the account holder.

The owner was inferred as the earliest subscription, on the convention that a
person subscribes their own phone before adding anyone else. The schema had no
owner flag to ask, so the inference was the best available - but it inverted
the moment the owner revoked and subscribed again after a guest had been added:
the guest's row became the earliest, and from then on a guest's tapback was
read as the owner's verdict while the owner's own was discarded. The same
inference decided whether a digest could carry prose written from the owner's
reactions, so in that state a guest could receive it.

Ownership is recorded now, by the one path that knows it: the account asking to
be subscribed. The backfill keeps the old convention for rows that already
exist - the earliest subscription of each account is marked - so nothing
changes for anyone whose owner is still the earliest row.

Revision ID: 20261101_0023
Revises: 20261031_0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0023"
down_revision: str | Sequence[str] | None = "20261031_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the flag, mark the earliest subscription of each account, then make the
# one-per-account rule a constraint rather than a convention.
def upgrade() -> None:
    op.add_column(
        "discovery_subscribers",
        sa.Column(
            "is_owner",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # DISTINCT ON with the same ordering the old inference used, so the
    # backfilled owner is the row that inference would have chosen. Ties on
    # created_at break by id, which is arbitrary but stable.
    op.execute(
        """
        UPDATE discovery_subscribers AS subscriber
        SET is_owner = true
        FROM (
            SELECT DISTINCT ON (user_id) id
            FROM discovery_subscribers
            ORDER BY user_id, created_at ASC, id ASC
        ) AS earliest
        WHERE subscriber.id = earliest.id
        """
    )
    op.create_index(
        "uq_discovery_subscriber_owner",
        "discovery_subscribers",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_owner"),
    )


# Remove the flag only during an explicitly authorized schema rollback. The
# index goes first: dropping the column would drop it anyway, but naming it
# keeps the rollback readable in a log.
def downgrade() -> None:
    op.drop_index(
        "uq_discovery_subscriber_owner",
        table_name="discovery_subscribers",
        postgresql_where=sa.text("is_owner"),
    )
    op.drop_column("discovery_subscribers", "is_owner")
