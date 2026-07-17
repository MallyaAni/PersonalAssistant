import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.auth import authorize_path_user
from backend.core.dependencies import DependencyToolMemoryService
from backend.services.tool_memory_service import reject_sensitive_tool_memory

router = APIRouter(
    prefix="/memory",
    tags=["tool-memory"],
    dependencies=[Depends(authorize_path_user)],
)
UserId = Annotated[str, Path(min_length=1, max_length=50)]


class ToolDescriptorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str = Field(min_length=1, max_length=200)
    tool_name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    input_purpose: str = Field(min_length=1, max_length=1_000)
    schema_fingerprint: str = Field(min_length=64, max_length=64)
    tool_version: str = Field(min_length=1, max_length=100)
    risk_classification: Literal["read_only", "write", "high_impact"]

    @field_validator(
        "server_id", "tool_name", "description", "input_purpose", "tool_version"
    )
    @classmethod
    def reject_sensitive_descriptor_text(cls, value: str) -> str:
        return reject_sensitive_tool_memory(value)

    @field_validator("schema_fingerprint")
    @classmethod
    def require_sha256_fingerprint(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("must be a SHA-256 hex fingerprint")
        return value.lower()


class ToolPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str = Field(min_length=1, max_length=200)
    tool_name: str = Field(min_length=1, max_length=200)
    preference_key: Literal["preferred_for", "default_scope", "display_label"]
    value: str = Field(min_length=1, max_length=500)
    purpose: str = Field(default="tool_personalization", min_length=1, max_length=100)
    source_trace_id: uuid.UUID
    expires_at: datetime | None = None

    @field_validator("server_id", "tool_name", "value", "purpose")
    @classmethod
    def reject_sensitive_preference_text(cls, value: str) -> str:
        return reject_sensitive_tool_memory(value)

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


class ToolOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str = Field(min_length=1, max_length=200)
    tool_name: str = Field(min_length=1, max_length=200)
    outcome_category: Literal["success", "failure", "cancelled", "denied"]
    source_trace_id: uuid.UUID


@router.post("/{user_id}/tools/descriptors", status_code=201)
async def upsert_tool_descriptor(
    user_id: UserId,
    body: ToolDescriptorRequest,
    service: DependencyToolMemoryService,
) -> dict[str, Any]:
    return await service.upsert_descriptor(user_id, **body.model_dump())


@router.get("/{user_id}/tools/search")
async def search_tool_descriptors(
    user_id: UserId,
    service: DependencyToolMemoryService,
    query: str = Query(min_length=1, max_length=2_000),
    server_id: str | None = Query(default=None, min_length=1, max_length=200),
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    return {
        "descriptors": await service.search_descriptors(
            user_id, query, server_id, top_k
        )
    }


@router.post("/{user_id}/tools/preferences", status_code=201)
async def save_tool_preference(
    user_id: UserId,
    body: ToolPreferenceRequest,
    service: DependencyToolMemoryService,
) -> dict[str, Any]:
    try:
        return await service.save_preference(
            user_id,
            body.server_id,
            body.tool_name,
            body.preference_key,
            body.value,
            body.purpose,
            str(body.source_trace_id),
            body.expires_at,
        )
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{user_id}/tools/outcomes", status_code=201)
async def record_tool_outcome(
    user_id: UserId,
    body: ToolOutcomeRequest,
    service: DependencyToolMemoryService,
) -> dict[str, Any]:
    try:
        return await service.record_outcome(
            user_id,
            body.server_id,
            body.tool_name,
            body.outcome_category,
            str(body.source_trace_id),
        )
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{user_id}/tools")
async def get_tool_memory(
    user_id: UserId,
    service: DependencyToolMemoryService,
) -> dict[str, Any]:
    return await service.snapshot(user_id)


@router.delete("/{user_id}/tools")
async def delete_tool_memory(
    user_id: UserId,
    service: DependencyToolMemoryService,
) -> dict[str, Any]:
    return {"deleted": await service.delete_all(user_id)}
