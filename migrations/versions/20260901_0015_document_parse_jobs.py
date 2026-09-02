"""Durable queue for documents waiting on the parser.

Revision ID: 20260901_0015
Revises: 20260830_0014

Docling runs on the desktop GPU, which is not always on. A document sent
while it is off is kept here - bytes and all - and parsed into knowledge when
the parser is reachable again, so nothing a person hands the assistant is
lost to timing (docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md, stage 2).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0015"
down_revision: str | Sequence[str] | None = "20260830_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_parse_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("media_type", sa.String(length=200), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_document_parse_jobs_status", "document_parse_jobs", ["status", "created_at"])
    op.create_index("ix_document_parse_jobs_user", "document_parse_jobs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_document_parse_jobs_user", table_name="document_parse_jobs")
    op.drop_index("ix_document_parse_jobs_status", table_name="document_parse_jobs")
    op.drop_table("document_parse_jobs")
