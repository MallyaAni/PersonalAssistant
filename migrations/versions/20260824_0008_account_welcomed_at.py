"""Record that an account has been introduced, so it happens exactly once.

The welcome is sent unprompted when the operator approves someone, and the
only thing standing between that and a duplicate introduction is a durable
mark. It lives on the account rather than on the access request because the
question being answered is "has this person ever been welcomed", which
outlives the request that created them and is still answerable if they were
approved through some other path.

Nullable, and null means not yet. Every account that exists today predates the
welcome and must not receive one retroactively: they have been using the
assistant for weeks, and an introduction arriving now would read as a fault.
Back-filling is therefore the wrong default, and this migration deliberately
leaves them null rather than stamping them - the one place where "no data" and
"already done" would be worth conflating, and the reason they are not is that
a wrong guess here texts real people.

Revision ID: 20260824_0008
Revises: 20260824_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0008"
down_revision: str | Sequence[str] | None = "20260824_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the mark. Existing accounts stay null; see the note above on why.
def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("welcomed_at", sa.DateTime(timezone=True), nullable=True),
    )


# Remove it, leaving the table as it was.
def downgrade() -> None:
    op.drop_column("user_accounts", "welcomed_at")
