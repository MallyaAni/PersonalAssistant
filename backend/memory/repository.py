from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.future import select
from sqlalchemy import text

from backend.models.memory import UserProfile, EpisodicMemory, SemanticMemory

class MemoryRepository:
    def __init__(self, session: Session):
        self.session = session

    async def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        query = select(UserProfile).where(UserProfile.user_id == user_id)
        result = self.session.execute(query)
        return result.scalar_one_or_none()

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        self.session.add(profile)
        self.session.commit()
        self.session.refresh(profile)
        return profile

    async def get_episodic_memories(self, user_id: str, query: str) -> List[EpisodicMemory]:
        # For now, we'll fetch all for a user; later this can be more nuanced search
        query_stmt = select(EpisodicMemory).where(EpisodicMemory.user_id == user_id)
        result = self.session.execute(query_stmt)
        return list(result.scalars().all())

    async def save_episodic_memory(self, content: str, user_id: str, metadata: Dict[str, Any]) -> EpisodicMemory:
        new_mem = EpisodicMemory(user_id=user_id, content=content, metadata=metadata)
        self.session.add(new_mem)
        self.session.commit()
        self.session.refresh(new_mem)
        return new_mem

    async def get_semantic_memories(self, query_embedding: List[float], top_k: int = 5) -> List[SemanticMemory]:
        # Using pgvector similarity search (<=> is cosine distance)
        stmt = select(SemanticMemory).order_by(SemanticMemory.embedding.cosine_distance(query_embedding)).limit(top_k)
        result = self.session.execute(stmt)
        return list(result.scalars().all())

    async def save_semantic_memory(self, content: str, embedding: List[float], metadata: Dict[str, Any]) -> SemanticMemory:
        new_mem = SemanticMemory(content=content, embedding=embedding, metadata=metadata)
        self.session.add(new_mem)
        self.session.commit()
        self.session.refresh(new_mem)
        return new_mem

    async def delete_memory(self, memory_id: str) -> bool:
        # Logic to delete from any of the three types based on ID lookup 
        # Simplified for now as we assume distinct IDs or specific table calls
        pass
