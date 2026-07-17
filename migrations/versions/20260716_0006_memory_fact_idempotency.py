"""Make approved fact provenance idempotent.

Revision ID: 20260716_0006
Revises: 20260716_0005
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0006"
down_revision: str | Sequence[str] | None = "20260716_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_memory_facts_user_key_source_trace",
        "memory_facts",
        ["user_id", "fact_key", "source_trace_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_memory_facts_user_key_source_trace",
        "memory_facts",
        type_="unique",
    )
