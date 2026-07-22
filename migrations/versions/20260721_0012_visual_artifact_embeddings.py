"""Add aligned image embeddings to visual artifacts.

Image vectors live in their own column rather than in semantic_memory. The
vision encoder is aligned to the text embedder, so both spaces share 768
dimensions and cosine ordering is meaningful within each. Cross-modal
similarity magnitudes are not comparable to text-text ones (the modality gap),
so image results must be ranked and thresholded separately and merged by rank.

Revision ID: 20260721_0012
Revises: 20260718_0011
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0012"
down_revision: str | Sequence[str] | None = "20260718_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Store one aligned image vector per artifact with its producing model recorded.
def upgrade() -> None:
    op.add_column(
        "visual_artifacts",
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.Vector(dim=768),
            nullable=True,
        ),
    )
    # Recording the model makes stale vectors identifiable when the encoder
    # changes, mirroring how semantic_memory tracks embedding provenance.
    op.add_column(
        "visual_artifacts",
        sa.Column("embedding_model", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "visual_artifacts",
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_visual_artifacts_embedding_hnsw",
        "visual_artifacts",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_visual_artifacts_embedding_hnsw", table_name="visual_artifacts")
    op.drop_column("visual_artifacts", "embedding_dimension")
    op.drop_column("visual_artifacts", "embedding_model")
    op.drop_column("visual_artifacts", "embedding")
