"""Record what was sent as its own message, so a reaction has something to land on.

Scout had no positive signal at all. Dismissal says "I already know this", which
is a different thing from "I would not have wanted this", and neither says "more
like that one". Nothing in the loop could learn what someone actually liked.

A digest sent as one message can only be judged as a whole. Sent as a bubble per
find, each one carries a tapback — the reaction Messages already offers on any
bubble — and that is a per-find opinion arriving on the same channel the digest
does, with no app to open and nothing to click.

This table is the join: one row per bubble, holding the identity of the find and
Apple's message GUID, with the reaction written back onto it when the bridge
reads one. Purely additive; nothing existing reads or writes it.

Revision ID: 20260810_0035
Revises: 20260808_0034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260810_0035"
down_revision: str | Sequence[str] | None = "20260808_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Create the bubble-to-reaction table and the two indexes that read it.
def upgrade() -> None:
    op.create_table(
        "discovery_sent_finds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("subscriber_id", UUID(as_uuid=True), nullable=True),
        sa.Column("item_digest", sa.String(length=64), nullable=True),
        # Sealed in the application, matching every other column that holds
        # something a find said about someone's interests.
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("locality", sa.String(length=120), nullable=True),
        sa.Column("message_guid", sa.String(length=120), nullable=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reaction", sa.String(length=12), nullable=True),
        sa.Column("reacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("message_guid", name="uq_discovery_sent_find_guid"),
    )
    op.create_index(
        "ix_discovery_sent_find_pending",
        "discovery_sent_finds",
        ["reacted_at", "sent_at"],
    )
    op.create_index(
        "ix_discovery_sent_find_user",
        "discovery_sent_finds",
        ["user_id", "item_digest"],
    )


def downgrade() -> None:
    op.drop_index("ix_discovery_sent_find_user", table_name="discovery_sent_finds")
    op.drop_index("ix_discovery_sent_find_pending", table_name="discovery_sent_finds")
    op.drop_table("discovery_sent_finds")
