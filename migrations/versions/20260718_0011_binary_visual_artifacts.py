"""Add generated and uploaded binary visual artifacts.

Revision ID: 20260718_0011
Revises: 20260718_0010
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260718_0011"
down_revision: str | Sequence[str] | None = "20260718_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Extend visual artifacts with opaque binary storage and integrity metadata.
def upgrade() -> None:
    op.drop_constraint(
        "ck_visual_artifacts_kind",
        "visual_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_visual_artifacts_kind",
        "visual_artifacts",
        "kind IN ('diagram', 'generated_image', 'uploaded_image')",
    )
    op.add_column(
        "visual_artifacts",
        sa.Column("storage_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "visual_artifacts",
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "visual_artifacts",
        sa.Column("sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "visual_artifacts",
        sa.Column("width", sa.Integer(), nullable=True),
    )
    op.add_column(
        "visual_artifacts",
        sa.Column("height", sa.Integer(), nullable=True),
    )


# Restore the diagram-only artifact schema during an explicit rollback.
def downgrade() -> None:
    op.execute("DELETE FROM visual_artifacts WHERE kind != 'diagram'")
    op.drop_column("visual_artifacts", "height")
    op.drop_column("visual_artifacts", "width")
    op.drop_column("visual_artifacts", "sha256")
    op.drop_column("visual_artifacts", "byte_size")
    op.drop_column("visual_artifacts", "storage_key")
    op.drop_constraint(
        "ck_visual_artifacts_kind",
        "visual_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_visual_artifacts_kind",
        "visual_artifacts",
        "kind IN ('diagram')",
    )
