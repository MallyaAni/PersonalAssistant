import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.embeddings.base import EmbeddingProvider


@dataclass(frozen=True)
class VectorDimensionStore:
    """Describe one trusted vector table and its canonical embedding text."""

    table: str
    index: str
    source_expression: str
    tracks_metadata: bool = True


VECTOR_DIMENSION_STORES = (
    VectorDimensionStore(
        "semantic_memory",
        "ix_semantic_memory_embedding_hnsw",
        "content",
    ),
    VectorDimensionStore(
        "semantic_cache_entries",
        "ix_semantic_cache_embedding_hnsw",
        "query",
    ),
    VectorDimensionStore(
        "procedure_memories",
        "ix_procedure_memory_embedding_hnsw",
        "name || E'\\n' || description || E'\\n' || steps::text",
    ),
    VectorDimensionStore(
        "memory_entities",
        "ix_memory_entity_embedding_hnsw",
        "entity_type || E'\\n' || canonical_name || E'\\n' || attributes::text",
    ),
    VectorDimensionStore(
        "knowledge_chunks",
        "ix_knowledge_chunk_embedding_hnsw",
        "content",
    ),
    VectorDimensionStore(
        "conversation_summaries",
        "ix_conversation_summary_embedding_hnsw",
        "content",
    ),
    VectorDimensionStore(
        "tool_descriptors",
        "ix_tool_descriptor_embedding_hnsw",
        (
            "'server=' || server_id || E'\\nname=' || tool_name || "
            "E'\\ndescription=' || description || E'\\ninput_purpose=' || "
            "input_purpose || E'\\nversion=' || tool_version || E'\\nrisk=' || "
            "risk_classification"
        ),
    ),
)


# Quote one allowlisted SQL identifier used by migration DDL.
def _identifier(value: str) -> str:
    if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", value) is None:
        raise ValueError(f"Unsafe database identifier: {value}")
    return f'"{value}"'


# Read a pgvector column's declared dimension from PostgreSQL metadata.
async def _column_dimension(
    connection: Any,
    table: str,
    column: str,
) -> int | None:
    formatted = await connection.scalar(
        text("""
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute AS attribute
            JOIN pg_class AS relation ON relation.oid = attribute.attrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = current_schema()
              AND relation.relname = :table
              AND attribute.attname = :column
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            """),
        {"table": table, "column": column},
    )
    if formatted is None:
        return None
    match = re.fullmatch(r"vector\((\d+)\)", str(formatted))
    if match is None:
        raise ValueError(f"{table}.{column} is not a dimensioned vector column")
    return int(match.group(1))


class VectorDimensionMigrationService:
    """Backfill shadow vectors and atomically switch every configured store."""

    # Configure the database, target embedding metadata, and trusted stores.
    def __init__(
        self,
        engine: AsyncEngine,
        embeddings: EmbeddingProvider,
        embedding_version: str,
        target_dimension: int,
        stores: tuple[VectorDimensionStore, ...] = VECTOR_DIMENSION_STORES,
    ) -> None:
        if not 1 <= target_dimension <= 2_000:
            raise ValueError("Target vector dimension must be between 1 and 2000")
        self.engine = engine
        self.embeddings = embeddings
        self.embedding_model = getattr(embeddings, "model", "unknown")
        self.embedding_version = embedding_version
        self.target_dimension = target_dimension
        self.stores = stores
        for store in stores:
            _identifier(store.table)
            _identifier(store.index)

    # Inventory current and resumable shadow-column state without mutation.
    async def inventory(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        async with self.engine.connect() as connection:
            for store in self.stores:
                current = await _column_dimension(connection, store.table, "embedding")
                shadow = await _column_dimension(
                    connection,
                    store.table,
                    "embedding_next",
                )
                remaining = None
                if shadow is not None:
                    table = _identifier(store.table)
                    remaining = await connection.scalar(
                        text(
                            f"SELECT count(*) FROM {table} "
                            "WHERE embedding_next IS NULL"
                        )
                    )
                result[store.table] = {
                    "current_dimension": current,
                    "shadow_dimension": shadow,
                    "remaining": remaining,
                }
        return {
            "target": {
                "model": self.embedding_model,
                "version": self.embedding_version,
                "dimension": self.target_dimension,
            },
            "stores": result,
        }

    # Resume shadow backfill and switch all stores in one final transaction.
    async def migrate(
        self,
        *,
        dry_run: bool = True,
        batch_size: int = 50,
    ) -> dict[str, Any]:
        if not 1 <= batch_size <= 500:
            raise ValueError("Migration batch size must be between 1 and 500")
        initial = await self.inventory()
        if dry_run:
            return {"dry_run": True, **initial}
        if all(
            store["current_dimension"] == self.target_dimension
            and store["shadow_dimension"] is None
            for store in initial["stores"].values()
        ):
            return {"dry_run": False, "already_current": True, **initial}

        await self._ensure_shadow_columns(initial)
        pending_stores = tuple(
            store
            for store in self.stores
            if initial["stores"][store.table]["current_dimension"]
            != self.target_dimension
        )
        updated = {
            store.table: await self._backfill_store(store, batch_size)
            for store in pending_stores
        }
        await self._switch_columns(pending_stores)
        return {
            "dry_run": False,
            "already_current": False,
            "updated": updated,
            **(await self.inventory()),
        }

    # Add or validate target-dimension shadow columns for every store.
    async def _ensure_shadow_columns(self, inventory: dict[str, Any]) -> None:
        async with self.engine.begin() as connection:
            for store in self.stores:
                state = inventory["stores"][store.table]
                current = state["current_dimension"]
                shadow = state["shadow_dimension"]
                if current is None:
                    raise ValueError(f"Missing vector column: {store.table}.embedding")
                if current == self.target_dimension and shadow is not None:
                    raise ValueError(
                        f"Unexpected shadow column on current store: {store.table}"
                    )
                if shadow is not None and shadow != self.target_dimension:
                    raise ValueError(
                        f"Shadow dimension mismatch on {store.table}: {shadow}"
                    )
                if current != self.target_dimension and shadow is None:
                    table = _identifier(store.table)
                    await connection.execute(
                        text(
                            f"ALTER TABLE {table} ADD COLUMN embedding_next "
                            f"vector({self.target_dimension})"
                        )
                    )

    # Fill missing shadow vectors in committed, resumable batches.
    async def _backfill_store(
        self,
        store: VectorDimensionStore,
        batch_size: int,
    ) -> int:
        table = _identifier(store.table)
        updated = 0
        while True:
            async with self.engine.begin() as connection:
                rows = list(
                    (
                        await connection.execute(
                            text(
                                f"SELECT id::text, {store.source_expression} "
                                f"FROM {table} WHERE embedding_next IS NULL "
                                "ORDER BY id LIMIT :limit FOR UPDATE"
                            ),
                            {"limit": batch_size},
                        )
                    ).all()
                )
                if not rows:
                    return updated
                for row_id, source_text in rows:
                    embedding = await asyncio.to_thread(
                        self.embeddings.embed_text,
                        str(source_text),
                    )
                    if len(embedding) != self.target_dimension:
                        raise ValueError(
                            "Embedding provider returned incompatible dimension: "
                            f"{len(embedding)}; expected {self.target_dimension}"
                        )
                    await connection.execute(
                        text(
                            f"UPDATE {table} SET embedding_next = "
                            f"CAST(:embedding AS vector({self.target_dimension})) "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {
                            "embedding": json.dumps(embedding),
                            "id": row_id,
                        },
                    )
                    updated += 1

    # Lock and switch every fully backfilled store in one DDL transaction.
    async def _switch_columns(
        self,
        stores: tuple[VectorDimensionStore, ...],
    ) -> None:
        async with self.engine.begin() as connection:
            for store in stores:
                table = _identifier(store.table)
                remaining = await connection.scalar(
                    text(
                        f"SELECT count(*) FROM {table} " "WHERE embedding_next IS NULL"
                    )
                )
                if remaining:
                    raise RuntimeError(
                        f"Cannot switch {store.table}; {remaining} vectors remain"
                    )
            for store in stores:
                table = _identifier(store.table)
                index = _identifier(store.index)
                await connection.execute(
                    text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
                )
                await connection.execute(text(f"DROP INDEX IF EXISTS {index}"))
                await connection.execute(
                    text(f"ALTER TABLE {table} DROP COLUMN embedding")
                )
                await connection.execute(
                    text(
                        f"ALTER TABLE {table} RENAME COLUMN "
                        "embedding_next TO embedding"
                    )
                )
                await connection.execute(
                    text(f"ALTER TABLE {table} ALTER COLUMN embedding SET NOT NULL")
                )
                if store.tracks_metadata:
                    await connection.execute(
                        text(
                            f"UPDATE {table} SET embedding_model = :model, "
                            "embedding_version = :version, "
                            "embedding_dimension = :dimension"
                        ),
                        {
                            "model": self.embedding_model,
                            "version": self.embedding_version,
                            "dimension": self.target_dimension,
                        },
                    )
                await connection.execute(
                    text(
                        f"CREATE INDEX {index} ON {table} USING hnsw "
                        "(embedding vector_cosine_ops)"
                    )
                )
