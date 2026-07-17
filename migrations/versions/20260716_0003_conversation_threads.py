"""Add a stable conversation ID distinct from per-request trace IDs.

Revision ID: 20260716_0003
Revises: 20260716_0002
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0003"
down_revision: str | Sequence[str] | None = "20260716_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute("UPDATE conversations SET conversation_id = id")
    op.alter_column("conversations", "conversation_id", nullable=False)
    op.create_index(
        "ix_conversations_conversation_id",
        "conversations",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_conversation_id", table_name="conversations")
    op.drop_column("conversations", "conversation_id")
