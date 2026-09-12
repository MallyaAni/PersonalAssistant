"""An ANN index on the sweep's seen-item store, which had none.

Every sweep asks two cosine questions per candidate against everything this
user has ever been shown: `has_near_duplicate` (is this the same happening as
one already announced) and `nearest_seen_distance` (is this the same *kind* of
thing this account always gets). Both ran through a plain btree on `user_id`,
so each was a sequential scan with a distance computed per row - the exact
shape the transcript store was given an index for in 20260824_0009, on the same
box, for the same reason.

It is invisible today and not later: `discovery_seen_items` grows by every
candidate every sweep, announced or not, forever, and the scan is per candidate
rather than per sweep. A daily cadence multiplies both sides. Built now because
building it under a large table is the slow, memory-hungry version, and because
this table has no retention step to bound it.

The sibling embedding columns - conversations, semantic_memory, the four agent
memory stores - are all indexed this way already. This one was simply missed.

Revision ID: 20260912_0020
Revises: 20260905_0019
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260912_0020"
down_revision: str | Sequence[str] | None = "20260905_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the HNSW cosine index the two novelty queries scan without.
def upgrade() -> None:
    op.create_index(
        "ix_discovery_seen_items_embedding_hnsw",
        "discovery_seen_items",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


# Drop it. The queries fall back to the sequential scan they used before.
def downgrade() -> None:
    op.drop_index(
        "ix_discovery_seen_items_embedding_hnsw",
        table_name="discovery_seen_items",
    )
