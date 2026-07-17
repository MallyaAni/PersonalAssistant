"""Scope semantic memory to users and align Nomic embedding dimensions.

Revision ID: 20260716_0002
Revises: 20260716_0001
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260716_0002"
down_revision: str | Sequence[str] | None = "20260716_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    semantic_rows = connection.execute(
        sa.text("SELECT count(*) FROM semantic_memory")
    ).scalar_one()
    if semantic_rows:
        raise RuntimeError(
            "semantic_memory must be empty before changing embeddings from "
            "1536 to 768 dimensions; export or migrate existing vectors first"
        )

    op.add_column(
        "semantic_memory",
        sa.Column("user_id", sa.String(length=50), nullable=False),
    )
    op.create_index(
        "ix_semantic_memory_user_id",
        "semantic_memory",
        ["user_id"],
    )
    op.alter_column(
        "semantic_memory",
        "embedding",
        existing_type=Vector(1536),
        type_=Vector(768),
        existing_nullable=False,
        postgresql_using="embedding::vector(768)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    semantic_rows = connection.execute(
        sa.text("SELECT count(*) FROM semantic_memory")
    ).scalar_one()
    if semantic_rows:
        raise RuntimeError(
            "semantic_memory must be empty before changing embeddings from "
            "768 to 1536 dimensions; export or migrate existing vectors first"
        )

    op.alter_column(
        "semantic_memory",
        "embedding",
        existing_type=Vector(768),
        type_=Vector(1536),
        existing_nullable=False,
        postgresql_using="embedding::vector(1536)",
    )
    op.drop_index("ix_semantic_memory_user_id", table_name="semantic_memory")
    op.drop_column("semantic_memory", "user_id")
