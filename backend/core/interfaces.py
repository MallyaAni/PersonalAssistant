from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator
from pydantic import BaseModel

class BaseResponse(BaseModel):
    content: str
    metadata: Dict[str, Any] = {}

class MemoryService(ABC):
    @abstractmethod
    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_episodic_memory(self, user_id: str, query: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_semantic_memory(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def save_conversation(self, conversation_id: str, turn: Dict[str, Any]) -> None:
        pass

class KnowledgeService(ABC):
    @abstractmethod
    async def query_knowledge(self, query: str) -> List[Dict[str, Any]]:
        pass

class InternetService(ABC):
    @abstractmethod
    async def search(self, query: str) -> List[Dict[str, Any]]:
        pass

class NotificationService(ABC):
    @abstractmethod
    async def notify(self, user_id: str, message: str) -> None:
        pass

class ToolService(ABC):
    @abstractmethod
    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        pass

# New interfaces for Conversation Engine
class ConversationRepository(ABC):
    @abstractmethod
    async def get_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def save_turn(self, conversation_id: str, turn: Dict[str, Any]) -> None:
        pass

class ConversationContextBuilder(ABC):
    @abstractmethod
    def build_context(self, user_id: str, query: str) -> Dict[str, Any]:
        pass

class ConversationStreamer(ABC):
    @abstractmethod
    async def stream_response(self, generator: AsyncGenerator[str, None]) -> Any:
        pass

class ConversationTracer(ABC):
    @abstractmethod
    def start_trace(self, user_id: str) -> str:
        pass

    @abstractmethod
    def log_step(self, trace_id: str, step_name: str, metadata: Dict[str, Any]):
        pass