import uuid
from typing import Any

from backend.core.interfaces import (
    ConversationRepository,
    ConversationTracer,
    MemoryService,
)


class StubMemoryService(MemoryService):
    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "preferences": {}}

    async def get_episodic_memory(
        self,
        user_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        return []

    async def get_semantic_memory(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return []


class StubConversationRepository(ConversationRepository):
    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return []

    async def save_turn(
        self,
        conversation_id: str,
        turn: dict[str, Any],
    ) -> None:
        return None

    # Report no persisted turns for tests that use this repository double.
    async def count_turns(self, conversation_id: str, user_id: str) -> int:
        return 0


class StubTracer(ConversationTracer):
    def start_trace(self, user_id: str) -> str:
        return str(uuid.uuid4())

    def log_step(
        self,
        trace_id: str,
        step_name: str,
        metadata: dict[str, Any],
    ) -> None:
        return None
