from typing import Annotated, List, Dict, Any, TypedDict, Optional
from pydantic import BaseModel, Field
import uuid

class AgentState(BaseModel):
    """The state object for the AssistantGraph."""
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    current_query: str
    history: List[Dict[str, Any]] = []
    context_data: Dict[str, Any] = {}
    assistant_response: Optional[str] = None
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

# This will be used for LangGraph's state management
class GraphState(TypedDict):
    # Using TypedDict here as it is often required by some LangGraph patterns 
    # while keeping our core models in Pydantic.
    conversation_id: str
    user_id: str
    current_query: str
    history: List[Dict[str, Any]]
    context_data: Dict[str, Any]
    assistant_response: Optional[str]
    trace_id: str

    @classmethod
    def from_pydantic(cls, pydantic_obj: AgentState) -> "GraphState":
        return cls(**pydantic_obj.model_dump())