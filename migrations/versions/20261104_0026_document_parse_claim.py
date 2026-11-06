"""Let one process claim a queued document parse at a time.

The queue selected every pending row and parsed them all, so two API
processes running the loop read the same file twice and stored it twice.
The claim columns are the presentation worker's lease, applied here: a
worker takes one row with skip-locked, holds it until the lease expires,
and a crashed worker's row is picked up after that.

Additive and nullable; rows already pending need no backfill because a
pending row is claimable without a lease.

Revision ID: 20261104_0026
Revises: 20261104_0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_0026"
down_revision: str | Sequence[str] | None = "20261104_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_parse_jobs", sa.Column("worker_id", sa.String(200), nullable=True)
    )
    op.add_column(
        "document_parse_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_document_parse_jobs_claim",
        "document_parse_jobs",
        ["status", "lease_expires_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_parse_jobs_claim", table_name="document_parse_jobs")
    op.drop_column("document_parse_jobs", "lease_expires_at")
    op.drop_column("document_parse_jobs", "worker_id")
