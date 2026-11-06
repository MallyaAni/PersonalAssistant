"""Tell the conversation when a queued deck is ready, on its own channel.

A deck is built minutes after the turn that asked for it, so the answer had
nowhere to land: the person had to keep the Presentations panel open. The job
now remembers the channel it was queued from and whether it has already told
anyone, so the worker can write one assistant-only turn and send the same
sentence where the request came from - once, even if it crashes and retries.

Additive and nullable; jobs queued before this keep the old silent behaviour.

Revision ID: 20261104_0027
Revises: 20261104_0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0027"
down_revision: str | Sequence[str] | None = "20261104_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "presentation_jobs", sa.Column("channel", sa.String(50), nullable=True)
    )
    op.add_column(
        "presentation_jobs",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("presentation_jobs", "notified_at")
    op.drop_column("presentation_jobs", "channel")
