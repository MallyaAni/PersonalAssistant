"""Conversation groups: a group chat as an account, and its members.

Revision ID: 20260828_0011
Revises: 20260826_0010
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260828_0011"
down_revision: str | Sequence[str] | None = "20260826_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("chat_address", sa.Text(), nullable=False),
        sa.Column("chat_digest", sa.String(length=64), nullable=False),
        sa.Column("chat_channel", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_conversation_group_user"),
        sa.UniqueConstraint("chat_digest", name="uq_conversation_group_chat"),
    )
    op.create_index("ix_conversation_groups_chat", "conversation_groups", ["chat_digest"])
    op.create_table(
        "conversation_group_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_user_id", sa.String(length=50), nullable=False),
        sa.Column("member_user_id", sa.String(length=50), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["group_user_id"], ["conversation_groups.user_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_user_id", "member_user_id", name="uq_conversation_group_member"),
    )
    op.create_index("ix_conversation_group_members_member", "conversation_group_members", ["member_user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_group_members_member", table_name="conversation_group_members")
    op.drop_table("conversation_group_members")
    op.drop_index("ix_conversation_groups_chat", table_name="conversation_groups")
    op.drop_table("conversation_groups")
