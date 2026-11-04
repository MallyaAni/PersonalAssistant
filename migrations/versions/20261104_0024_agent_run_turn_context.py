"""Carry the turn's own context on the run that continues it.

A chat turn that runs out of budget hands its remaining steps to a durable
run. The run knew the conversation and the channel, so the person was told
where they had asked - but a step it applied was applied with no turn
context at all: no speaker (a room's members share one account), no zone (a
group continuation could not resolve where the speaker was), and no
replied-to message. The effects followed: a reminder created by a group
continuation was saved on `web` and never delivered, a room check-in
skipped the room's sensitive-subject refusal, and the change log wrote a
null conversation so "undo that" inside the run could undo another
conversation's change.

Three nullable columns, additive. A run that continues no turn - every
other kind - leaves them null and behaves exactly as before.

Revision ID: 20261104_0024
Revises: 20261101_0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0024"
down_revision: str | Sequence[str] | None = "20261101_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("speaker_user_id", sa.String(50), nullable=True)
    )
    op.add_column("agent_runs", sa.Column("timezone", sa.String(60), nullable=True))
    op.add_column("agent_runs", sa.Column("replying_to", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "replying_to")
    op.drop_column("agent_runs", "timezone")
    op.drop_column("agent_runs", "speaker_user_id")
