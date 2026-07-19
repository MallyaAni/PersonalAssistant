"""Add durable stores for the remaining agent memory forms.

Revision ID: 20260717_0008
Revises: 20260716_0007
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260717_0008"
down_revision: str | Sequence[str] | None = "20260716_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Create the agent-memory tables, constraints, and vector indexes.
def upgrade() -> None:
    op.create_table(
        "semantic_cache_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "cache_key",
            "model",
            name="uq_semantic_cache_user_key_model",
        ),
    )
    op.create_index(
        "ix_semantic_cache_entries_user_id",
        "semantic_cache_entries",
        ["user_id"],
    )
    op.create_index(
        "ix_semantic_cache_entries_expires_at",
        "semantic_cache_entries",
        ["expires_at"],
    )
    op.create_index(
        "ix_semantic_cache_user_expiry",
        "semantic_cache_entries",
        ["user_id", "expires_at"],
    )
    op.create_index(
        "ix_semantic_cache_embedding_hnsw",
        "semantic_cache_entries",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "working_memory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "conversation_id",
            "memory_key",
            name="uq_working_memory_user_conversation_key",
        ),
    )
    op.create_index(
        "ix_working_memory_items_user_id", "working_memory_items", ["user_id"]
    )
    op.create_index(
        "ix_working_memory_items_expires_at",
        "working_memory_items",
        ["expires_at"],
    )
    op.create_index(
        "ix_working_memory_user_conversation",
        "working_memory_items",
        ["user_id", "conversation_id"],
    )

    op.create_table(
        "procedure_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.JSON(), nullable=False),
        sa.Column("approval_state", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_data", postgresql.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "name",
            "version",
            name="uq_procedure_memory_user_name_version",
        ),
    )
    op.create_index("ix_procedure_memories_user_id", "procedure_memories", ["user_id"])
    op.create_index(
        "ix_procedure_memories_expires_at", "procedure_memories", ["expires_at"]
    )
    op.create_index(
        "ix_procedure_memory_user_state",
        "procedure_memories",
        ["user_id", "approval_state"],
    )
    op.create_index(
        "ix_procedure_memory_embedding_hnsw",
        "procedure_memories",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "memory_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("canonical_name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("attributes", postgresql.JSON(), nullable=False),
        sa.Column("approval_state", sa.String(length=20), nullable=False),
        sa.Column(
            "source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("source_trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "entity_type",
            "normalized_name",
            name="uq_memory_entity_user_type_name",
        ),
    )
    op.create_index("ix_memory_entities_user_id", "memory_entities", ["user_id"])
    op.create_index("ix_memory_entities_expires_at", "memory_entities", ["expires_at"])
    op.create_index(
        "ix_memory_entity_user_state",
        "memory_entities",
        ["user_id", "approval_state"],
    )
    op.create_index(
        "ix_memory_entity_embedding_hnsw",
        "memory_entities",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "memory_entity_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=100), nullable=False),
        sa.Column("attributes", postgresql.JSON(), nullable=False),
        sa.Column("approval_state", sa.String(length=20), nullable=False),
        sa.Column("source_trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_entity_id"], ["memory_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"], ["memory_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            name="uq_memory_entity_relation",
        ),
    )
    op.create_index(
        "ix_memory_entity_relations_user_id",
        "memory_entity_relations",
        ["user_id"],
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "content_hash",
            name="uq_knowledge_document_user_hash",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_user_id", "knowledge_documents", ["user_id"]
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("extra_data", postgresql.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "position",
            name="uq_knowledge_chunk_document_position",
        ),
    )
    op.create_index("ix_knowledge_chunks_user_id", "knowledge_chunks", ["user_id"])
    op.create_index(
        "ix_knowledge_chunk_user_document",
        "knowledge_chunks",
        ["user_id", "document_id"],
    )
    op.create_index(
        "ix_knowledge_chunk_embedding_hnsw",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "conversation_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("through_turn_count", sa.Integer(), nullable=False),
        sa.Column("source_trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_version", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "conversation_id",
            "through_turn_count",
            name="uq_conversation_summary_version",
        ),
    )
    op.create_index(
        "ix_conversation_summaries_user_id",
        "conversation_summaries",
        ["user_id"],
    )
    op.create_index(
        "ix_conversation_summary_user_conversation",
        "conversation_summaries",
        ["user_id", "conversation_id"],
    )
    op.create_index(
        "ix_conversation_summary_embedding_hnsw",
        "conversation_summaries",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_semantic_memory_embedding_hnsw",
        "semantic_memory",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_tool_descriptor_embedding_hnsw",
        "tool_descriptors",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


# Remove the agent-memory schema created by this migration.
def downgrade() -> None:
    op.drop_index("ix_tool_descriptor_embedding_hnsw", table_name="tool_descriptors")
    op.drop_index("ix_semantic_memory_embedding_hnsw", table_name="semantic_memory")
    op.drop_index(
        "ix_conversation_summary_embedding_hnsw",
        table_name="conversation_summaries",
    )
    op.drop_index(
        "ix_conversation_summary_user_conversation",
        table_name="conversation_summaries",
    )
    op.drop_index(
        "ix_conversation_summaries_user_id", table_name="conversation_summaries"
    )
    op.drop_table("conversation_summaries")
    op.drop_index("ix_knowledge_chunk_embedding_hnsw", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunk_user_document", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_user_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_user_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index(
        "ix_memory_entity_relations_user_id", table_name="memory_entity_relations"
    )
    op.drop_table("memory_entity_relations")
    op.drop_index("ix_memory_entity_embedding_hnsw", table_name="memory_entities")
    op.drop_index("ix_memory_entity_user_state", table_name="memory_entities")
    op.drop_index("ix_memory_entities_expires_at", table_name="memory_entities")
    op.drop_index("ix_memory_entities_user_id", table_name="memory_entities")
    op.drop_table("memory_entities")
    op.drop_index("ix_procedure_memory_embedding_hnsw", table_name="procedure_memories")
    op.drop_index("ix_procedure_memory_user_state", table_name="procedure_memories")
    op.drop_index("ix_procedure_memories_expires_at", table_name="procedure_memories")
    op.drop_index("ix_procedure_memories_user_id", table_name="procedure_memories")
    op.drop_table("procedure_memories")
    op.drop_index(
        "ix_working_memory_user_conversation", table_name="working_memory_items"
    )
    op.drop_index(
        "ix_working_memory_items_expires_at", table_name="working_memory_items"
    )
    op.drop_index("ix_working_memory_items_user_id", table_name="working_memory_items")
    op.drop_table("working_memory_items")
    op.drop_index(
        "ix_semantic_cache_embedding_hnsw", table_name="semantic_cache_entries"
    )
    op.drop_index("ix_semantic_cache_user_expiry", table_name="semantic_cache_entries")
    op.drop_index(
        "ix_semantic_cache_entries_expires_at", table_name="semantic_cache_entries"
    )
    op.drop_index(
        "ix_semantic_cache_entries_user_id", table_name="semantic_cache_entries"
    )
    op.drop_table("semantic_cache_entries")
