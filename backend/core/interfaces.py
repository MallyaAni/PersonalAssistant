from abc import ABC, abstractmethod
from typing import Any


class MemoryService(ABC):
    @abstractmethod
    async def get_user_profile(self, user_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def get_episodic_memory(
        self,
        user_id: str,
        query: str,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_semantic_memory(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]: ...


class ConversationRepository(ABC):
    @abstractmethod
    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def save_turn(
        self,
        conversation_id: str,
        turn: dict[str, Any],
    ) -> None: ...


class ConversationTracer(ABC):
    @abstractmethod
    def start_trace(self, user_id: str) -> str: ...

    @abstractmethod
    def log_step(
        self,
        trace_id: str,
        step_name: str,
        metadata: dict[str, Any],
    ) -> None: ...
