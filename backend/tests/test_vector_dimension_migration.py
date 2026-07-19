import uuid

import pytest
from sqlalchemy import text

from backend.database.session import async_engine
from backend.embeddings.base import EmbeddingProvider
from backend.services.vector_dimension_migration_service import (
    VECTOR_DIMENSION_STORES,
    VectorDimensionMigrationService,
    VectorDimensionStore,
    _identifier,
)


class TwoDimensionProvider(EmbeddingProvider):
    model = "two-dimension-test"

    # Return a stable two-dimensional document vector.
    def embed_text(self, text: str) -> list[float]:
        return [0.25, 0.75]

    # Return a stable two-dimensional query vector.
    def embed_query(self, query: str) -> list[float]:
        return self.embed_text(query)


class WrongDimensionProvider(TwoDimensionProvider):
    # Return the wrong dimension to force a rollback-safe backfill failure.
    def embed_text(self, text: str) -> list[float]:
        return [1.0]


# Verify dynamic SQL identifiers reject caller-controlled syntax.
def test_vector_dimension_migration_rejects_unsafe_identifiers() -> None:
    with pytest.raises(ValueError, match="Unsafe database identifier"):
        _identifier("memory; DROP TABLE users")


# Verify production vector stores currently inventory as 768 without mutation.
@pytest.mark.asyncio
async def test_vector_dimension_inventory_covers_every_production_store() -> None:
    service = VectorDimensionMigrationService(
        async_engine,
        TwoDimensionProvider(),
        "inventory-only",
        768,
    )
    report = await service.migrate(dry_run=True)
    assert set(report["stores"]) == {store.table for store in VECTOR_DIMENSION_STORES}
    assert {state["current_dimension"] for state in report["stores"].values()} == {768}
    assert all(state["shadow_dimension"] is None for state in report["stores"].values())


# Verify failed backfill preserves the old vector and a retry switches dimensions.
@pytest.mark.asyncio
async def test_vector_dimension_migration_is_resumable_and_atomic() -> None:
    suffix = uuid.uuid4().hex
    table = f"vector_migration_{suffix}"
    index = f"ix_vector_migration_{suffix}"
    store = VectorDimensionStore(table, index, "content", tracks_metadata=False)
    quoted_table = _identifier(table)
    quoted_index = _identifier(index)
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    async with async_engine.begin() as connection:
        await connection.execute(
            text(
                f"CREATE TABLE {quoted_table} ("
                "id uuid PRIMARY KEY, content text NOT NULL, "
                "embedding vector(3) NOT NULL)"
            )
        )
        await connection.execute(
            text(
                f"CREATE INDEX {quoted_index} ON {quoted_table} USING hnsw "
                "(embedding vector_cosine_ops)"
            )
        )
        await connection.execute(
            text(
                f"INSERT INTO {quoted_table} (id, content, embedding) VALUES "
                "(:first_id, 'first', '[1,0,0]'), "
                "(:second_id, 'second', '[0,1,0]')"
            ),
            {"first_id": first_id, "second_id": second_id},
        )

    try:
        failing = VectorDimensionMigrationService(
            async_engine,
            WrongDimensionProvider(),
            "dimension-two",
            2,
            (store,),
        )
        with pytest.raises(
            ValueError,
            match="incompatible dimension: 1; expected 2",
        ):
            await failing.migrate(dry_run=False, batch_size=1)
        failed_inventory = await failing.inventory()
        assert failed_inventory["stores"][table] == {
            "current_dimension": 3,
            "shadow_dimension": 2,
            "remaining": 2,
        }
        async with async_engine.connect() as connection:
            old_vectors = list(
                (
                    await connection.execute(
                        text(
                            f"SELECT embedding::text FROM {quoted_table} "
                            "ORDER BY content"
                        )
                    )
                ).scalars()
            )
        assert old_vectors == ["[1,0,0]", "[0,1,0]"]

        successful = VectorDimensionMigrationService(
            async_engine,
            TwoDimensionProvider(),
            "dimension-two",
            2,
            (store,),
        )
        result = await successful.migrate(dry_run=False, batch_size=1)
        assert result["updated"] == {table: 2}
        assert result["stores"][table] == {
            "current_dimension": 2,
            "shadow_dimension": None,
            "remaining": None,
        }
        async with async_engine.connect() as connection:
            new_vectors = list(
                (
                    await connection.execute(
                        text(
                            f"SELECT embedding::text FROM {quoted_table} "
                            "ORDER BY content"
                        )
                    )
                ).scalars()
            )
            index_exists = await connection.scalar(
                text("SELECT to_regclass(:index) IS NOT NULL"),
                {"index": index},
            )
        assert new_vectors == ["[0.25,0.75]", "[0.25,0.75]"]
        assert index_exists is True
    finally:
        async with async_engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS {quoted_table}"))
