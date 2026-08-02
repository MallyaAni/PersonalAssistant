"""Record the operator's approval of a subscription.

Revision ID: 20260802_0027
Revises: 20260802_0026
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0027"
down_revision: str | Sequence[str] | None = "20260802_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Consent and approval are different permissions and both are required to send.
#
# The recipient consents to receive; the operator permits this machine to message
# that address, because the bridge sends from the operator's own Apple ID.
# Existing rows were created by the operator directly, so they are approved.
def upgrade() -> None:
    op.add_column(
        "discovery_subscribers",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE discovery_subscribers SET approved_at = created_at")


def downgrade() -> None:
    op.drop_column("discovery_subscribers", "approved_at")
