import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, and_, delete, func, or_
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database.locks import transaction_advisory_lock
from backend.discovery.errors import (
    DiscoveryProfileLimitError,
    DiscoveryProjectionConflictError,
)
from backend.discovery.projection import DiscoveryProjection
from backend.memory.errors import MemoryConflictError
from backend.models.artifact import VisualArtifact
from backend.models.conversation import Conversation
from backend.models.discovery import DiscoveryInterest, DiscoveryLocality
from backend.models.discovery_familiar import DiscoveryFamiliarItem
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule
from backend.models.discovery_source import DiscoverySeenItem, DiscoverySource
from backend.models.discovery_subscriber import DiscoverySubscriber
from backend.models.memory import (
    EpisodicMemory,
    MemoryFact,
    SemanticMemory,
    UserProfile,
)
from backend.models.tool_memory import ToolDescriptor, ToolPreference, ToolUsageOutcome


class MemoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_profile(self, user_id: str) -> UserProfile | None:
        query = select(UserProfile).where(UserProfile.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        self.session.add(profile)
        await self.session.commit()
        await self.session.refresh(profile)
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
        await self.session.commit()
        await self.session.refresh(profile)
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
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def has_fact_history(self, user_id: str, fact_key: str) -> bool:
        stmt = select(func.count(MemoryFact.id)).where(
            MemoryFact.user_id == user_id,
            MemoryFact.fact_key == fact_key,
        )
        return bool((await self.session.execute(stmt)).scalar_one())

    async def list_memory_facts(
        self, user_id: str, limit: int | None = None
    ) -> list[MemoryFact]:
        stmt = (
            select(MemoryFact)
            .where(MemoryFact.user_id == user_id)
            .order_by(
                MemoryFact.fact_key,
                MemoryFact.version.desc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    # Return one fact when it belongs to the requested user.
    async def get_fact(self, user_id: str, fact_id: str) -> MemoryFact | None:
        return (
            await self.session.execute(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.id == uuid.UUID(fact_id),
                )
            )
        ).scalar_one_or_none()

    async def approve_preferred_name_fact(
        self,
        user_id: str,
        name: str,
        source_conversation_id: str,
        source_trace_id: str,
        expires_at: datetime | None,
    ) -> tuple[UserProfile, MemoryFact, bool]:
        fact, deduplicated = await self.approve_fact(
            user_id=user_id,
            fact_type="profile",
            fact_key="preferred_name",
            value=name,
            purpose="personalization",
            source_conversation_id=source_conversation_id,
            source_trace_id=source_trace_id,
            expires_at=expires_at,
            extra_data={"source": "chat_approval"},
        )
        profile = await self.get_user_profile(user_id)
        if profile is None:
            raise MemoryConflictError("The approved fact has no profile projection")
        return profile, fact, deduplicated

    # Persist one approved fact while preserving its version history.
    async def approve_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        fact_key: str,
        value: str,
        purpose: str,
        source_conversation_id: str | None,
        source_trace_id: str,
        expires_at: datetime | None,
        extra_data: dict[str, Any],
    ) -> tuple[MemoryFact, bool]:
        try:
            memory_fact, deduplicated = await self._approve_fact_uncommitted(
                user_id=user_id,
                fact_type=fact_type,
                fact_key=fact_key,
                value=value,
                purpose=purpose,
                source_conversation_id=source_conversation_id,
                source_trace_id=source_trace_id,
                expires_at=expires_at,
                extra_data=extra_data,
            )
            await self.session.commit()
            await self.session.refresh(memory_fact)
            return memory_fact, deduplicated
        except Exception:
            await self.session.rollback()
            raise

    # Persist several approved facts in one transaction or none of them.
    async def approve_facts(
        self,
        facts: list[dict[str, Any]],
    ) -> list[tuple[MemoryFact, bool]]:
        try:
            results: list[tuple[MemoryFact, bool]] = []
            # Stable lock order prevents two overlapping lists from deadlocking.
            for item in sorted(facts, key=lambda value: str(value["fact_key"])):
                results.append(await self._approve_fact_uncommitted(**item))
            await self.session.commit()
            for memory_fact, _ in results:
                await self.session.refresh(memory_fact)
            return results
        except Exception:
            await self.session.rollback()
            raise

    # Stage one fact and its projection without ending the caller's transaction.
    async def _approve_fact_uncommitted(
        self,
        *,
        user_id: str,
        fact_type: str,
        fact_key: str,
        value: str,
        purpose: str,
        source_conversation_id: str | None,
        source_trace_id: str,
        expires_at: datetime | None,
        extra_data: dict[str, Any],
    ) -> tuple[MemoryFact, bool]:
        source_trace_uuid = uuid.UUID(source_trace_id)
        normalized_value = value.strip().casefold()
        # A transaction-scoped advisory lock also serializes the first write,
        # when no fact row exists yet for SELECT ... FOR UPDATE to lock.
        await transaction_advisory_lock(self.session, "fact", user_id, fact_key)
        existing = (
            await self.session.execute(
                select(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.fact_key == fact_key,
                    MemoryFact.source_trace_id == source_trace_uuid,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.fact_type != fact_type:
                raise MemoryConflictError(
                    "The fact key is already associated with another fact type"
                )
            if existing.normalized_value != normalized_value:
                raise MemoryConflictError(
                    "The source trace is already associated with another value"
                )
            return existing, True

        stored = list(
            (
                await self.session.execute(
                    select(MemoryFact)
                    .where(
                        MemoryFact.user_id == user_id,
                        MemoryFact.fact_key == fact_key,
                    )
                    .order_by(MemoryFact.version.desc())
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        latest = stored[0] if stored else None
        if latest is not None and latest.fact_type != fact_type:
            raise MemoryConflictError(
                "The fact key is already associated with another fact type"
            )
        effective_at = datetime.now(UTC)
        current = next(
            (
                fact
                for fact in stored
                if fact.approval_state == "approved"
                and (fact.expires_at is None or fact.expires_at > effective_at)
            ),
            None,
        )
        if current is not None and current.normalized_value == normalized_value:
            await self._apply_fact_projection(user_id, fact_key, current.value)
            return current, True

        for stored_fact in stored:
            if stored_fact.approval_state == "approved":
                stored_fact.approval_state = "superseded"

        memory_fact = MemoryFact(
            user_id=user_id,
            fact_type=fact_type,
            fact_key=fact_key,
            value=value,
            normalized_value=normalized_value,
            approval_state="approved",
            confidence=1.0,
            purpose=purpose,
            source_conversation_id=(
                uuid.UUID(source_conversation_id)
                if source_conversation_id is not None
                else None
            ),
            source_trace_id=source_trace_uuid,
            version=(latest.version + 1) if latest else 1,
            supersedes_id=latest.id if latest else None,
            embedding_model=None,
            embedding_version=None,
            embedding_dimension=None,
            expires_at=expires_at,
            extra_data=extra_data,
        )
        self.session.add(memory_fact)
        await self._apply_fact_projection(user_id, fact_key, value)
        return memory_fact, False

    async def clear_preferred_name_facts(self, user_id: str) -> UserProfile | None:
        await self.clear_fact_key(user_id, "preferred_name")
        return await self.get_user_profile(user_id)

    # Delete one fact and refresh any denormalized profile projection.
    async def delete_fact(self, user_id: str, fact_id: str) -> bool:
        try:
            fact = (
                await self.session.execute(
                    select(MemoryFact)
                    .where(
                        MemoryFact.user_id == user_id,
                        MemoryFact.id == uuid.UUID(fact_id),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if fact is None:
                await self.session.rollback()
                return False
            fact_key = fact.fact_key
            was_approved = fact.approval_state == "approved"
            await self.session.delete(fact)
            if was_approved:
                await self._apply_fact_projection(user_id, fact_key, None)
            await self.session.commit()
            return True
        except Exception:
            await self.session.rollback()
            raise

    # Delete all facts for a key and clear its profile projection.
    async def clear_fact_key(self, user_id: str, fact_key: str) -> int:
        try:
            result = await self.session.execute(
                delete(MemoryFact).where(
                    MemoryFact.user_id == user_id,
                    MemoryFact.fact_key == fact_key,
                )
            )
            deleted = int(getattr(result, "rowcount", 0))
            await self._apply_fact_projection(user_id, fact_key, None)
            await self.session.commit()
            return deleted
        except Exception:
            await self.session.rollback()
            raise

    # Apply a supported approved fact to the user's profile row.
    async def _apply_fact_projection(
        self,
        user_id: str,
        fact_key: str,
        value: str | None,
    ) -> None:
        if fact_key not in {"preferred_name", "response_style"}:
            projection = DiscoveryProjection(self.session)
            try:
                if value is None:
                    await projection.revoke_fact(user_id, fact_key)
                else:
                    await projection.apply_fact(user_id, fact_key, value)
            except (
                DiscoveryProfileLimitError,
                DiscoveryProjectionConflictError,
            ) as exc:
                raise MemoryConflictError(str(exc)) from exc
            return
        profile = await self.get_user_profile(user_id)
        if profile is None:
            if value is None:
                return
            profile = UserProfile(user_id=user_id, name=None, preferences={})
            self.session.add(profile)
        if fact_key == "preferred_name":
            profile.name = value
            return
        preferences = dict(profile.preferences or {})
        if value is None:
            preferences.pop("response_style", None)
        else:
            preferences["response_style"] = value
        profile.preferences = preferences

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
        result = await self.session.execute(stmt)
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
        await self.session.commit()
        await self.session.refresh(new_mem)
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
        result = await self.session.execute(stmt)
        return [(memory, float(score)) for memory, score in result.all()]

    # Retrieve the user's own past turns nearest this question.
    #
    # Searching what they actually said, rather than only what a classifier
    # promoted into semantic memory: an account with fourteen conversations had
    # zero promoted rows, so recall could reach none of it. Turns written
    # before turns were embedded have no vector and are skipped by the
    # `is_not(None)` rather than matching everything.
    #
    # The current conversation is excluded because its recent turns are already
    # supplied to the prompt as history, and recalling them again would spend
    # the context budget repeating what is directly above.
    async def get_recalled_turns(
        self,
        user_id: str,
        query_embedding: list[float],
        top_k: int,
        max_cosine_distance: float,
        exclude_conversation_id: uuid.UUID | None = None,
    ) -> list[tuple[Conversation, float]]:
        distance = Conversation.embedding.cosine_distance(query_embedding)
        stmt = (
            select(Conversation, distance.label("cosine_distance"))
            .where(
                Conversation.user_id == user_id,
                Conversation.embedding.is_not(None),
                distance <= max_cosine_distance,
            )
            .order_by(distance, Conversation.id)
            .limit(top_k)
        )
        if exclude_conversation_id is not None:
            stmt = stmt.where(
                Conversation.conversation_id != exclude_conversation_id
            )
        result = await self.session.execute(stmt)
        return [(turn, float(score)) for turn, score in result.all()]

    # Retrieve one user's derived visual descriptions with a wider candidate bound.
    async def get_visual_semantic_memories(
        self,
        user_id: str,
        query_embedding: list[float],
        top_k: int,
        max_cosine_distance: float,
    ) -> list[tuple[SemanticMemory, float]]:
        distance = SemanticMemory.embedding.cosine_distance(query_embedding)
        effective_at = datetime.now(UTC)
        stmt = (
            select(SemanticMemory, distance.label("cosine_distance"))
            .join(
                VisualArtifact,
                and_(
                    VisualArtifact.user_id == SemanticMemory.user_id,
                    sql_cast(VisualArtifact.id, String)
                    == SemanticMemory.extra_data["artifact_id"].astext,
                ),
            )
            .where(
                SemanticMemory.user_id == user_id,
                SemanticMemory.purpose == "visual_artifact_analysis",
                VisualArtifact.status == "ready",
                VisualArtifact.kind.in_({"generated_image", "uploaded_image"}),
                or_(
                    SemanticMemory.expires_at.is_(None),
                    SemanticMemory.expires_at > effective_at,
                ),
                distance <= max_cosine_distance,
            )
            .order_by(distance, SemanticMemory.id)
            .limit(top_k)
        )
        result = await self.session.execute(stmt)
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
        await self.session.commit()
        await self.session.refresh(new_mem)
        return new_mem

    # Atomically replace the derived visual-memory row for one owned artifact.
    async def replace_visual_semantic_memory(
        self,
        user_id: str,
        artifact_id: str,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any],
        purpose: str,
        embedding_model: str,
        embedding_version: str,
        embedding_dimension: int,
    ) -> SemanticMemory:
        await transaction_advisory_lock(
            self.session,
            "visual-semantic-memory",
            user_id,
            artifact_id,
        )
        await self.session.execute(
            delete(SemanticMemory).where(
                SemanticMemory.user_id == user_id,
                SemanticMemory.purpose == purpose,
                SemanticMemory.extra_data["artifact_id"].astext == artifact_id,
            )
        )
        memory = SemanticMemory(
            user_id=user_id,
            content=content,
            embedding=embedding,
            purpose=purpose,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            embedding_dimension=embedding_dimension,
            extra_data=metadata,
        )
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def list_semantic_memories(
        self, user_id: str, limit: int | None = None
    ) -> list[SemanticMemory]:
        stmt = (
            select(SemanticMemory)
            .where(SemanticMemory.user_id == user_id)
            .order_by(SemanticMemory.created_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_conversations(
        self, user_id: str, limit: int | None = None
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at, Conversation.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

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
            memory = (
                await self.session.execute(
                    select(EpisodicMemory).where(
                        EpisodicMemory.id == memory_id,
                        EpisodicMemory.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
        elif memory_type == "semantic":
            memory = (
                await self.session.execute(
                    select(SemanticMemory).where(
                        SemanticMemory.id == memory_id,
                        SemanticMemory.user_id == user_id,
                    )
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
        await self.session.commit()
        await self.session.refresh(memory)
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
        result = await self.session.execute(stmt)
        await self.session.commit()
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
            # Ambient discovery holds some of the most personal data here — where
            # the user lives, what they like, everything they have been shown,
            # and other people's contact details. It grew outside this
            # subsystem's guarantees, so a "forget me" once left all of it
            # behind. Runs are removed before schedules for the foreign key.
            (
                "discovery_familiar",
                delete(DiscoveryFamiliarItem).where(
                    DiscoveryFamiliarItem.user_id == user_id
                ),
            ),
            (
                "discovery_seen",
                delete(DiscoverySeenItem).where(DiscoverySeenItem.user_id == user_id),
            ),
            (
                "discovery_subscribers",
                delete(DiscoverySubscriber).where(
                    DiscoverySubscriber.user_id == user_id
                ),
            ),
            (
                "discovery_sources",
                delete(DiscoverySource).where(DiscoverySource.user_id == user_id),
            ),
            (
                "discovery_runs",
                delete(DiscoveryRun).where(DiscoveryRun.user_id == user_id),
            ),
            (
                "discovery_schedules",
                delete(DiscoverySchedule).where(DiscoverySchedule.user_id == user_id),
            ),
            (
                "discovery_interests",
                delete(DiscoveryInterest).where(DiscoveryInterest.user_id == user_id),
            ),
            (
                "discovery_localities",
                delete(DiscoveryLocality).where(DiscoveryLocality.user_id == user_id),
            ),
        ):
            result = await self.session.execute(stmt)
            counts[name] = int(getattr(result, "rowcount", 0))
        await self.session.commit()
        return counts
