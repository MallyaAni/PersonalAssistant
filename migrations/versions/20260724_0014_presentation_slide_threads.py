"""Associate presentation feedback revisions with their selected slide.

Revision ID: 20260724_0014
Revises: 20260724_0013
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0014"
down_revision: str | Sequence[str] | None = "20260724_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the stable slide identity needed to reconstruct per-slide feedback threads.
def upgrade() -> None:
    op.add_column(
        "presentation_revisions",
        sa.Column("target_slide_id", sa.String(length=120), nullable=True),
    )


# Remove per-slide feedback association during an explicit rollback.
def downgrade() -> None:
    op.drop_column("presentation_revisions", "target_slide_id")
