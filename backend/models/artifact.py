import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base


class VisualArtifact(Base):
    __tablename__ = "visual_artifacts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('diagram', 'generated_image', 'uploaded_image')",
            name="ck_visual_artifacts_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed')",
            name="ck_visual_artifacts_status",
        ),
        Index(
            "ix_visual_artifacts_user_conversation_created",
            "user_id",
            "conversation_id",
            "created_at",
        ),
    )

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
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_format: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Serialize one artifact without exposing persistence implementation details.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "conversation_id": str(self.conversation_id),
            "trace_id": str(self.trace_id),
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "source_format": self.source_format,
            "source": self.source,
            "mime_type": self.mime_type,
            "content_available": self.storage_key is not None,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "provider": self.provider,
            "model": self.model,
            "error_code": self.error_code,
            "metadata": self.extra_data or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
