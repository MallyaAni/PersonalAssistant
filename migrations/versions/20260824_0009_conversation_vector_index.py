"""An ANN index on the transcript store, built before it is big.

Recall - passive on every turn, active when the model searches its history -
computed cosine distance against every one of a user's embedded turns through
a plain btree on user_id. Invisible at a few hundred rows and a growing
per-turn tax at tens of thousands, on the same box as the router. HNSW makes
it a graph probe instead of a scan, and building it now costs seconds where
building it under a large table is the slow, memory-hungry version. Same
pattern as the four agent-memory embedding indexes.

Revision ID: 20260824_0009
Revises: 20260824_0008
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260824_0009"
down_revision: str | Sequence[str] | None = "20260824_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_embedding_hnsw",
        "conversations",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_embedding_hnsw", table_name="conversations")
