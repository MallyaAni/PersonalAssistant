"""Make what the user actually said searchable, not only what a classifier kept.

One number states the problem: an account with fourteen stored conversations had
zero rows in `semantic_memory`. Her job, her constraints and her frustration
were never lost - they sit here in `conversations`, encrypted - but only
`semantic_memory` is searched, and a 4B classifier decides what is promoted
into it. Measured over nine statements it captures attributes ("my dog is
Biscuit") and misses circumstances ("I cover phone lines for executives"), so
everything it declines is invisible for good.

Teaching it more categories would be endless. Embedding the turn instead moves
the judgement to recall time, where the question is in hand and relevance
generalises without anyone naming a category.

The vector goes on `conversations` rather than in a table beside it: there is
exactly one per turn, the row is written once and never split, and a separate
table would only add a join and the chance of orphans.

Purely additive and nullable. Every turn recorded before today simply has no
vector until the backfill runs, and a NULL is skipped by the search rather than
matching everything. The development database holds real conversations and has
no backups, so nothing here rewrites or drops anything.

Revision ID: 20260819_0039
Revises: 20260812_0038
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260819_0039"
down_revision: str | Sequence[str] | None = "20260812_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches EMBEDDING_DIMENSION and the vector already stored on semantic_memory,
# so one query embedding can be compared against both stores in a turn.
_DIMENSION = 768


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("embedding", Vector(_DIMENSION), nullable=True),
    )
    # Recorded beside the vector for the same reason semantic_memory records
    # it: a vector is only comparable with others from the same model, and a
    # model change has to be visible rather than silently mixing spaces.
    op.add_column(
        "conversations",
        sa.Column("embedding_model", sa.String(length=200), nullable=True),
    )
    # Recall is always scoped to one account, so the index leads with the
    # owner; without that every search would scan other people's turns before
    # discarding them.
    op.create_index(
        "ix_conversations_user_embedded",
        "conversations",
        ["user_id"],
        postgresql_where=sa.text("embedding IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_user_embedded", table_name="conversations")
    op.drop_column("conversations", "embedding_model")
    op.drop_column("conversations", "embedding")
