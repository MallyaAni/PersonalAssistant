"""Make an artifact's parent a column, so provenance survives retrieval.

A derivative recorded its parent inside `extra_data`, which meant nothing could
join on it. Recall therefore reconstructed lineage from whatever else happened to
match the same query: edit a photograph, ask about it later, and the upload it
came from was collapsed out of the results as a near-duplicate, taking the only
record of what the user had actually supplied. The assistant then described the
edited hat as the one in "the picture you uploaded".

Reconstructing a relationship from a result set can only ever be as good as the
result set. As a column it is a relationship: one indexed recursive query
resolves the whole chain for every match, whether or not any ancestor was
retrieved, and it is modality-neutral — the same edge serves a cropped video or
a revised document the day those exist.

The JSON key keeps being written and is left in place on old rows. This is
purely additive; nothing is dropped and nothing is rewritten.

Backfill only links a parent that still exists, so the foreign key is valid the
moment it is created. Rows whose parent was deleted keep the JSON key and get a
null column, which is the truth: that lineage is gone.

Revision ID: 20260811_0037
Revises: 20260811_0036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0037"
down_revision: str | Sequence[str] | None = "20260811_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Only a well-formed identifier is cast. The writer used `str(id or "")`, so an
# empty string is a value this column has to survive meeting.
_UUID_SHAPED = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    "-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# Add the parent edge, link the history that is still intact, then constrain it.
def upgrade() -> None:
    op.add_column(
        "visual_artifacts",
        sa.Column("parent_artifact_id", sa.dialects.postgresql.UUID(as_uuid=True)),
    )
    op.execute(
        sa.text(
            """
            UPDATE visual_artifacts AS child
               SET parent_artifact_id = parent.id
              FROM visual_artifacts AS parent
             WHERE child.extra_data->>'parent_artifact_id' ~ :shape
               AND parent.id = (child.extra_data->>'parent_artifact_id')::uuid
               AND parent.user_id = child.user_id
            """
        ).bindparams(shape=_UUID_SHAPED)
    )
    op.create_index(
        "ix_visual_artifacts_parent",
        "visual_artifacts",
        ["parent_artifact_id"],
    )
    # A deleted parent must not block deleting it, and must not leave a link to
    # a row that is gone: the lineage is genuinely lost, and says so.
    op.create_foreign_key(
        "fk_visual_artifacts_parent",
        "visual_artifacts",
        "visual_artifacts",
        ["parent_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_visual_artifacts_parent", "visual_artifacts", type_="foreignkey"
    )
    op.drop_index("ix_visual_artifacts_parent", table_name="visual_artifacts")
    op.drop_column("visual_artifacts", "parent_artifact_id")
