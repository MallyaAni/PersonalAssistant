from typing import List, Dict, Any, AsyncGenerator
from fastapi.responses import StreamingResponse
from backend.core.interfaces import (
    MemoryService, 
    KnowledgeService, 
    InternetService, 
    NotificationService, 
    ToolService,
    ConversationRepository,
    ConversationContextBuilder,
    ConversationStreamer,
    ConversationTracer
)

class MockMemoryService(MemoryService):
    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        return {"user_id": user_id, "preferences": {}}

    async def get_episodic_memory(self, user_id: str, query: str) -> List[Dict[str, Any]]:
        return []

    async def get_semantic_memory(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return []

    async def save_conversation(self, conversation_id: str, turn: Dict[str, Any]) -> None:
        pass

class MockKnowledgeService(KnowledgeService):
    async def query_knowledge(self, query: str) -> List[Dict[str, Any]]:
        return []

class MockInternetService(InternetService):
    async def search(self, query: str) -> List[Dict[str, Any]]:
        return []

class MockNotificationService(NotificationService):
    async def notify(self, user_id: str, message: str) -> None:
        pass

class MockToolService(ToolService):
    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "output": "Mock execution"}

class MockConversationRepository(ConversationRepository):
    async def get_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        return []

    async def save_turn(self, conversation_id: str, turn: Dict[str, Any]) -> None:
        pass

class MockContextBuilder(ConversationContextBuilder):
    def build_context(self, user_id: str, query: str) -> Dict[str, Any]:
        return {"user_id": user_id, "query": query}

class MockStreamer(ConversationStreamer):
    async def stream_response(self, generator: AsyncGenerator[str, None]) -> StreamingResponse:
        from fastapi.responses import StreamingResponse
        return StreamingResponse(generator, media_type="text/event-stream")

class MockTracer(ConversationTracer):
    def start_trace(self, user_id: str) -> str:
        import uuid
        return str(uuid.uuid4())

    def log_step(self, trace_id: str, step_name: str, metadata: Dict[str, Any]):
        print(f"Trace {trace_id} | Step {step_name}: {metadata}")