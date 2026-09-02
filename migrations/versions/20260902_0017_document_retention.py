"""A document knows the last date it is about, and when it was archived.

Revision ID: 20260902_0017
Revises: 20260902_0016

Retention for document knowledge (docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md,
"Retention"): the digest step reads the last date a document is about; a
grace period after it the document is archived - kept, reachable when
nothing current answers or when it is pinned, but out of default retrieval.
The file itself is never deleted on a date.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0017"
down_revision: str | Sequence[str] | None = "20260902_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("about_until", sa.Date(), nullable=True))
    op.add_column("knowledge_documents", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_knowledge_documents_about_until", "knowledge_documents", ["about_until"])


def downgrade() -> None:
    op.execute("UPDATE knowledge_documents SET status = 'active' WHERE status = 'archived'")
    op.drop_index("ix_knowledge_documents_about_until", table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "archived_at")
    op.drop_column("knowledge_documents", "about_until")
