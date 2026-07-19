import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.embeddings.base import EmbeddingProvider
from backend.models.agent_memory import (
    ConversationSummary,
    KnowledgeChunk,
    MemoryEntity,
    ProcedureMemory,
    SemanticCacheEntry,
)
from backend.models.memory import SemanticMemory
from backend.models.tool_memory import ToolDescriptor


@dataclass(frozen=True)
class ReembeddingStore:
    name: str
    model: Any
    canonical_text: Callable[[Any], str]


STORES = (
    ReembeddingStore("semantic", SemanticMemory, lambda row: row.content),
    ReembeddingStore("semantic_cache", SemanticCacheEntry, lambda row: row.query),
    ReembeddingStore(
        "procedures",
        ProcedureMemory,
        lambda row: (
            f"{row.name}\n{row.description}\n"
            f"{json.dumps(row.steps, sort_keys=True)}"
        ),
    ),
    ReembeddingStore(
        "entities",
        MemoryEntity,
        lambda row: (
            f"{row.entity_type}\n{row.canonical_name}\n"
            f"{json.dumps(row.attributes, sort_keys=True)}"
        ),
    ),
    ReembeddingStore("knowledge_chunks", KnowledgeChunk, lambda row: row.content),
    ReembeddingStore("summaries", ConversationSummary, lambda row: row.content),
    ReembeddingStore(
        "tool_descriptors",
        ToolDescriptor,
        lambda row: (
            f"server={row.server_id}\nname={row.tool_name}\n"
            f"description={row.description}\ninput_purpose={row.input_purpose}\n"
            f"version={row.tool_version}\nrisk={row.risk_classification}"
        ),
    ),
)


class MemoryReembeddingService:
    """Inventory and resumably re-embed every vector-bearing memory store."""

    # Store the target embedding configuration and database session.
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider,
        embedding_version: str,
        expected_dimension: int,
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.embedding_model = getattr(embeddings, "model", "unknown")
        self.embedding_version = embedding_version
        self.expected_dimension = expected_dimension

    # Preview or replace stale embeddings in bounded batches.
    async def reembed(
        self,
        user_id: str | None = None,
        *,
        dry_run: bool = True,
        batch_size: int = 50,
    ) -> dict[str, Any]:
        if batch_size < 1 or batch_size > 500:
            raise ValueError("Re-embedding batch size must be between 1 and 500")

        stale_ids: dict[str, list[Any]] = {}
        counts: dict[str, int] = {}
        for store in STORES:
            conditions = self._stale_conditions(store.model, user_id)
            ids = list(
                (
                    await self.session.execute(
                        select(store.model.id)
                        .where(*conditions)
                        .order_by(store.model.id)
                    )
                ).scalars()
            )
            stale_ids[store.name] = ids
            counts[store.name] = len(ids)

        result: dict[str, Any] = {
            "dry_run": dry_run,
            "user_id": user_id,
            "target": {
                "model": self.embedding_model,
                "version": self.embedding_version,
                "dimension": self.expected_dimension,
            },
            "counts": counts,
            "stale_total": sum(counts.values()),
            "updated": {name: 0 for name in counts},
            "updated_total": 0,
        }
        if dry_run:
            await self.session.rollback()
            return result

        for store in STORES:
            ids = stale_ids[store.name]
            for start in range(0, len(ids), batch_size):
                batch_ids = ids[start : start + batch_size]
                try:
                    rows = list(
                        (
                            await self.session.execute(
                                select(store.model)
                                .where(store.model.id.in_(batch_ids))
                                .order_by(store.model.id)
                                .with_for_update()
                            )
                        ).scalars()
                    )
                    embeddings = [
                        await asyncio.to_thread(
                            self.embeddings.embed_text,
                            store.canonical_text(row),
                        )
                        for row in rows
                    ]
                    invalid_dimensions = {
                        len(embedding)
                        for embedding in embeddings
                        if len(embedding) != self.expected_dimension
                    }
                    if invalid_dimensions:
                        dimensions = ", ".join(
                            str(value) for value in sorted(invalid_dimensions)
                        )
                        raise ValueError(
                            "Embedding provider returned incompatible dimension(s): "
                            f"{dimensions}; expected {self.expected_dimension}"
                        )
                    for row, embedding in zip(rows, embeddings, strict=True):
                        row.embedding = embedding
                        row.embedding_model = self.embedding_model
                        row.embedding_version = self.embedding_version
                        row.embedding_dimension = self.expected_dimension
                    await self.session.commit()
                    result["updated"][store.name] += len(rows)
                    result["updated_total"] += len(rows)
                except Exception:
                    await self.session.rollback()
                    raise
        return result

    # Count total and stale vectors across every vector-bearing store.
    async def inventory(self, user_id: str | None = None) -> dict[str, Any]:
        totals: dict[str, int] = {}
        stale: dict[str, int] = {}
        for store in STORES:
            user_filter = (
                (store.model.user_id == user_id,) if user_id is not None else ()
            )
            totals[store.name] = (
                await self.session.scalar(
                    select(func.count()).select_from(store.model).where(*user_filter)
                )
                or 0
            )
            stale[store.name] = (
                await self.session.scalar(
                    select(func.count())
                    .select_from(store.model)
                    .where(*self._stale_conditions(store.model, user_id))
                )
                or 0
            )
        return {
            "user_id": user_id,
            "target": {
                "model": self.embedding_model,
                "version": self.embedding_version,
                "dimension": self.expected_dimension,
            },
            "totals": totals,
            "stale": stale,
            "total": sum(totals.values()),
            "stale_total": sum(stale.values()),
        }

    # Build filters for embeddings that do not match the target configuration.
    def _stale_conditions(
        self,
        model: Any,
        user_id: str | None,
    ) -> tuple[Any, ...]:
        conditions: list[Any] = [
            or_(
                model.embedding_model != self.embedding_model,
                model.embedding_version != self.embedding_version,
                model.embedding_dimension != self.expected_dimension,
            )
        ]
        if user_id is not None:
            conditions.append(model.user_id == user_id)
        return tuple(conditions)
