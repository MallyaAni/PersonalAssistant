"""Add explicit memory retention and embedding metadata.

Revision ID: 20260716_0005
Revises: 20260716_0004
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0005"
down_revision: str | Sequence[str] | None = "20260716_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "episodic_memory",
        sa.Column(
            "purpose",
            sa.String(length=100),
            server_default="user_explicit",
            nullable=False,
        ),
    )
    op.add_column(
        "episodic_memory",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_episodic_memory_expires_at", "episodic_memory", ["expires_at"])
    op.add_column(
        "semantic_memory",
        sa.Column(
            "purpose",
            sa.String(length=100),
            server_default="user_explicit",
            nullable=False,
        ),
    )
    op.add_column(
        "semantic_memory",
        sa.Column(
            "embedding_model",
            sa.String(length=200),
            server_default="legacy_unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "semantic_memory",
        sa.Column(
            "embedding_version",
            sa.String(length=100),
            server_default="legacy_unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "semantic_memory",
        sa.Column(
            "embedding_dimension", sa.Integer(), server_default="768", nullable=False
        ),
    )
    op.add_column(
        "semantic_memory",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_semantic_memory_expires_at", "semantic_memory", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_semantic_memory_expires_at", table_name="semantic_memory")
    op.drop_column("semantic_memory", "expires_at")
    op.drop_column("semantic_memory", "embedding_dimension")
    op.drop_column("semantic_memory", "embedding_version")
    op.drop_column("semantic_memory", "embedding_model")
    op.drop_column("semantic_memory", "purpose")
    op.drop_index("ix_episodic_memory_expires_at", table_name="episodic_memory")
    op.drop_column("episodic_memory", "expires_at")
    op.drop_column("episodic_memory", "purpose")
