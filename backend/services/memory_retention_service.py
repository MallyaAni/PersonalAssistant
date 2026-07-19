from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_memory import (
    MemoryEntity,
    MemoryEntityRelation,
    ProcedureMemory,
    SemanticCacheEntry,
    WorkingMemoryItem,
)
from backend.models.memory import (
    EpisodicMemory,
    MemoryFact,
    SemanticMemory,
    UserProfile,
)
from backend.models.tool_memory import ToolPreference


class MemoryRetentionService:
    """Atomically report or purge expired memory records."""

    # Store the database session used by retention operations.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Preview or atomically delete memory that expired by a cutoff time.
    async def purge_expired(
        self,
        user_id: str | None = None,
        *,
        dry_run: bool = True,
        cutoff: datetime | None = None,
    ) -> dict[str, Any]:
        effective_cutoff = cutoff or datetime.now(UTC)
        if effective_cutoff.tzinfo is None or effective_cutoff.utcoffset() is None:
            raise ValueError("Retention cutoff must include a timezone")

        expired_entities = select(MemoryEntity.id).where(
            MemoryEntity.expires_at.is_not(None),
            MemoryEntity.expires_at <= effective_cutoff,
            *self._user_filter(MemoryEntity, user_id),
        )
        relation_filter = or_(
            MemoryEntityRelation.source_entity_id.in_(expired_entities),
            MemoryEntityRelation.target_entity_id.in_(expired_entities),
        )
        if user_id is not None:
            relation_filter = relation_filter & (
                MemoryEntityRelation.user_id == user_id
            )

        profile_filter = self._expired_profile_projection_filter(
            user_id,
            effective_cutoff,
        )
        filters: tuple[tuple[str, Any, tuple[Any, ...]], ...] = (
            (
                "semantic_cache",
                SemanticCacheEntry,
                (
                    SemanticCacheEntry.expires_at <= effective_cutoff,
                    *self._user_filter(SemanticCacheEntry, user_id),
                ),
            ),
            (
                "working",
                WorkingMemoryItem,
                (
                    WorkingMemoryItem.expires_at <= effective_cutoff,
                    *self._user_filter(WorkingMemoryItem, user_id),
                ),
            ),
            (
                "procedures",
                ProcedureMemory,
                (
                    ProcedureMemory.expires_at.is_not(None),
                    ProcedureMemory.expires_at <= effective_cutoff,
                    *self._user_filter(ProcedureMemory, user_id),
                ),
            ),
            (
                "entity_relations",
                MemoryEntityRelation,
                (relation_filter,),
            ),
            (
                "entities",
                MemoryEntity,
                (
                    MemoryEntity.expires_at.is_not(None),
                    MemoryEntity.expires_at <= effective_cutoff,
                    *self._user_filter(MemoryEntity, user_id),
                ),
            ),
            (
                "facts",
                MemoryFact,
                (
                    MemoryFact.expires_at.is_not(None),
                    MemoryFact.expires_at <= effective_cutoff,
                    *self._user_filter(MemoryFact, user_id),
                ),
            ),
            (
                "episodic",
                EpisodicMemory,
                (
                    EpisodicMemory.expires_at.is_not(None),
                    EpisodicMemory.expires_at <= effective_cutoff,
                    *self._user_filter(EpisodicMemory, user_id),
                ),
            ),
            (
                "semantic",
                SemanticMemory,
                (
                    SemanticMemory.expires_at.is_not(None),
                    SemanticMemory.expires_at <= effective_cutoff,
                    *self._user_filter(SemanticMemory, user_id),
                ),
            ),
            (
                "tool_preferences",
                ToolPreference,
                (
                    ToolPreference.expires_at.is_not(None),
                    ToolPreference.expires_at <= effective_cutoff,
                    *self._user_filter(ToolPreference, user_id),
                ),
            ),
        )

        try:
            counts: dict[str, int] = {}
            for name, model, conditions in filters:
                counts[name] = await self._count(model, conditions)
            counts["profiles_cleared"] = await self._count(
                UserProfile, (profile_filter,)
            )
            if dry_run:
                await self.session.rollback()
            else:
                # Clear denormalized profile fields while the expiring facts are
                # still visible to the correlated EXISTS clauses. The update and
                # all deletes remain part of the same transaction.
                await self.session.execute(
                    update(UserProfile).where(profile_filter).values(name=None)
                )
                for _, model, conditions in filters:
                    await self.session.execute(delete(model).where(*conditions))
                await self.session.commit()
            return {
                "dry_run": dry_run,
                "cutoff": effective_cutoff.isoformat(),
                "user_id": user_id,
                "counts": counts,
                "affected_total": sum(counts.values()),
            }
        except Exception:
            await self.session.rollback()
            raise

    # Limit a retention query to one user when requested.
    @staticmethod
    def _user_filter(model: Any, user_id: str | None) -> tuple[Any, ...]:
        return (model.user_id == user_id,) if user_id is not None else ()

    # Count rows matched by a retention filter.
    async def _count(self, model: Any, conditions: tuple[Any, ...]) -> int:
        return (
            await self.session.scalar(
                select(func.count()).select_from(model).where(*conditions)
            )
            or 0
        )

    # Find profiles whose preferred-name projection has expired.
    @staticmethod
    def _expired_profile_projection_filter(
        user_id: str | None,
        cutoff: datetime,
    ) -> Any:
        expired_preferred_name = exists(
            select(MemoryFact.id).where(
                MemoryFact.user_id == UserProfile.user_id,
                MemoryFact.fact_key == "preferred_name",
                MemoryFact.approval_state == "approved",
                MemoryFact.expires_at.is_not(None),
                MemoryFact.expires_at <= cutoff,
            )
        )
        active_preferred_name = exists(
            select(MemoryFact.id).where(
                MemoryFact.user_id == UserProfile.user_id,
                MemoryFact.fact_key == "preferred_name",
                MemoryFact.approval_state == "approved",
                or_(
                    MemoryFact.expires_at.is_(None),
                    MemoryFact.expires_at > cutoff,
                ),
            )
        )
        condition = (
            UserProfile.name.is_not(None)
            & expired_preferred_name
            & ~active_preferred_name
        )
        if user_id is not None:
            condition = condition & (UserProfile.user_id == user_id)
        return condition
