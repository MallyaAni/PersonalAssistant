from typing import Any, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=50)
    conversation_id: UUID | None = None
    active_image_artifact_id: UUID | None = None
    query: str = Field(min_length=1, max_length=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("user_id", "query")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ObserveRequest(BaseModel):
    """A group message read for context, not answered: stored as a turn with
    no reply, and classified for memory the way an answered turn is."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=50)
    conversation_id: UUID | None = None
    query: str = Field(min_length=1, max_length=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReadinessRequest(BaseModel):
    """What a texting client has received since its last reply, to be judged."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=50)
    fragments: list[str] = Field(min_length=1, max_length=12)
    previous_reply: str = Field(default="", max_length=4_000)
    in_group: bool = False
    # How it reached the assistant: reply, mention, name, positive tapback, or none.
    addressed_by: str = Field(default="", max_length=20)


class ChatStreamEvent(TypedDict):
    event: Literal[
        "start",
        "action",
        "delta",
        "memory_proposal",
        "artifact_started",
        "artifact_ready",
        "artifact_error",
        "image_matches",
        "search_started",
        "search_results",
        "search_blocked",
        "tool_started",
        "tool_finished",
        "agent_started",
        "agent_finished",
        "done",
    ]
    data: dict[str, Any]
