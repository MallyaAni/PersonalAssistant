"""A check-in stores what it is about, instead of it being read back out of prose.

Revision ID: 20260830_0014
Revises: 20260830_0013
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0014"
down_revision: str | Sequence[str] | None = "20260830_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable because a reminder has no subject and never will. Encrypted
    # like the instruction beside it: it is the person's own words about
    # their own life, and "the fertility appointment" is exactly the sort
    # of thing that must not sit in plaintext because it was convenient.
    op.add_column(
        "scheduled_tasks",
        sa.Column("subject", sa.Text(), nullable=True),
    )
    # The kinds were "checkin:event" and "checkin:wellbeing" for the few
    # hours between 0013 and this. They name situations, and the point of
    # the rename is that the kinds should name what governs the rules
    # instead - an outing, an interview and a flat application are all
    # followed up identically, and only wellbeing is rationed. Any row
    # written in that window is the same thing under the earlier name.
    op.execute(
        "update scheduled_tasks set kind = 'checkin:following_up' "
        "where kind = 'checkin:event'"
    )


def downgrade() -> None:
    op.execute(
        "update scheduled_tasks set kind = 'checkin:event' "
        "where kind = 'checkin:following_up'"
    )
    op.drop_column("scheduled_tasks", "subject")
