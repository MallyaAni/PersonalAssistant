"""Carry chosen credentials on an access request.

Approval previously handed back a usable token that the asker still had to
redeem, so an approved request was not yet an account and the operator could not
see whether anyone had actually signed up. Collecting the username and password
when they ask means approving creates the account outright.

The password is hashed on arrival with the same parameters as a live account. A
pending request is not a safer place to keep a secret than a real account, and
the plaintext is never needed again: approval moves the hash across unchanged.

Revision ID: 20260802_0030
Revises: 20260802_0029
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0030"
down_revision: str | Sequence[str] | None = "20260802_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable because requests made before this migration have neither, and
    # they stay approvable through the token path they were created under.
    op.add_column(
        "access_requests", sa.Column("desired_username", sa.Text(), nullable=True)
    )
    op.add_column(
        "access_requests", sa.Column("password_hash", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("access_requests", "password_hash")
    op.drop_column("access_requests", "desired_username")
