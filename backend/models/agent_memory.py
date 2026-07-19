import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
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
from backend.models.vector import VECTOR_DIMENSION


class SemanticCacheEntry(Base):
    __tablename__ = "semantic_cache_entries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "cache_key",
            "model",
            name="uq_semantic_cache_user_key_model",
        ),
        Index(
            "ix_semantic_cache_user_expiry",
            "user_id",
            "expires_at",
        ),
        Index(
            "ix_semantic_cache_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(VECTOR_DIMENSION), nullable=False
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Convert this semantic-cache row into an API-safe dictionary.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "cache_key": self.cache_key,
            "query": self.query,
            "response": self.response,
            "model": self.model,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "hit_count": self.hit_count,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_accessed_at": (
                self.last_accessed_at.isoformat() if self.last_accessed_at else None
            ),
        }


class WorkingMemoryItem(Base):
    __tablename__ = "working_memory_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "conversation_id",
            "memory_key",
            name="uq_working_memory_user_conversation_key",
        ),
        Index(
            "ix_working_memory_user_conversation",
            "user_id",
            "conversation_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    memory_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Convert this working-memory row into an API-safe dictionary.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "conversation_id": str(self.conversation_id),
            "memory_key": self.memory_key,
            "value": self.value,
            "purpose": self.purpose,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ProcedureMemory(Base):
    __tablename__ = "procedure_memories"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "name",
            "version",
            name="uq_procedure_memory_user_name_version",
        ),
        Index(
            "ix_procedure_memory_user_state",
            "user_id",
            "approval_state",
        ),
        Index(
            "ix_procedure_memory_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    approval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(VECTOR_DIMENSION), nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Convert this procedure row into an API-safe dictionary.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "steps": self.steps,
            "approval_state": self.approval_state,
            "version": self.version,
            "source_trace_id": str(self.source_trace_id),
            "source_conversation_id": (
                str(self.source_conversation_id)
                if self.source_conversation_id
                else None
            ),
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "active": self.active,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MemoryEntity(Base):
    __tablename__ = "memory_entities"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "entity_type",
            "normalized_name",
            name="uq_memory_entity_user_type_name",
        ),
        Index(
            "ix_memory_entity_user_state",
            "user_id",
            "approval_state",
        ),
        Index(
            "ix_memory_entity_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    approval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(VECTOR_DIMENSION), nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Convert this entity row into an API-safe dictionary.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "normalized_name": self.normalized_name,
            "attributes": self.attributes,
            "approval_state": self.approval_state,
            "source_conversation_id": (
                str(self.source_conversation_id)
                if self.source_conversation_id
                else None
            ),
            "source_trace_id": str(self.source_trace_id),
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class MemoryEntityRelation(Base):
    __tablename__ = "memory_entity_relations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            name="uq_memory_entity_relation",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    source_trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Convert this entity-relation row into an API-safe dictionary.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "source_entity_id": str(self.source_entity_id),
            "target_entity_id": str(self.target_entity_id),
            "relation_type": self.relation_type,
            "attributes": self.attributes,
            "approval_state": self.approval_state,
            "source_trace_id": str(self.source_trace_id),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "content_hash",
            name="uq_knowledge_document_user_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(20), nullable=False)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Convert this knowledge-document row into an API-safe dictionary.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "title": self.title,
            "source_uri": self.source_uri,
            "content_hash": self.content_hash,
            "purpose": self.purpose,
            "status": self.status,
            "approval_state": self.approval_state,
            "source_conversation_id": (
                str(self.source_conversation_id)
                if self.source_conversation_id
                else None
            ),
            "source_trace_id": (
                str(self.source_trace_id) if self.source_trace_id else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "position",
            name="uq_knowledge_chunk_document_position",
        ),
        Index("ix_knowledge_chunk_user_document", "user_id", "document_id"),
        Index(
            "ix_knowledge_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(VECTOR_DIMENSION), nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Convert this knowledge-chunk row into an API-safe dictionary.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "document_id": str(self.document_id),
            "position": self.position,
            "content": self.content,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "conversation_id",
            "through_turn_count",
            name="uq_conversation_summary_version",
        ),
        Index(
            "ix_conversation_summary_user_conversation",
            "user_id",
            "conversation_id",
        ),
        Index(
            "ix_conversation_summary_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    through_turn_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(VECTOR_DIMENSION), nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Convert this conversation-summary row into an API-safe dictionary.
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "conversation_id": str(self.conversation_id),
            "content": self.content,
            "through_turn_count": self.through_turn_count,
            "source_trace_id": str(self.source_trace_id),
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "embedding_dimension": self.embedding_dimension,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
