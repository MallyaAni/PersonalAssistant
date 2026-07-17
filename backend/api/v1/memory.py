import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.auth import authorize_path_user
from backend.core.dependencies import DependencyMemoryService
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

    @field_validator("content", "purpose")
    @classmethod
    def normalize_memory_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

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

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

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


@router.get("/{user_id}")
async def get_memory_snapshot(
    user_id: UserId,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    return await service.get_memory_snapshot(user_id)


@router.get("/{user_id}/export")
async def export_memory(
    user_id: UserId,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    exported = await service.get_user_export(user_id)
    return {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        **exported,
    }


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


@router.delete("/{user_id}/profile/preferred-name")
async def clear_preferred_name(
    user_id: UserId,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    return await service.clear_preferred_name(user_id)


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


@router.get("/{user_id}/search")
async def search_semantic_memory(
    user_id: UserId,
    service: DependencyMemoryService,
    query: str = Query(min_length=1, max_length=10_000),
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict[str, list[dict[str, Any]]]:
    return {"memories": await service.get_semantic_memory(user_id, query, top_k)}


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


@router.delete("/{user_id}")
async def delete_all_user_memory(
    user_id: UserId,
    service: DependencyMemoryService,
) -> dict[str, dict[str, int]]:
    return {"deleted": await service.delete_all_user_memory(user_id)}
