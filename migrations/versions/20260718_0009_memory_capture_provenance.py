"""Add approval and conversation provenance for captured durable memory.

Revision ID: 20260718_0009
Revises: 20260717_0008
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0009"
down_revision: str | Sequence[str] | None = "20260717_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add durable approval and source-request provenance to captured memory.
def upgrade() -> None:
    op.add_column(
        "procedure_memories",
        sa.Column(
            "source_conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "approval_state",
            sa.String(length=20),
            server_default="approved",
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "source_conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "source_trace_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.alter_column(
        "knowledge_documents",
        "approval_state",
        server_default=None,
    )


# Remove capture provenance while preserving the older memory schema.
def downgrade() -> None:
    op.drop_column("knowledge_documents", "source_trace_id")
    op.drop_column("knowledge_documents", "source_conversation_id")
    op.drop_column("knowledge_documents", "approval_state")
    op.drop_column("procedure_memories", "source_conversation_id")
