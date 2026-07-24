import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
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
from backend.database.types import EncryptedText
from backend.models.vector import VECTOR_DIMENSION


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(100))
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "name": self.name,
            "preferences": self.preferences,
        }


class EpisodicMemory(Base):
    __tablename__ = "episodic_memory"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())
    content: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(100), nullable=False, default="user_explicit"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "content": self.content,
            "purpose": self.purpose,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "extra_data": self.extra_data,
        }


class SemanticMemory(Base):
    __tablename__ = "semantic_memory"
    __table_args__ = (
        Index(
            "ix_semantic_memory_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    content: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(VECTOR_DIMENSION))
    purpose: Mapped[str] = mapped_column(
        String(100), nullable=False, default="user_explicit"
    )
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "content": self.content,
            "purpose": self.purpose,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MemoryFact(Base):
    __tablename__ = "memory_facts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "fact_key",
            "version",
            name="uq_memory_facts_user_key_version",
        ),
        UniqueConstraint(
            "user_id",
            "fact_key",
            "source_trace_id",
            name="uq_memory_facts_user_key_source_trace",
        ),
        Index(
            "ix_memory_facts_user_key_state",
            "user_id",
            "fact_key",
            "approval_state",
        ),
        Index("ix_memory_facts_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    approval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_facts.id", ondelete="SET NULL"),
        nullable=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "fact_type": self.fact_type,
            "fact_key": self.fact_key,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "approval_state": self.approval_state,
            "confidence": self.confidence,
            "purpose": self.purpose,
            "source_conversation_id": (
                str(self.source_conversation_id)
                if self.source_conversation_id
                else None
            ),
            "source_trace_id": (
                str(self.source_trace_id) if self.source_trace_id else None
            ),
            "version": self.version,
            "supersedes_id": str(self.supersedes_id) if self.supersedes_id else None,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "extra_data": self.extra_data,
        }
