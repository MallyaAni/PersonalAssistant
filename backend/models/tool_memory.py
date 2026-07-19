import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.models.vector import VECTOR_DIMENSION


class ToolDescriptor(Base):
    __tablename__ = "tool_descriptors"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "server_id",
            "tool_name",
            "schema_fingerprint",
            name="uq_tool_descriptor_identity",
        ),
        Index(
            "ix_tool_descriptor_active_lookup",
            "user_id",
            "server_id",
            "active",
        ),
        Index(
            "ix_tool_descriptor_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    server_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    input_purpose: Mapped[str] = mapped_column(Text, nullable=False)
    schema_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_classification: Mapped[str] = mapped_column(String(30), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(VECTOR_DIMENSION), nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "server_id": self.server_id,
            "tool_name": self.tool_name,
            "description": self.description,
            "input_purpose": self.input_purpose,
            "schema_fingerprint": self.schema_fingerprint,
            "tool_version": self.tool_version,
            "risk_classification": self.risk_classification,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ToolPreference(Base):
    __tablename__ = "tool_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "server_id",
            "tool_name",
            "preference_key",
            name="uq_tool_preference_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    server_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    preference_key: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    source_trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "server_id": self.server_id,
            "tool_name": self.tool_name,
            "preference_key": self.preference_key,
            "value": self.value,
            "purpose": self.purpose,
            "approval_state": self.approval_state,
            "source_trace_id": str(self.source_trace_id),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ToolUsageOutcome(Base):
    __tablename__ = "tool_usage_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    server_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    outcome_category: Mapped[str] = mapped_column(String(30), nullable=False)
    source_trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "server_id": self.server_id,
            "tool_name": self.tool_name,
            "outcome_category": self.outcome_category,
            "source_trace_id": str(self.source_trace_id),
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
