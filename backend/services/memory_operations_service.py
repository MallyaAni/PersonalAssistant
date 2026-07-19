from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.embeddings.base import EmbeddingProvider
from backend.models.agent_memory import (
    ConversationSummary,
    KnowledgeChunk,
    KnowledgeDocument,
    MemoryEntity,
    MemoryEntityRelation,
    ProcedureMemory,
    SemanticCacheEntry,
    WorkingMemoryItem,
)
from backend.models.conversation import Conversation
from backend.models.memory import (
    EpisodicMemory,
    MemoryFact,
    SemanticMemory,
    UserProfile,
)
from backend.models.tool_memory import ToolDescriptor, ToolPreference, ToolUsageOutcome
from backend.services.memory_reembedding_service import MemoryReembeddingService

COUNT_STORES = (
    ("conversations", Conversation),
    ("profiles", UserProfile),
    ("facts", MemoryFact),
    ("episodic", EpisodicMemory),
    ("semantic", SemanticMemory),
    ("semantic_cache", SemanticCacheEntry),
    ("working", WorkingMemoryItem),
    ("procedures", ProcedureMemory),
    ("entities", MemoryEntity),
    ("entity_relations", MemoryEntityRelation),
    ("knowledge_documents", KnowledgeDocument),
    ("knowledge_chunks", KnowledgeChunk),
    ("summaries", ConversationSummary),
    ("tool_descriptors", ToolDescriptor),
    ("tool_preferences", ToolPreference),
    ("tool_outcomes", ToolUsageOutcome),
)

EXPIRING_STORES = (
    ("facts", MemoryFact),
    ("episodic", EpisodicMemory),
    ("semantic", SemanticMemory),
    ("semantic_cache", SemanticCacheEntry),
    ("working", WorkingMemoryItem),
    ("procedures", ProcedureMemory),
    ("entities", MemoryEntity),
    ("tool_preferences", ToolPreference),
)


class MemoryOperationsService:
    """Expose non-content operational state for the memory subsystem."""

    # Store dependencies used to inspect database and embedding health.
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider,
        embedding_version: str,
        embedding_dimension: int,
    ) -> None:
        self.session = session
        self.reembedding = MemoryReembeddingService(
            session,
            embeddings,
            embedding_version,
            embedding_dimension,
        )

    # Report memory counts, stale data, invariants, and database health.
    async def inspect(self, user_id: str | None = None) -> dict[str, Any]:
        now = datetime.now(UTC)
        started = perf_counter()
        await self.session.scalar(select(1))
        query_latency_ms = round((perf_counter() - started) * 1_000, 3)

        counts: dict[str, int] = {}
        for name, model in COUNT_STORES:
            counts[name] = await self._count(model, user_id)
        expired: dict[str, int] = {}
        for name, model in EXPIRING_STORES:
            expired[name] = await self._count(
                model,
                user_id,
                model.expires_at.is_not(None),
                model.expires_at <= now,
            )
        vector_inventory = await self.reembedding.inventory(user_id)
        indexing_documents = await self._count(
            KnowledgeDocument,
            user_id,
            KnowledgeDocument.status != "active",
        )
        invariants = {
            "fact_keys_with_multiple_approved": await self._group_violation_count(
                MemoryFact,
                user_id,
                (MemoryFact.fact_key,),
                MemoryFact.approval_state == "approved",
            ),
            "procedure_names_with_multiple_active": await self._group_violation_count(
                ProcedureMemory,
                user_id,
                (ProcedureMemory.name,),
                ProcedureMemory.active.is_(True),
            ),
        }
        attention_total = (
            sum(expired.values())
            + int(vector_inventory["stale_total"])
            + indexing_documents
            + sum(invariants.values())
        )
        bind = self.session.get_bind()
        pool = getattr(bind, "pool", None)
        return {
            "status": "healthy" if attention_total == 0 else "attention",
            "checked_at": now.isoformat(),
            "user_id": user_id,
            "counts": counts,
            "records_total": sum(counts.values()),
            "expired_backlog": expired,
            "expired_total": sum(expired.values()),
            "vectors": vector_inventory,
            "indexing_documents": indexing_documents,
            "invariant_violations": invariants,
            "database": {
                "query_ok": True,
                "query_latency_ms": query_latency_ms,
                "pool": pool.status() if pool is not None else "unavailable",
            },
        }

    # Render stable non-content gauges for Prometheus-compatible scrapers.
    @staticmethod
    def prometheus(report: dict[str, Any]) -> str:
        lines = [
            "# HELP anios_memory_records Memory records in the selected scope.",
            "# TYPE anios_memory_records gauge",
        ]
        lines.extend(
            f'anios_memory_records{{store="{name}"}} {count}'
            for name, count in sorted(report["counts"].items())
        )
        lines.extend(
            [
                "# HELP anios_memory_expired_records Expired records awaiting purge.",
                "# TYPE anios_memory_expired_records gauge",
            ]
        )
        lines.extend(
            f'anios_memory_expired_records{{store="{name}"}} {count}'
            for name, count in sorted(report["expired_backlog"].items())
        )
        lines.extend(
            [
                "# HELP anios_memory_stale_vectors Vectors awaiting re-embedding.",
                "# TYPE anios_memory_stale_vectors gauge",
                f'anios_memory_stale_vectors {report["vectors"]["stale_total"]}',
                "# HELP anios_memory_invariant_violations Broken memory invariants.",
                "# TYPE anios_memory_invariant_violations gauge",
                (
                    "anios_memory_invariant_violations "
                    f'{sum(report["invariant_violations"].values())}'
                ),
                "# HELP anios_memory_database_query_latency_ms Database probe latency.",
                "# TYPE anios_memory_database_query_latency_ms gauge",
                (
                    "anios_memory_database_query_latency_ms "
                    f'{report["database"]["query_latency_ms"]}'
                ),
                "# HELP anios_memory_healthy Memory health state as 1 or 0.",
                "# TYPE anios_memory_healthy gauge",
                f'anios_memory_healthy {int(report["status"] == "healthy")}',
            ]
        )
        return "\n".join(lines) + "\n"

    # Count rows for a store within the requested user scope.
    async def _count(
        self,
        model: Any,
        user_id: str | None,
        *conditions: Any,
    ) -> int:
        filters = list(conditions)
        if user_id is not None:
            filters.append(model.user_id == user_id)
        return (
            await self.session.scalar(
                select(func.count()).select_from(model).where(*filters)
            )
            or 0
        )

    # Count grouped keys that violate a single-record invariant.
    async def _group_violation_count(
        self,
        model: Any,
        user_id: str | None,
        group_columns: tuple[Any, ...],
        *conditions: Any,
    ) -> int:
        filters = list(conditions)
        if user_id is not None:
            filters.append(model.user_id == user_id)
        scoped_group_columns = (model.user_id, *group_columns)
        grouped = (
            select(*scoped_group_columns)
            .where(*filters)
            .group_by(*scoped_group_columns)
            .having(func.count() > 1)
            .subquery()
        )
        return await self.session.scalar(select(func.count()).select_from(grouped)) or 0
