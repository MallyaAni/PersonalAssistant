"""The change log remembers which conversation a change was made in.

Revision ID: 20260828_0012
Revises: 20260828_0011
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260828_0012"
down_revision: str | Sequence[str] | None = "20260828_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduled_task_changes",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_scheduled_task_changes_conversation",
        "scheduled_task_changes",
        ["user_id", "conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_task_changes_conversation", table_name="scheduled_task_changes")
    op.drop_column("scheduled_task_changes", "conversation_id")
