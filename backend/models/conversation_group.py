"""A group chat as an account: who is in it, and which chat it is.

A group is a `user_id` of the form `group:<slug>` - a real `user_accounts` row
that cannot log in - so everything the group learns or schedules is owned the
way every other record is owned (ADR 0016). These two tables hold what the
account row cannot: which chat the group is, and which approved accounts are
its members.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText


class ConversationGroup(Base):
    """One group chat and the account that owns what it learns."""

    __tablename__ = "conversation_groups"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_conversation_group_user"),
        UniqueConstraint("chat_digest", name="uq_conversation_group_chat"),
        Index("ix_conversation_groups_chat", "chat_digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The owning account: `group:<slug>`.
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # The chat, sealed, and its keyed digest for lookup - the same shape as a
    # subscriber address, because that is what it is to delivery.
    chat_address: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    chat_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_channel: Mapped[str] = mapped_column(String(20), nullable=False, default="imessage")
    display_name: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationGroupMember(Base):
    """One approved account's membership of a group."""

    __tablename__ = "conversation_group_members"
    __table_args__ = (
        UniqueConstraint("group_user_id", "member_user_id", name="uq_conversation_group_member"),
        Index("ix_conversation_group_members_member", "member_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("conversation_groups.user_id", ondelete="CASCADE"), nullable=False
    )
    member_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
