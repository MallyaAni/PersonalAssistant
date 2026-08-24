"""Collect a phone number when someone asks for an account.

The iMessage bridge decides who is talking by looking a sender's normalized
address up against the subscriber allowlist. Until now that allowlist was only
ever populated after the fact, by an account holder enrolling an address, so an
approved user could sign in on the web and still be a stranger to the bridge.

Asking at sign-up makes approval the moment someone becomes reachable: the
operator sees the number they are approving, and accepting the request enrols
it. Stored the way this codebase stores anything that identifies a person - the
value encrypted at rest, a separate digest carrying lookup and uniqueness.

Nullable, deliberately. Requests already in the table were made before the
field existed and cannot be back-filled from anything; a NOT NULL column would
either refuse the migration or invent a number for a real person. New requests
are required to carry one by the API, which is where the rule belongs.

Revision ID: 20260824_0007
Revises: 20260822_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0007"
down_revision: str | Sequence[str] | None = "20260822_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the encrypted number and its lookup digest.
def upgrade() -> None:
    op.add_column("access_requests", sa.Column("phone", sa.Text(), nullable=True))
    op.add_column(
        "access_requests",
        sa.Column("phone_digest", sa.String(length=64), nullable=True),
    )
    # Not unique: the same person may ask twice after being declined, and a
    # unique constraint would turn a second attempt into a 500 rather than a
    # second request the operator can read. Indexed because approval looks the
    # number up to decide whether it is already enrolled to someone else.
    op.create_index(
        "ix_access_requests_phone_digest",
        "access_requests",
        ["phone_digest"],
        unique=False,
    )


# Remove both, so a downgrade leaves the table as it was.
def downgrade() -> None:
    op.drop_index("ix_access_requests_phone_digest", table_name="access_requests")
    op.drop_column("access_requests", "phone_digest")
    op.drop_column("access_requests", "phone")
