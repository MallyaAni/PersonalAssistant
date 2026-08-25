import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config.settings import settings
from backend.core.auth import authorize_path_user
from backend.core.dependencies import (
    ArtifactDeletionDependency,
    DbDependency,
    DependencyAgentMemoryManager,
    DependencyMemoryService,
)
from backend.discovery.projection import interest_fact, locality_fact
from backend.discovery.types import MAX_LABEL_CHARS, MAX_REGION_CHARS
from backend.memory.errors import MemoryConflictError
from backend.services.artifact_deletion_service import ArtifactDeletionError

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


class DiscoveryInterestApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)
    source_conversation_id: uuid.UUID
    source_trace_id: uuid.UUID

    # Trim an approved interest and reject blank text.
    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class DiscoveryInterestsApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: list[str] = Field(min_length=1, max_length=8)
    source_conversation_id: uuid.UUID
    source_trace_id: uuid.UUID

    # Trim every proposed topic and reject blank or oversized labels.
    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > MAX_LABEL_CHARS for value in normalized):
            raise ValueError("interest labels must be non-blank and within bounds")
        return normalized


class DiscoveryLocalityApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)
    region: str | None = Field(default=None, max_length=MAX_REGION_CHARS)
    source_conversation_id: uuid.UUID
    source_trace_id: uuid.UUID

    # Trim an approved locality label and reject blank text.
    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    # Normalize an optional locality region before persistence.
    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        normalized = value.strip() if value is not None else ""
        return normalized or None


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
    return await service.get_memory_snapshot(
        user_id, limit=settings.MEMORY_SNAPSHOT_MAX_ITEMS
    )


# Export all personal, agent, and tool memory for one user.
@router.get("/{user_id}/export")
async def export_memory(
    user_id: UserId,
    service: DependencyMemoryService,
    agent_memory: DependencyAgentMemoryManager,
    db: DbDependency,
) -> dict[str, Any]:
    from sqlalchemy import select

    from backend.models.auth import AccessRequest

    exported = await service.get_user_export(user_id)
    # The number given at sign-up outlives approval on the access-request row
    # (the subscriber copy can be revoked and deleted independently of it), so
    # an export without this section would claim the system holds less about
    # the person than it does. Null when the account predates phone sign-up.
    request = await db.scalar(
        select(AccessRequest).where(
            AccessRequest.desired_username == user_id,
            AccessRequest.status == "approved",
        )
    )
    return {
        "schema_version": 3,
        "exported_at": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        "sign_up": (
            {
                "display_name": request.display_name,
                "phone": request.phone,
                "contact": request.contact,
            }
            if request is not None
            else None
        ),
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


# Approve a chat-proposed interest and atomically project it into Scout's profile.
@router.post("/{user_id}/profile/discovery-interest", status_code=201)
async def approve_discovery_interest(
    user_id: UserId,
    body: DiscoveryInterestApprovalRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    fact = interest_fact(body.label)
    try:
        return await service.approve_fact(
            user_id=user_id,
            fact_type=fact.fact_type,
            fact_key=fact.fact_key,
            value=fact.value,
            purpose=fact.purpose,
            source_conversation_id=str(body.source_conversation_id),
            source_trace_id=str(body.source_trace_id),
            expires_at=None,
            metadata={"source": "chat_approval"},
        )
    except MemoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Approve one semantic list and project every interest in one transaction.
@router.post("/{user_id}/profile/discovery-interests", status_code=201)
async def approve_discovery_interests(
    user_id: UserId,
    body: DiscoveryInterestsApprovalRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    try:
        return await service.approve_discovery_interests(
            user_id=user_id,
            labels=body.labels,
            source_conversation_id=str(body.source_conversation_id),
            source_trace_id=str(body.source_trace_id),
        )
    except MemoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Approve a chat-proposed home locality and atomically configure Scout's primary place.
@router.post("/{user_id}/profile/discovery-locality", status_code=201)
async def approve_discovery_locality(
    user_id: UserId,
    body: DiscoveryLocalityApprovalRequest,
    service: DependencyMemoryService,
) -> dict[str, Any]:
    fact = locality_fact(body.label, body.region)
    try:
        return await service.approve_fact(
            user_id=user_id,
            fact_type=fact.fact_type,
            fact_key=fact.fact_key,
            value=fact.value,
            purpose=fact.purpose,
            source_conversation_id=str(body.source_conversation_id),
            source_trace_id=str(body.source_trace_id),
            expires_at=None,
            metadata={"source": "chat_approval"},
        )
    except MemoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    artifacts: ArtifactDeletionDependency,
) -> dict[str, dict[str, int]]:
    deleted = await service.delete_all_user_memory(user_id)
    deleted.update(await agent_memory.delete_all(user_id))
    try:
        deleted["artifacts"] = await artifacts.delete_all_owned(user_id)
    except ArtifactDeletionError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Memory records were deleted, but some artifact files could not "
                "be removed. Run storage collection before retrying."
            ),
        ) from exc
    return {"deleted": deleted}
