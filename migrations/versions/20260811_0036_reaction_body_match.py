"""Match a reaction by what the message said, not by Apple's identifier.

Identifiers failed four distinct ways against a real Mac: not captured at all,
captured but pointing at the wrong message, pointing at the copy the phone holds
rather than the one this machine sent, and pointing at a row this machine never
kept. The lookup was guessing at a handle Apple never gives back at send time.

The body is the one thing we control end to end — every bubble's text is
composed here — and it survives all four failures, because it identifies the
message rather than the row. A short prefix is enough to recognise one bubble
among a week of them, and it is sealed for the same reason the label is: what a
digest said is what someone is interested in.

Purely additive. Existing rows keep their identifiers and simply never match.

Revision ID: 20260811_0036
Revises: 20260810_0035
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0036"
down_revision: str | Sequence[str] | None = "20260810_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the sealed body prefix a reaction is matched on.
def upgrade() -> None:
    op.add_column(
        "discovery_sent_finds",
        sa.Column("body_prefix", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discovery_sent_finds", "body_prefix")
