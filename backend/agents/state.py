import uuid
from typing import Any

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """The state object for the AssistantGraph."""

    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    current_query: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    context_data: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
