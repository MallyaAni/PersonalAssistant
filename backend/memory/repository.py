import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from backend.memory.errors import MemoryConflictError
from backend.models.conversation import Conversation
from backend.models.memory import (
    EpisodicMemory,
    MemoryFact,
    SemanticMemory,
    UserProfile,
)
from backend.models.tool_memory import ToolDescriptor, ToolPreference, ToolUsageOutcome


class MemoryRepository:
    def __init__(self, session: Session):
        self.session = session

    async def get_user_profile(self, user_id: str) -> UserProfile | None:
        query = select(UserProfile).where(UserProfile.user_id == user_id)
        result = self.session.execute(query)
        return result.scalar_one_or_none()

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        self.session.add(profile)
        self.session.commit()
        self.session.refresh(profile)
        return profile

    async def upsert_user_profile(
        self,
        user_id: str,
        name: str | None,
        preferences: dict[str, Any],
    ) -> UserProfile:
        profile = await self.get_user_profile(user_id)
        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                name=name,
                preferences=preferences,
            )
            self.session.add(profile)
        else:
            profile.name = name
            profile.preferences = preferences
        self.session.commit()
        self.session.refresh(profile)
        return profile

    async def get_current_fact(
        self,
        user_id: str,
        fact_key: str,
        at: datetime | None = None,
    ) -> MemoryFact | None:
        effective_at = at or datetime.now(UTC)
        stmt = (
            select(MemoryFact)
            .where(
                MemoryFact.user_id == user_id,
                MemoryFact.fact_key == fact_key,
                MemoryFact.approval_state == "approved",
                or_(
                    MemoryFact.expires_at.is_(None),
                    MemoryFact.expires_at > effective_at,
                ),
            )
            .order_by(MemoryFact.version.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    async def has_fact_history(self, user_id: str, fact_key: str) -> bool:
        stmt = select(func.count(MemoryFact.id)).where(
            MemoryFact.user_id == user_id,
            MemoryFact.fact_key == fact_key,
        )
        return bool(self.session.execute(stmt).scalar_one())

    async def list_memory_facts(self, user_id: str) -> list[MemoryFact]:
        stmt = (
            select(MemoryFact)
            .where(MemoryFact.user_id == user_id)
            .order_by(
                MemoryFact.fact_key,
                MemoryFact.version.desc(),
            )
        )
        return list(self.session.execute(stmt).scalars().all())

    async def approve_preferred_name_fact(
        self,
        user_id: str,
        name: str,
        source_conversation_id: str,
        source_trace_id: str,
        expires_at: datetime | None,
    ) -> tuple[UserProfile, MemoryFact]:
        try:
            source_trace_uuid = uuid.UUID(source_trace_id)
            existing = self.session.execute(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.fact_key == "preferred_name",
                    MemoryFact.source_trace_id == source_trace_uuid,
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.normalized_value != name.strip().casefold():
                    raise MemoryConflictError(
                        "The source trace is already associated with another value"
                    )
                profile = await self.get_user_profile(user_id)
                if profile is None:
                    raise MemoryConflictError(
                        "The idempotent fact has no profile projection"
                    )
                return profile, existing

            facts = list(
                self.session.execute(
                    select(MemoryFact)
                    .where(
                        MemoryFact.user_id == user_id,
                        MemoryFact.fact_key == "preferred_name",
                    )
                    .order_by(MemoryFact.version.desc())
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            latest = facts[0] if facts else None
            for fact in facts:
                if fact.approval_state == "approved":
                    fact.approval_state = "superseded"

            memory_fact = MemoryFact(
                user_id=user_id,
                fact_type="profile",
                fact_key="preferred_name",
                value=name,
                normalized_value=name.strip().casefold(),
                approval_state="approved",
                confidence=1.0,
                purpose="personalization",
                source_conversation_id=uuid.UUID(source_conversation_id),
                source_trace_id=source_trace_uuid,
                version=(latest.version + 1) if latest else 1,
                supersedes_id=latest.id if latest else None,
                embedding_model=None,
                embedding_version=None,
                embedding_dimension=None,
                expires_at=expires_at,
                extra_data={"source": "chat_approval"},
            )
            self.session.add(memory_fact)

            profile = await self.get_user_profile(user_id)
            if profile is None:
                profile = UserProfile(user_id=user_id, name=name, preferences={})
                self.session.add(profile)
            else:
                profile.name = name

            self.session.commit()
            self.session.refresh(profile)
            self.session.refresh(memory_fact)
            return profile, memory_fact
        except Exception:
            self.session.rollback()
            raise

    async def clear_preferred_name_facts(self, user_id: str) -> UserProfile | None:
        try:
            self.session.execute(
                delete(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.fact_key == "preferred_name",
                )
            )
            profile = await self.get_user_profile(user_id)
            if profile is not None:
                profile.name = None
            self.session.commit()
            if profile is not None:
                self.session.refresh(profile)
            return profile
        except Exception:
            self.session.rollback()
            raise

    async def get_episodic_memories(
        self,
        user_id: str,
        limit: int | None = None,
    ) -> list[EpisodicMemory]:
        effective_at = datetime.now(UTC)
        stmt = (
            select(EpisodicMemory)
            .where(
                EpisodicMemory.user_id == user_id,
                or_(
                    EpisodicMemory.expires_at.is_(None),
                    EpisodicMemory.expires_at > effective_at,
                ),
            )
            .order_by(EpisodicMemory.timestamp.desc(), EpisodicMemory.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = self.session.execute(stmt)
        return list(result.scalars().all())

    async def save_episodic_memory(
        self,
        content: str,
        user_id: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: datetime | None = None,
    ) -> EpisodicMemory:
        new_mem = EpisodicMemory(
            user_id=user_id,
            content=content,
            purpose=purpose,
            expires_at=expires_at,
            extra_data=metadata,
        )
        self.session.add(new_mem)
        self.session.commit()
        self.session.refresh(new_mem)
        return new_mem

    async def get_semantic_memories(
        self,
        user_id: str,
        query_embedding: list[float],
        top_k: int = 5,
        max_cosine_distance: float = 0.35,
    ) -> list[tuple[SemanticMemory, float]]:
        distance = SemanticMemory.embedding.cosine_distance(query_embedding)
        effective_at = datetime.now(UTC)
        stmt = (
            select(SemanticMemory, distance.label("cosine_distance"))
            .where(
                SemanticMemory.user_id == user_id,
                or_(
                    SemanticMemory.expires_at.is_(None),
                    SemanticMemory.expires_at > effective_at,
                ),
                distance <= max_cosine_distance,
            )
            .order_by(distance, SemanticMemory.id)
            .limit(top_k)
        )
        result = self.session.execute(stmt)
        return [(memory, float(score)) for memory, score in result.all()]

    async def save_semantic_memory(
        self,
        user_id: str,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any],
        purpose: str,
        embedding_model: str,
        embedding_version: str,
        embedding_dimension: int,
        expires_at: datetime | None,
    ) -> SemanticMemory:
        new_mem = SemanticMemory(
            user_id=user_id,
            content=content,
            embedding=embedding,
            purpose=purpose,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            embedding_dimension=embedding_dimension,
            expires_at=expires_at,
            extra_data=metadata,
        )
        self.session.add(new_mem)
        self.session.commit()
        self.session.refresh(new_mem)
        return new_mem

    async def list_semantic_memories(self, user_id: str) -> list[SemanticMemory]:
        stmt = (
            select(SemanticMemory)
            .where(SemanticMemory.user_id == user_id)
            .order_by(SemanticMemory.created_at.desc())
        )
        result = self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_conversations(self, user_id: str) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at, Conversation.id)
        )
        return list(self.session.execute(stmt).scalars().all())

    async def update_memory(
        self,
        user_id: str,
        memory_type: str,
        memory_id: str,
        content: str,
        metadata: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> EpisodicMemory | SemanticMemory | None:
        memory: EpisodicMemory | SemanticMemory | None
        if memory_type == "episodic":
            memory = self.session.execute(
                select(EpisodicMemory).where(
                    EpisodicMemory.id == memory_id,
                    EpisodicMemory.user_id == user_id,
                )
            ).scalar_one_or_none()
        elif memory_type == "semantic":
            memory = self.session.execute(
                select(SemanticMemory).where(
                    SemanticMemory.id == memory_id,
                    SemanticMemory.user_id == user_id,
                )
            ).scalar_one_or_none()
        else:
            return None
        if memory is None:
            return None
        memory.content = content
        memory.extra_data = metadata
        if isinstance(memory, SemanticMemory):
            if embedding is None:
                raise ValueError("Semantic memory correction requires an embedding")
            memory.embedding = embedding
        self.session.commit()
        self.session.refresh(memory)
        return memory

    async def delete_memory(
        self,
        user_id: str,
        memory_type: str,
        memory_id: str,
    ) -> bool:
        if memory_type == "episodic":
            stmt = delete(EpisodicMemory).where(
                EpisodicMemory.id == memory_id,
                EpisodicMemory.user_id == user_id,
            )
        elif memory_type == "semantic":
            stmt = delete(SemanticMemory).where(
                SemanticMemory.id == memory_id,
                SemanticMemory.user_id == user_id,
            )
        else:
            return False
        result = self.session.execute(stmt)
        self.session.commit()
        return int(getattr(result, "rowcount", 0)) == 1

    async def delete_all_user_memory(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for name, stmt in (
            (
                "tool_outcomes",
                delete(ToolUsageOutcome).where(ToolUsageOutcome.user_id == user_id),
            ),
            (
                "tool_preferences",
                delete(ToolPreference).where(ToolPreference.user_id == user_id),
            ),
            (
                "tool_descriptors",
                delete(ToolDescriptor).where(ToolDescriptor.user_id == user_id),
            ),
            ("facts", delete(MemoryFact).where(MemoryFact.user_id == user_id)),
            ("profiles", delete(UserProfile).where(UserProfile.user_id == user_id)),
            (
                "episodic",
                delete(EpisodicMemory).where(EpisodicMemory.user_id == user_id),
            ),
            (
                "semantic",
                delete(SemanticMemory).where(SemanticMemory.user_id == user_id),
            ),
            (
                "conversations",
                delete(Conversation).where(Conversation.user_id == user_id),
            ),
        ):
            result = self.session.execute(stmt)
            counts[name] = int(getattr(result, "rowcount", 0))
        self.session.commit()
        return counts
