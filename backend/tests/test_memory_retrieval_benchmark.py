import os
import uuid

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal, SessionLocal
from backend.embeddings.base import EmbeddingProvider
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.models.memory import SemanticMemory
from backend.services.memory_retrieval_evaluator import MemoryRetrievalEvaluator
from backend.services.postgres_memory_service import PostgresMemoryService


# Build a deterministic two-axis vector for retrieval tests.
def _vector(first: float, second: float) -> list[float]:
    return [first, second, *([0.0] * 766)]


class BenchmarkEmbeddingProvider(EmbeddingProvider):
    model = "retrieval-benchmark"

    # Return the benchmark vector for stored text.
    def embed_text(self, text: str) -> list[float]:
        return _vector(1.0, 0.0)

    # Return the benchmark vector for queries.
    def embed_query(self, query: str) -> list[float]:
        return _vector(1.0, 0.0)


# Verify pgvector retrieval is relevant, user-scoped, and within latency bounds.
@pytest.mark.asyncio
async def test_pgvector_retrieval_benchmark_is_scoped_relevant_and_bounded() -> None:
    user_id = f"bench_{uuid.uuid4()}"
    other_user = f"bench_{uuid.uuid4()}"
    target = f"BENCHMARK_TARGET_{uuid.uuid4()}"
    with SessionLocal() as session:
        session.add_all(
            [
                SemanticMemory(
                    user_id=user_id,
                    content=target,
                    embedding=_vector(1.0, 0.0),
                    purpose="benchmark",
                    embedding_model="retrieval-benchmark",
                    embedding_version="1",
                    embedding_dimension=768,
                    extra_data={},
                ),
                SemanticMemory(
                    user_id=other_user,
                    content="cross-user exact match must not appear",
                    embedding=_vector(1.0, 0.0),
                    purpose="benchmark",
                    embedding_model="retrieval-benchmark",
                    embedding_version="1",
                    embedding_dimension=768,
                    extra_data={},
                ),
                *[
                    SemanticMemory(
                        user_id=user_id,
                        content=f"irrelevant candidate {index}",
                        embedding=_vector(0.0, 1.0),
                        purpose="benchmark",
                        embedding_model="retrieval-benchmark",
                        embedding_version="1",
                        embedding_dimension=768,
                        extra_data={},
                    )
                    for index in range(300)
                ],
            ]
        )
        session.commit()

    try:
        async with AsyncSessionLocal() as session:
            memory = PostgresMemoryService(
                session,
                BenchmarkEmbeddingProvider(),
                SemanticRetrievalPolicy(),
                "1",
            )
            result = await MemoryRetrievalEvaluator(memory).evaluate(
                user_id=user_id,
                query="find benchmark target",
                expected_content=target,
                iterations=25,
                warmups=2,
                top_k=5,
            )

        assert result["hit_rate"] == 1.0
        assert result["result_count_min"] == 1
        assert result["result_count_max"] == 1
        assert result["latency_ms"]["p95"] < 500
    finally:
        with SessionLocal() as session:
            session.execute(
                delete(SemanticMemory).where(
                    SemanticMemory.user_id.in_([user_id, other_user])
                )
            )
            session.commit()
