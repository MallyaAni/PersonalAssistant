"""Let a digest survive a sleeping Mac.

Delivery had exactly one attempt. When the bridge was unreachable at the moment
a sweep finished — a laptop asleep, the lid shut, the machine off the network —
the digest was lost, and the run still recorded itself as a clean success. The
failure was visible only on the subscriber row, as `last_error`, which is why a
missing 5:30pm digest looked from the run table like a delivery that worked.

Retrying a send is normally unsafe: a connection dropped mid-request does not
say whether the message went before the reply was lost. So the retry added here
is gated on the one case that carries no doubt — a connection that was never
established, where nothing reached the bridge at all.

Three columns, all nullable or defaulted, so existing runs are unaffected: they
have no pending delivery and never acquire one.

Revision ID: 20260808_0034
Revises: 20260808_0033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0034"
down_revision: str | Sequence[str] | None = "20260808_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the state a pending redelivery needs: when, how often, and what to send.
def upgrade() -> None:
    op.add_column(
        "discovery_runs",
        sa.Column("deliver_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "discovery_runs",
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "discovery_runs",
        # Sealed, like digest_json: it is the same user content in rendered form.
        sa.Column("delivery_message", sa.Text(), nullable=True),
    )
    # The worker asks "what is due to be redelivered?" on every idle tick, so
    # that question gets an index rather than a scan of every run ever made.
    op.create_index(
        "ix_discovery_runs_deliver_after",
        "discovery_runs",
        ["deliver_after"],
        postgresql_where=sa.text("deliver_after IS NOT NULL"),
    )


# Drop them; delivery becomes single-attempt again, which is where it started.
def downgrade() -> None:
    op.drop_index("ix_discovery_runs_deliver_after", table_name="discovery_runs")
    op.drop_column("discovery_runs", "delivery_message")
    op.drop_column("discovery_runs", "delivery_attempts")
    op.drop_column("discovery_runs", "deliver_after")
