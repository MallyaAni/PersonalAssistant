import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.auth import authorize_path_user
from backend.core.dependencies import (
    DependencyAgentMemoryManager,
    DependencyMemoryService,
)
from backend.memory.errors import MemoryConflictError

router = APIRouter(
    prefix="/memory",
    tags=["memory"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, Path(min_length=1, max_length=50)]


class ProfileRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    preferences: dict[str, Any] = Field(default_factory=dict)


class MemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    purpose: str = Field(default="user_explicit", min_length=1, max_length=100)
    expires_at: datetime | None = None

    # Trim memory text fields and reject blank values.
    @field_validator("content", "purpose")
    @classmethod
    def normalize_memory_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    # Require an optional memory expiry to be timezone-aware and future-dated.
    @field_validator("expires_at")
    @classmethod
    def require_future_memory_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone")
        if value <= datetime.now(UTC):
            raise ValueError("must be in the future")
        return value


class PreferredNameApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    source_conversation_id: uuid.UUID
    source_trace_id: uuid.UUID
    expires_at: datetime | None = None

    # Trim a preferred name and reject blank text.
    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    # Require an optional fact expiry to be timezone-aware and future-dated.
    @field_validator("expires_at")
    @classmethod
    def require_future_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone")
        if value <= datetime.now(UTC):
            raise ValueError("must be in the future")
        return value


class FactApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,49}$")
    fact_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")
    value: str = Field(min_length=1, max_length=10_000)
    purpose: str = Field(min_length=1, max_length=100)
    source_conversation_id: uuid.UUID | None = None
    source_trace_id: uuid.UUID
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Trim required fact text and reject blank values.
    @field_validator("value", "purpose")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    # Reuse the preferred-name expiry validation for a fact.
    @field_validator("expires_at")
    @classmethod
    def require_future_expiry(cls, value: datetime | None) -> datetime | None:
        return PreferredNameApprovalRequest.require_future_expiry(value)


class FactCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=10_000)
    source_conversation_id: uuid.UUID | None = None
    source_trace_id: uuid.UUID
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Trim a corrected fact value and reject blank text.
    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    # Reuse the preferred-name expiry validation for a correction.
    @field_validator("expires_at")
    @classmethod
    def require_future_expiry(cls, value: datetime | None) -> datetime | None:
        return PreferredNameApprovalRequest.require_future_expiry(value)


# Return a combined personal-memory snapshot for one user.
@router.get("/{user_id}")
async def get_memory_snapshot(
    user_id: UserId,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    return await service.get_memory_snapshot(user_id)


# Export all personal, agent, and tool memory for one user.
@router.get("/{user_id}/export")
async def export_memory(
    user_id: UserId,
    service: DependencyMemoryService,
    agent_memory: DependencyAgentMemoryManager,
) -> dict[str, Any]:
    exported = await service.get_user_export(user_id)
    return {
        "schema_version": 2,
        "exported_at": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        "agent_memory": await agent_memory.export(user_id),
        **exported,
    }


# Create or update the user's profile projection.
@router.put("/{user_id}/profile")
async def upsert_profile(
    user_id: UserId,
    body: ProfileRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    return await service.upsert_user_profile(
        user_id,
        body.name,
        body.preferences,
    )


# Approve a preferred-name fact and update the profile projection.
@router.post("/{user_id}/profile/preferred-name")
async def approve_preferred_name(
    user_id: UserId,
    body: PreferredNameApprovalRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    try:
        return await service.approve_preferred_name(
            user_id,
            body.name,
            str(body.source_conversation_id),
            str(body.source_trace_id),
            body.expires_at,
        )
    except MemoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Remove preferred-name facts and clear the profile projection.
@router.delete("/{user_id}/profile/preferred-name")
async def clear_preferred_name(
    user_id: UserId,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    return await service.clear_preferred_name(user_id)


# Approve and persist a typed personal-memory fact.
@router.post("/{user_id}/facts", status_code=201)
async def approve_fact(
    user_id: UserId,
    body: FactApprovalRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    try:
        return await service.approve_fact(
            user_id=user_id,
            fact_type=body.fact_type,
            fact_key=body.fact_key,
            value=body.value,
            purpose=body.purpose,
            source_conversation_id=(
                str(body.source_conversation_id)
                if body.source_conversation_id is not None
                else None
            ),
            source_trace_id=str(body.source_trace_id),
            expires_at=body.expires_at,
            metadata=body.metadata,
        )
    except MemoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Replace an existing fact with a newly approved correction.
@router.put("/{user_id}/facts/{fact_id}")
async def correct_fact(
    user_id: UserId,
    fact_id: uuid.UUID,
    body: FactCorrectionRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    try:
        result = await service.correct_fact(
            user_id=user_id,
            fact_id=str(fact_id),
            value=body.value,
            source_conversation_id=(
                str(body.source_conversation_id)
                if body.source_conversation_id is not None
                else None
            ),
            source_trace_id=str(body.source_trace_id),
            expires_at=body.expires_at,
            metadata=body.metadata,
        )
    except MemoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return result


# Delete one fact owned by the requested user.
@router.delete("/{user_id}/facts/{fact_id}")
async def delete_fact(
    user_id: UserId,
    fact_id: uuid.UUID,
    service: DependencyMemoryService,
) -> dict[str, bool]:
    if not await service.delete_fact(user_id, str(fact_id)):
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"deleted": True}


# Delete every fact for one user and fact key.
@router.delete("/{user_id}/facts/key/{fact_key}")
async def clear_fact_key(
    user_id: UserId,
    fact_key: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{0,99}$")],
    service: DependencyMemoryService,
) -> dict[str, int]:
    return {"deleted": await service.clear_fact_key(user_id, fact_key)}


# Save one explicit episodic memory for a user.
@router.post("/{user_id}/episodic", status_code=201)
async def create_episodic_memory(
    user_id: UserId,
    body: MemoryRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    return await service.save_episodic_memory(
        user_id,
        body.content,
        body.metadata,
        body.purpose,
        body.expires_at,
    )


# Save and embed one explicit semantic memory for a user.
@router.post("/{user_id}/semantic", status_code=201)
async def create_semantic_memory(
    user_id: UserId,
    body: MemoryRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    return await service.save_semantic_memory(
        user_id,
        body.content,
        body.metadata,
        body.purpose,
        body.expires_at,
    )


# Retrieve semantic memories relevant to a query.
@router.get("/{user_id}/search")
async def search_semantic_memory(
    user_id: UserId,
    service: DependencyMemoryService,
    query: str = Query(min_length=1, max_length=10_000),
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict[str, list[dict[str, Any]]]:
    return {"memories": await service.get_semantic_memory(user_id, query, top_k)}


# Delete one episodic or semantic memory owned by a user.
@router.delete("/{user_id}/{memory_type}/{memory_id}")
async def delete_memory(
    user_id: UserId,
    memory_type: Literal["episodic", "semantic"],
    memory_id: uuid.UUID,
    service: DependencyMemoryService,
) -> dict[str, bool]:
    deleted = await service.delete_memory(user_id, memory_type, str(memory_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": True}


# Update one episodic or semantic memory owned by a user.
@router.put("/{user_id}/{memory_type}/{memory_id}")
async def update_memory(
    user_id: UserId,
    memory_type: Literal["episodic", "semantic"],
    memory_id: uuid.UUID,
    body: MemoryRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    memory = await service.update_memory(
        user_id,
        memory_type,
        str(memory_id),
        body.content,
        body.metadata,
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


# Delete all memory categories owned by one user.
@router.delete("/{user_id}")
async def delete_all_user_memory(
    user_id: UserId,
    service: DependencyMemoryService,
    agent_memory: DependencyAgentMemoryManager,
) -> dict[str, dict[str, int]]:
    deleted = await service.delete_all_user_memory(user_id)
    deleted.update(await agent_memory.delete_all(user_id))
    return {"deleted": deleted}
