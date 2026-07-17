from typing import Any, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=50)
    conversation_id: UUID | None = None
    query: str = Field(min_length=1, max_length=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("user_id", "query")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ChatStreamEvent(TypedDict):
    event: Literal["start", "delta", "memory_proposal", "done"]
    data: dict[str, Any]
