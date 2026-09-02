"""A written document is a visual artifact of kind 'document'.

Revision ID: 20260902_0016
Revises: 20260901_0015

The assistant now writes PDFs and Word files (docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md,
stage 6). They live in the same artifact store as pictures and diagrams -
bytes under an opaque key, hash and size on the row, served through the
owned-artifact route both surfaces already use - so the only change is the
kind the check constraint admits.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260902_0016"
down_revision: str | Sequence[str] | None = "20260901_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_BEFORE = "kind IN ('diagram', 'generated_image', 'uploaded_image')"
_KINDS_AFTER = "kind IN ('diagram', 'generated_image', 'uploaded_image', 'document')"


def upgrade() -> None:
    op.drop_constraint("ck_visual_artifacts_kind", "visual_artifacts", type_="check")
    op.create_check_constraint("ck_visual_artifacts_kind", "visual_artifacts", _KINDS_AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM visual_artifacts WHERE kind = 'document'")
    op.drop_constraint("ck_visual_artifacts_kind", "visual_artifacts", type_="check")
    op.create_check_constraint("ck_visual_artifacts_kind", "visual_artifacts", _KINDS_BEFORE)
