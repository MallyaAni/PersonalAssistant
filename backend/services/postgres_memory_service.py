import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.core.interfaces import MemoryService
from backend.embeddings.base import EmbeddingProvider
from backend.memory.repository import MemoryRepository
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.models.memory import UserProfile


class PostgresMemoryService(MemoryService):
    def __init__(
        self,
        session: Session,
        embeddings: EmbeddingProvider,
        retrieval_policy: SemanticRetrievalPolicy | None = None,
        embedding_model_version: str = "unknown",
    ):
        self.repo = MemoryRepository(session)
        self.embeddings = embeddings
        self.retrieval_policy = retrieval_policy or SemanticRetrievalPolicy()
        self.embedding_model_version = embedding_model_version

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        profile = await self.repo.get_user_profile(user_id)
        if not profile:
            # Fallback/Default if no profile exists
            return {"user_id": user_id, "preferences": {}}
        result = profile.to_dict()
        if await self.repo.has_fact_history(user_id, "preferred_name"):
            current_name = await self.repo.get_current_fact(user_id, "preferred_name")
            result["name"] = current_name.value if current_name else None
        return result

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        return await self.repo.save_user_profile(profile)

    async def upsert_user_profile(
        self,
        user_id: str,
        name: str | None,
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        profile = await self.repo.upsert_user_profile(user_id, name, preferences)
        return profile.to_dict()

    async def approve_preferred_name(
        self,
        user_id: str,
        name: str,
        source_conversation_id: str,
        source_trace_id: str,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        profile, fact = await self.repo.approve_preferred_name_fact(
            user_id,
            name,
            source_conversation_id,
            source_trace_id,
            expires_at,
        )
        return {"profile": profile.to_dict(), "fact": fact.to_dict()}

    async def clear_preferred_name(self, user_id: str) -> dict[str, Any]:
        profile = await self.repo.clear_preferred_name_facts(user_id)
        if profile is None:
            return {"user_id": user_id, "preferences": {}}
        return profile.to_dict()

    async def get_episodic_memory(
        self,
        user_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        memories = await self.repo.get_episodic_memories(user_id, limit=5)
        return [m.to_dict() for m in memories]

    async def get_semantic_memory(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        query_embedding = await asyncio.to_thread(self.embeddings.embed_query, query)
        memories = await self.repo.get_semantic_memories(
            user_id,
            query_embedding,
            min(top_k, self.retrieval_policy.max_results),
            self.retrieval_policy.max_cosine_distance,
        )
        return self.retrieval_policy.select(memories, top_k)

    async def save_episodic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        memory = await self.repo.save_episodic_memory(
            content,
            user_id,
            metadata,
            purpose,
            expires_at,
        )
        return memory.to_dict()

    async def save_semantic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        embedding = await asyncio.to_thread(self.embeddings.embed_text, content)
        memory = await self.repo.save_semantic_memory(
            user_id,
            content,
            embedding,
            metadata,
            purpose,
            getattr(self.embeddings, "model", "unknown"),
            self.embedding_model_version,
            len(embedding),
            expires_at,
        )
        return memory.to_dict()

    async def update_memory(
        self,
        user_id: str,
        memory_type: str,
        memory_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        embedding = None
        if memory_type == "semantic":
            embedding = await asyncio.to_thread(self.embeddings.embed_text, content)
        memory = await self.repo.update_memory(
            user_id,
            memory_type,
            memory_id,
            content,
            metadata,
            embedding,
        )
        return memory.to_dict() if memory else None

    async def get_memory_snapshot(self, user_id: str) -> dict[str, Any]:
        profile = await self.get_user_profile(user_id)
        episodic = [
            memory.to_dict()
            for memory in await self.repo.get_episodic_memories(user_id)
        ]
        semantic = [
            memory.to_dict()
            for memory in await self.repo.list_semantic_memories(user_id)
        ]
        facts = [fact.to_dict() for fact in await self.repo.list_memory_facts(user_id)]
        return {
            "profile": profile,
            "episodic": episodic,
            "semantic": semantic,
            "facts": facts,
        }

    async def get_user_export(self, user_id: str) -> dict[str, Any]:
        return {
            "memory": await self.get_memory_snapshot(user_id),
            "conversations": [
                conversation.to_dict()
                for conversation in await self.repo.list_conversations(user_id)
            ],
        }

    async def delete_memory(
        self,
        user_id: str,
        memory_type: str,
        memory_id: str,
    ) -> bool:
        return await self.repo.delete_memory(user_id, memory_type, memory_id)

    async def delete_all_user_memory(self, user_id: str) -> dict[str, int]:
        return await self.repo.delete_all_user_memory(user_id)
