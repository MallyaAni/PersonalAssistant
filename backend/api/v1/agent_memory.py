import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.auth import authorize_path_user
from backend.core.dependencies import (
    DependencyAgentMemoryManager,
    DependencyMemoryOperationsService,
    DependencyMemoryReembeddingService,
    DependencyMemoryRetentionService,
)

router = APIRouter(
    prefix="/memory",
    tags=["agent-memory"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, Path(min_length=1, max_length=50)]


# Validate that a timestamp is timezone-aware and in the future.
def _require_future(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("must include a timezone")
    if value <= datetime.now(UTC):
        raise ValueError("must be in the future")
    return value


# Validate an optional timestamp when one is supplied.
def _require_optional_future(value: datetime | None) -> datetime | None:
    return _require_future(value) if value is not None else None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SemanticCacheRequest(StrictModel):
    query: str = Field(min_length=1, max_length=10_000)
    response: str = Field(min_length=1, max_length=50_000)
    model: str = Field(min_length=1, max_length=200)
    expires_at: datetime

    # Validate semantic-cache expiry before accepting the request.
    @field_validator("expires_at")
    @classmethod
    def require_future(cls, value: datetime) -> datetime:
        return _require_future(value)


class WorkingMemoryRequest(StrictModel):
    conversation_id: uuid.UUID
    memory_key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=10_000)
    purpose: str = Field(min_length=1, max_length=100)
    expires_at: datetime

    # Validate working-memory expiry before accepting the request.
    @field_validator("expires_at")
    @classmethod
    def require_future(cls, value: datetime) -> datetime:
        return _require_future(value)


class ProcedureRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10_000)
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    source_conversation_id: uuid.UUID | None = None
    source_trace_id: uuid.UUID
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Validate an optional procedure expiry.
    @field_validator("expires_at")
    @classmethod
    def require_future(cls, value: datetime | None) -> datetime | None:
        return _require_optional_future(value)


class EntityRequest(StrictModel):
    entity_type: str = Field(min_length=1, max_length=100)
    canonical_name: str = Field(min_length=1, max_length=300)
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_conversation_id: uuid.UUID | None = None
    source_trace_id: uuid.UUID
    expires_at: datetime | None = None

    # Validate an optional entity expiry.
    @field_validator("expires_at")
    @classmethod
    def require_future(cls, value: datetime | None) -> datetime | None:
        return _require_optional_future(value)


class EntityRelationRequest(StrictModel):
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relation_type: str = Field(min_length=1, max_length=100)
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_trace_id: uuid.UUID


class KnowledgeDocumentRequest(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=200_000)
    source_uri: str | None = Field(default=None, max_length=2_000)
    purpose: str = Field(default="user_knowledge", min_length=1, max_length=100)
    source_conversation_id: uuid.UUID | None = None
    source_trace_id: uuid.UUID | None = None


class SummaryRequest(StrictModel):
    conversation_id: uuid.UUID
    content: str = Field(min_length=1, max_length=50_000)
    through_turn_count: int = Field(ge=1)
    source_trace_id: uuid.UUID


# Return counts for every agent-memory store owned by a user.
@router.get("/{user_id}/agent")
async def agent_memory_snapshot(
    user_id: UserId,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return await manager.snapshot(user_id)


# Create or refresh a semantic-cache entry.
@router.put("/{user_id}/agent/cache")
async def put_semantic_cache(
    user_id: UserId,
    body: SemanticCacheRequest,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return await manager.semantic_cache.put(
        user_id,
        body.query,
        body.response,
        body.model,
        body.expires_at,
    )


# Retrieve an exact or semantically similar cached response.
@router.get("/{user_id}/agent/cache")
async def get_semantic_cache(
    user_id: UserId,
    manager: DependencyAgentMemoryManager,
    query: str = Query(min_length=1, max_length=10_000),
    model: str = Query(min_length=1, max_length=200),
) -> dict[str, Any]:
    return {"entry": await manager.semantic_cache.get(user_id, query, model)}


# Delete expired semantic-cache entries for one user.
@router.delete("/{user_id}/agent/cache/expired")
async def purge_semantic_cache(
    user_id: UserId,
    manager: DependencyAgentMemoryManager,
) -> dict[str, int]:
    return {"deleted": await manager.semantic_cache.purge_expired(user_id)}


# Preview or apply retention cleanup for one user's memory.
@router.post("/{user_id}/agent/retention/purge")
async def purge_expired_memory(
    user_id: UserId,
    service: DependencyMemoryRetentionService,
    dry_run: bool = Query(default=True),
) -> dict[str, Any]:
    return await service.purge_expired(user_id, dry_run=dry_run)


# Report current and stale vector counts for one user.
@router.get("/{user_id}/agent/reembedding")
async def reembedding_inventory(
    user_id: UserId,
    service: DependencyMemoryReembeddingService,
) -> dict[str, Any]:
    return await service.inventory(user_id)


# Preview or replace stale vectors for one user.
@router.post("/{user_id}/agent/reembedding")
async def reembed_memory(
    user_id: UserId,
    service: DependencyMemoryReembeddingService,
    dry_run: bool = Query(default=True),
    batch_size: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    return await service.reembed(
        user_id,
        dry_run=dry_run,
        batch_size=batch_size,
    )


# Report operational health for one user's memory.
@router.get("/{user_id}/agent/operations")
async def inspect_memory_operations(
    user_id: UserId,
    service: DependencyMemoryOperationsService,
) -> dict[str, Any]:
    return await service.inspect(user_id)


# Expose non-content memory health as Prometheus-compatible metrics.
@router.get(
    "/{user_id}/agent/operations/metrics",
    response_class=PlainTextResponse,
)
async def memory_operations_metrics(
    user_id: UserId,
    service: DependencyMemoryOperationsService,
) -> str:
    return service.prometheus(await service.inspect(user_id))


# Create or update a temporary working-memory item.
@router.put("/{user_id}/agent/working")
async def upsert_working_memory(
    user_id: UserId,
    body: WorkingMemoryRequest,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return await manager.working.upsert(
        user_id,
        str(body.conversation_id),
        body.memory_key,
        body.value,
        body.purpose,
        body.expires_at,
    )


# List active working-memory items for one conversation.
@router.get("/{user_id}/agent/working/{conversation_id}")
async def list_working_memory(
    user_id: UserId,
    conversation_id: uuid.UUID,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return {"items": await manager.working.list_active(user_id, str(conversation_id))}


# Approve a new version of a reusable procedure.
@router.post("/{user_id}/agent/procedures", status_code=status.HTTP_201_CREATED)
async def approve_procedure(
    user_id: UserId,
    body: ProcedureRequest,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return await manager.procedures.approve(
        user_id,
        body.name,
        body.description,
        body.steps,
        str(body.source_conversation_id) if body.source_conversation_id else None,
        str(body.source_trace_id),
        body.expires_at,
        body.metadata,
    )


# Search approved procedures by meaning.
@router.get("/{user_id}/agent/procedures/search")
async def search_procedures(
    user_id: UserId,
    manager: DependencyAgentMemoryManager,
    query: str = Query(min_length=1, max_length=10_000),
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    return {"procedures": await manager.procedures.search(user_id, query, top_k)}


# Create or update an approved entity.
@router.put("/{user_id}/agent/entities")
async def upsert_entity(
    user_id: UserId,
    body: EntityRequest,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return await manager.entities.upsert(
        user_id,
        body.entity_type,
        body.canonical_name,
        body.attributes,
        str(body.source_conversation_id) if body.source_conversation_id else None,
        str(body.source_trace_id),
        body.expires_at,
    )


# Search approved entities by meaning.
@router.get("/{user_id}/agent/entities/search")
async def search_entities(
    user_id: UserId,
    manager: DependencyAgentMemoryManager,
    query: str = Query(min_length=1, max_length=10_000),
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    return {"entities": await manager.entities.search(user_id, query, top_k)}


# Create or update a relationship between two user-owned entities.
@router.post("/{user_id}/agent/entity-relations", status_code=201)
async def relate_entities(
    user_id: UserId,
    body: EntityRelationRequest,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    try:
        return await manager.entities.relate(
            user_id,
            str(body.source_entity_id),
            str(body.target_entity_id),
            body.relation_type,
            body.attributes,
            str(body.source_trace_id),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Ingest and embed a user knowledge document.
@router.post("/{user_id}/agent/knowledge", status_code=201)
async def ingest_knowledge(
    user_id: UserId,
    body: KnowledgeDocumentRequest,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return await manager.knowledge.ingest(
        user_id,
        body.title,
        body.content,
        body.source_uri,
        body.purpose,
        str(body.source_conversation_id) if body.source_conversation_id else None,
        str(body.source_trace_id) if body.source_trace_id else None,
    )


# Search embedded knowledge chunks by meaning.
@router.get("/{user_id}/agent/knowledge/search")
async def search_knowledge(
    user_id: UserId,
    manager: DependencyAgentMemoryManager,
    query: str = Query(min_length=1, max_length=10_000),
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    return {"chunks": await manager.knowledge.search(user_id, query, top_k)}


# Delete one user-owned knowledge document and its chunks.
@router.delete("/{user_id}/agent/knowledge/{document_id}")
async def delete_knowledge(
    user_id: UserId,
    document_id: uuid.UUID,
    manager: DependencyAgentMemoryManager,
) -> dict[str, bool]:
    if not await manager.knowledge.delete(user_id, str(document_id)):
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {"deleted": True}


# Save an embedded conversation summary.
@router.put("/{user_id}/agent/summaries")
async def save_summary(
    user_id: UserId,
    body: SummaryRequest,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return await manager.summaries.save(
        user_id,
        str(body.conversation_id),
        body.content,
        body.through_turn_count,
        str(body.source_trace_id),
    )


# Search conversation summaries by meaning.
@router.get("/{user_id}/agent/summaries/search")
async def search_summaries(
    user_id: UserId,
    manager: DependencyAgentMemoryManager,
    query: str = Query(min_length=1, max_length=10_000),
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    return {"summaries": await manager.summaries.search(user_id, query, top_k)}


# Return the latest summary for one conversation.
@router.get("/{user_id}/agent/summaries/{conversation_id}")
async def latest_summary(
    user_id: UserId,
    conversation_id: uuid.UUID,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return {"summary": await manager.summaries.latest(user_id, str(conversation_id))}


# Delete all agent-memory records owned by one user.
@router.delete("/{user_id}/agent")
async def delete_agent_memory(
    user_id: UserId,
    manager: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    return {"deleted": await manager.delete_all(user_id)}


# Delete one supported agent-memory record owned by a user.
@router.delete("/{user_id}/agent/{memory_type}/{memory_id}")
async def delete_agent_memory_record(
    user_id: UserId,
    memory_type: Literal[
        "cache",
        "working",
        "procedures",
        "entities",
        "entity_relations",
        "summaries",
    ],
    memory_id: uuid.UUID,
    manager: DependencyAgentMemoryManager,
) -> dict[str, bool]:
    if not await manager.delete_record(user_id, memory_type, str(memory_id)):
        raise HTTPException(status_code=404, detail="Agent memory record not found")
    return {"deleted": True}
