import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText


class Presentation(Base):
    __tablename__ = "presentations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=False
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "presentation_revisions.id",
            name="fk_presentations_current_revision",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Serialize public deck metadata without exposing storage identifiers.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "conversation_id": str(self.conversation_id),
            "trace_id": str(self.trace_id),
            "title": self.title,
            "current_revision_id": (
                str(self.current_revision_id) if self.current_revision_id else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PresentationRevision(Base):
    __tablename__ = "presentation_revisions"
    __table_args__ = (
        UniqueConstraint(
            "presentation_id",
            "revision_number",
            name="uq_presentation_revisions_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    presentation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("presentations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("presentation_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    specification_json: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    target_slide_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    change_summary: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    renderer: Mapped[str | None] = mapped_column(String(80), nullable=True)
    renderer_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Serialize one revision and optionally include its canonical specification.
    def to_dict(self, include_specification: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": str(self.id),
            "presentation_id": str(self.presentation_id),
            "parent_revision_id": (
                str(self.parent_revision_id) if self.parent_revision_id else None
            ),
            "revision_number": self.revision_number,
            "status": self.status,
            "target_slide_id": self.target_slide_id,
            "change_summary": self.change_summary,
            "provider": self.provider,
            "model": self.model,
            "renderer": self.renderer,
            "renderer_version": self.renderer_version,
            "content_available": self.storage_key is not None,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "error_code": self.error_code,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
        }
        if include_specification:
            result["specification"] = (
                json.loads(self.specification_json) if self.specification_json else None
            )
        return result
