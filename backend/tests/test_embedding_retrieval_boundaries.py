"""Vector retrieval never mixes records from incompatible embedding spaces."""

from typing import Any

from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.models.agent_memory import (
    ConversationSummary,
    KnowledgeChunk,
    MemoryEntity,
    ProcedureMemory,
    SemanticCacheEntry,
)
from backend.services.agent_memory_manager import _VectorStore
from backend.services.tool_memory_service import ToolMemoryService


class _Embeddings:
    model = "current-embedding-model"


# Render SQL predicates into one stable string for boundary assertions.
def _sql(predicates: tuple[Any, ...]) -> str:
    return " ".join(str(predicate) for predicate in predicates)


# Build the shared vector-store mechanism without requiring a live database.
def _vector_store() -> _VectorStore:
    return _VectorStore(
        None,  # type: ignore[arg-type]
        _Embeddings(),  # type: ignore[arg-type]
        SemanticRetrievalPolicy(),
        "current-version",
    )


# Every agent-memory vector table must be bounded by model, version, and dimension.
def test_agent_memory_vector_spaces_are_part_of_every_search_boundary() -> None:
    store = _vector_store()
    for model in (
        SemanticCacheEntry,
        ProcedureMemory,
        MemoryEntity,
        KnowledgeChunk,
        ConversationSummary,
    ):
        rendered = _sql(store._current_embedding_predicates(model, [0.0] * 768))
        assert f"{model.__tablename__}.embedding_model" in rendered
        assert f"{model.__tablename__}.embedding_version" in rendered
        assert f"{model.__tablename__}.embedding_dimension" in rendered


# Tool descriptors use the same boundary as personal and agent memories.
def test_tool_descriptor_search_uses_the_current_embedding_space() -> None:
    service = ToolMemoryService(
        None,  # type: ignore[arg-type]
        _Embeddings(),  # type: ignore[arg-type]
        SemanticRetrievalPolicy(),
        "current-version",
    )
    rendered = _sql(service._current_embedding_filters([0.0] * 768))
    assert "tool_descriptors.embedding_model" in rendered
    assert "tool_descriptors.embedding_version" in rendered
    assert "tool_descriptors.embedding_dimension" in rendered
