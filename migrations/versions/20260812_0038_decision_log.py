"""Record what the ranker considered, not only what it sent.

A reaction on a bubble labels one item. It cannot say which interest matched it,
how strongly it scored, or what it was chosen over — and the rejected candidates,
the only evidence a rejection was wrong, were never written down at all.

This holds one decision per run, in the shape off-policy evaluation expects, so
the reactions being collected now are worth something to a ranker later instead
of being a pile of thumbs with no context.

Sealed like `digest_json` beside it: what someone was offered is as personal as
what they liked about it.

Purely additive, and nullable, so every run recorded before today simply has no
decision on file — which is the truth.

Revision ID: 20260812_0038
Revises: 20260811_0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0038"
down_revision: str | Sequence[str] | None = "20260811_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the sealed decision record.
def upgrade() -> None:
    op.add_column(
        "discovery_runs",
        sa.Column("decision_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discovery_runs", "decision_json")
