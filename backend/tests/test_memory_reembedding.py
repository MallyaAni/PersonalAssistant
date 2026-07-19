import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.cli.reembed_memory import main as reembed_memory_main
from backend.config.settings import settings
from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal, SessionLocal
from backend.embeddings.base import EmbeddingProvider
from backend.main import app
from backend.models.agent_memory import (
    ConversationSummary,
    KnowledgeChunk,
    MemoryEntity,
    ProcedureMemory,
    SemanticCacheEntry,
)
from backend.models.memory import SemanticMemory
from backend.models.tool_memory import ToolDescriptor
from backend.services.memory_reembedding_service import MemoryReembeddingService

VECTOR_MODELS = (
    SemanticMemory,
    SemanticCacheEntry,
    ProcedureMemory,
    MemoryEntity,
    KnowledgeChunk,
    ConversationSummary,
    ToolDescriptor,
)


# Build a deterministic vector with the configured test dimension.
def _vector(value: float = 1.0) -> list[float]:
    return [value, *([0.0] * 767)]


class RecordingEmbeddingProvider(EmbeddingProvider):
    model = "reembedding-test-model"

    # Configure the fake vector dimension and call recorder.
    def __init__(self, dimension: int = 768) -> None:
        self.dimension = dimension
        self.calls: list[str] = []

    # Record stored text and return a deterministic embedding.
    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.25, *([0.0] * (self.dimension - 1))]

    # Reuse stored-text embedding behavior for queries.
    def embed_query(self, query: str) -> list[float]:
        return self.embed_text(query)


# Delete all test-owned memory for one user.
def _cleanup(user_id: str) -> None:
    with TestClient(app) as client:
        client.delete(f"/api/v1/memory/{user_id}")


# Create one record in every vector-bearing memory store.
def _create_vector_rows(client: TestClient, user_id: str) -> None:
    trace_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    responses = [
        client.post(
            f"/api/v1/memory/{user_id}/semantic",
            json={"content": "semantic re-embedding text"},
        ),
        client.put(
            f"/api/v1/memory/{user_id}/agent/cache",
            json={
                "query": "cache re-embedding query",
                "response": "cached response",
                "model": "coordinator-test",
                "expires_at": expires_at.isoformat(),
            },
        ),
        client.post(
            f"/api/v1/memory/{user_id}/agent/procedures",
            json={
                "name": "Re-embedding procedure",
                "description": "Procedure description",
                "steps": [{"order": 1, "instruction": "Run it"}],
                "source_trace_id": trace_id,
            },
        ),
        client.put(
            f"/api/v1/memory/{user_id}/agent/entities",
            json={
                "entity_type": "project",
                "canonical_name": "Re-embedding project",
                "attributes": {"state": "active"},
                "source_trace_id": trace_id,
            },
        ),
        client.post(
            f"/api/v1/memory/{user_id}/agent/knowledge",
            json={
                "title": "Re-embedding knowledge",
                "content": "Knowledge chunk re-embedding text.",
                "purpose": "test",
            },
        ),
        client.put(
            f"/api/v1/memory/{user_id}/agent/summaries",
            json={
                "conversation_id": conversation_id,
                "content": "Summary re-embedding text.",
                "through_turn_count": 2,
                "source_trace_id": trace_id,
            },
        ),
        client.post(
            f"/api/v1/memory/{user_id}/tools/descriptors",
            json={
                "server_id": "reembedding-mcp",
                "tool_name": "search_records",
                "description": "Search records",
                "input_purpose": "Choose a search term",
                "schema_fingerprint": "a" * 64,
                "tool_version": "1.0.0",
                "risk_classification": "read_only",
            },
        ),
    ]
    assert [response.status_code for response in responses] == [
        201,
        200,
        201,
        200,
        201,
        200,
        201,
    ]


# Verify inventory, dry-run, and apply modes cover every vector store.
def test_reembedding_inventory_dry_run_and_apply_cover_every_vector_store() -> None:
    user_id = f"reembed_{uuid.uuid4()}"
    provider = RecordingEmbeddingProvider()
    app.dependency_overrides[get_embedding_provider] = lambda: provider

    try:
        with TestClient(app) as client:
            _create_vector_rows(client, user_id)
            provider.calls.clear()
            with SessionLocal() as session:
                for model in VECTOR_MODELS:
                    session.execute(
                        update(model)
                        .where(model.user_id == user_id)
                        .values(
                            embedding_model="retired-model",
                            embedding_version="retired-version",
                        )
                    )
                session.commit()

            inventory = client.get(f"/api/v1/memory/{user_id}/agent/reembedding")
            dry_run = client.post(f"/api/v1/memory/{user_id}/agent/reembedding")
            expected_counts = {
                "semantic": 1,
                "semantic_cache": 1,
                "procedures": 1,
                "entities": 1,
                "knowledge_chunks": 1,
                "summaries": 1,
                "tool_descriptors": 1,
            }
            assert inventory.status_code == 200
            assert inventory.json()["stale"] == expected_counts
            assert inventory.json()["stale_total"] == 7
            assert dry_run.status_code == 200
            assert dry_run.json()["counts"] == expected_counts
            assert dry_run.json()["updated_total"] == 0
            assert provider.calls == []

            applied = client.post(
                f"/api/v1/memory/{user_id}/agent/reembedding",
                params={"dry_run": "false", "batch_size": 2},
            )
            assert applied.status_code == 200
            assert applied.json()["updated"] == expected_counts
            assert applied.json()["updated_total"] == 7
            assert len(provider.calls) == 7

            after = client.get(f"/api/v1/memory/{user_id}/agent/reembedding").json()
            assert after["stale_total"] == 0
            with SessionLocal() as session:
                for model in VECTOR_MODELS:
                    row = session.execute(
                        select(model).where(model.user_id == user_id)
                    ).scalar_one()
                    assert row.embedding_model == provider.model
                    assert row.embedding_version == settings.EMBEDDING_MODEL_VERSION
                    assert row.embedding_dimension == 768
                    assert list(row.embedding) == _vector(0.25)
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _cleanup(user_id)


# Verify an invalid vector dimension rolls back the full batch.
@pytest.mark.asyncio
async def test_reembedding_rolls_back_an_entire_batch_on_dimension_mismatch() -> None:
    user_id = f"reembed_{uuid.uuid4()}"
    row_ids = [uuid.uuid4(), uuid.uuid4()]
    with SessionLocal() as session:
        session.add_all(
            SemanticMemory(
                id=row_id,
                user_id=user_id,
                content=f"dimension test {index}",
                embedding=_vector(),
                purpose="test",
                embedding_model="retired-model",
                embedding_version="retired-version",
                embedding_dimension=768,
                extra_data={},
            )
            for index, row_id in enumerate(row_ids)
        )
        session.commit()

    try:
        async with AsyncSessionLocal() as session:
            service = MemoryReembeddingService(
                session,
                RecordingEmbeddingProvider(dimension=3),
                settings.EMBEDDING_MODEL_VERSION,
                768,
            )
            with pytest.raises(ValueError, match="incompatible dimension"):
                await service.reembed(user_id, dry_run=False, batch_size=2)

        with SessionLocal() as session:
            rows = list(
                session.execute(
                    select(SemanticMemory)
                    .where(SemanticMemory.id.in_(row_ids))
                    .order_by(SemanticMemory.id)
                ).scalars()
            )
            assert len(rows) == 2
            assert {row.embedding_model for row in rows} == {"retired-model"}
            assert {row.embedding_version for row in rows} == {"retired-version"}
    finally:
        with SessionLocal() as session:
            session.execute(
                delete(SemanticMemory).where(SemanticMemory.user_id == user_id)
            )
            session.commit()


# Verify the re-embedding CLI rejects an unscoped write operation.
def test_reembedding_cli_refuses_unscoped_apply() -> None:
    with pytest.raises(SystemExit) as error:
        reembed_memory_main(["--apply"])
    assert error.value.code == 2
