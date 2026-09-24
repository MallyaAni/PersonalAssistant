"""Keep encrypted personal advice separate from research and trade journals."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260924_0021"
down_revision = "20260912_0020"
branch_labels = None
depends_on = None


# Add an independent receipt store without changing widely queried account tables.
def upgrade() -> None:
    op.create_table(
        "personal_decision_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledge_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_personal_decisions_owner_time",
        "personal_decision_receipts",
        ["user_id", "generated_at", "id"],
    )
    op.create_index(
        "ix_personal_decisions_expiry", "personal_decision_receipts", ["expires_at"]
    )


# Remove the receipt store only during an explicitly authorized schema rollback.
def downgrade() -> None:
    op.drop_table("personal_decision_receipts")
