from typing import List, Dict, Any, Optional
from backend.core.interfaces import MemoryService
from backend.memory.repository import MemoryRepository
from sqlalchemy.orm import Session

class PostgresMemoryService(MemoryService):
    def __init__(self, session: Session):
        self.repo = MemoryRepository(session)

    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        profile = await self.repo.get_user_profile(user_id)
        if not profile:
            # Fallback/Default if no profile exists
            return {"user_id": user_id, "preferences": {}}
        return profile.to_dict()

    async def get_episodic_memory(self, user_id: str, query: str) -> List[Dict[str, Any]]:
        # For now, retrieving all for simplicity as per repository current state
        # Future: filter by content relevance or timestamp
        memories = await self.repo.get_episodic_memories(user_id, query)
        return [m.to_dict() for m in memories]

    async def get_semantic_memory(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        # NOTE: In a full implementation, we would call an EmbeddingService here
        # to convert the string 'query' into a vector before calling repo.get_semantic_memories.
        # For now, we return empty as we don't have the embedding logic wired yet.
        return []

    async def save_conversation(self, conversation_id: str, turn: Dict[str, Any]) -> None:
        # This is part of MemoryService interface but often maps to ConversationRepository
        # We'll leave it as a no-op or bridge to a repository if needed.
        pass

    async def save_episodic_memory(self, user_id: str, content: str, metadata: Dict[str, Any]) -> None:
        await self.repo.save_episodic_memory(content, user_id, metadata)

    async def save_semantic_memory(self, content: str, embedding: List[float], metadata: Dict[str, Any]) -> None:
        await self.repo.save_semantic_memory(content, embedding, metadata)
