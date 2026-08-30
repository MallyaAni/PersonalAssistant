"""A scheduled task says whether it is a reminder or a check-in.

Revision ID: 20260830_0013
Revises: 20260828_0012
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0013"
down_revision: str | Sequence[str] | None = "20260828_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows are all reminders the person asked for: the check-in is
    # what is new. server_default fills them in one statement and stays on
    # the column so a row written by anything that does not know about kind
    # is still a reminder rather than a null.
    op.add_column(
        "scheduled_tasks",
        sa.Column(
            "kind",
            sa.String(length=20),
            nullable=False,
            server_default="reminder",
        ),
    )
    # Check-ins are counted per person on every turn that proposes one, and
    # capped at three; the index is what keeps that from reading the whole
    # table each time.
    op.create_index(
        "ix_scheduled_tasks_kind",
        "scheduled_tasks",
        ["user_id", "kind", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_kind", table_name="scheduled_tasks")
    op.drop_column("scheduled_tasks", "kind")
