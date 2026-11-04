"""Record which turn wrote a change, so "undo that" picks what was asked for.

A turn can write more than one change row. "Scout, remind us to stretch at
5am tomorrow" records the reminder during the tool step, then the memory
classifier saves a note about it after the reply - so the memory save is the
newer row. "Undo that" then took back the note and left the reminder armed
(found by the group undo journey on the live sweep, 2026-11-04).

One nullable column, additive: the tracer's id for the turn. latest_undoable
prefers a non-memory row from the same turn over the memory save that
followed it. Rows written before the column existed have null and keep the
old newest-row behaviour.

Revision ID: 20261104_0025
Revises: 20261104_0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0025"
down_revision: str | Sequence[str] | None = "20261104_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduled_task_changes", sa.Column("turn_id", sa.String(64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("scheduled_task_changes", "turn_id")
