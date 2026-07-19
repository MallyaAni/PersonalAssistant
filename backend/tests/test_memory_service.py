import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Inject a mock secret key for testing purposes to satisfy Pydantic validation
os.environ["SECRET_KEY"] = "test_secret_key_only_for_testing"

from backend.database.session import async_engine
from backend.embeddings.base import EmbeddingProvider
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.models.memory import SemanticMemory, UserProfile
from backend.services.postgres_memory_service import PostgresMemoryService


def vector(first: float, second: float = 0.0):
    return [first, second, *([0.0] * 766)]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    def embed_text(self, text):
        return vector(0.0, 1.0) if "coffee" in text else vector(1.0)

    def embed_query(self, query):
        return vector(0.0, 1.0) if "coffee" in query else vector(1.0)


# Yield an async session whose committed work is rolled back after each test.
@pytest_asyncio.fixture
async def db_session():
    connection = await async_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


# Build the memory service with the rollback-scoped async session.
@pytest.fixture
def memory_service(db_session):
    return PostgresMemoryService(db_session, DeterministicEmbeddingProvider())


@pytest.mark.asyncio
async def test_get_user_profile(memory_service):
    profile = await memory_service.get_user_profile("non_existent_id")
    assert profile["user_id"] == "non_existent_id"
    assert "preferences" in profile


@pytest.mark.asyncio
async def test_save_user_profile(memory_service):
    user_id = f"test_user_{uuid.uuid4()}"
    new_profile = await memory_service.save_user_profile(
        UserProfile(user_id=user_id, name="Test User", preferences={"theme": "dark"})
    )
    assert new_profile.user_id == user_id
    assert new_profile.name == "Test User"


@pytest.mark.asyncio
async def test_save_episodic_memory(memory_service):
    user_id = f"test_user_{uuid.uuid4()}"
    content = "This is a test episodic memory."
    await memory_service.save_episodic_memory(user_id, content, {"source": "manual"})

    memories = await memory_service.get_episodic_memory(user_id, "test")
    assert len(memories) > 0
    assert memories[0]["content"] == content
    assert memories[0]["extra_data"] == {"source": "manual"}


@pytest.mark.asyncio
async def test_episodic_memory_is_scoped_to_requested_user(memory_service):
    requested_user = f"test_user_{uuid.uuid4()}"
    other_user = f"test_user_{uuid.uuid4()}"
    await memory_service.save_episodic_memory(
        requested_user,
        "Requested user's memory",
        {},
    )
    await memory_service.save_episodic_memory(
        other_user,
        "Other user's private memory",
        {},
    )

    memories = await memory_service.get_episodic_memory(requested_user, "memory")

    assert [memory["content"] for memory in memories] == ["Requested user's memory"]


@pytest.mark.asyncio
async def test_save_semantic_memory(memory_service, db_session):
    user_id = f"test_user_{uuid.uuid4()}"
    content = f"The user prefers jasmine tea {uuid.uuid4()}."
    await memory_service.save_semantic_memory(
        user_id,
        content,
        {"type": "preference"},
    )

    saved = (
        await db_session.execute(
            select(SemanticMemory).where(SemanticMemory.content == content)
        )
    ).scalar_one()
    assert saved.user_id == user_id
    assert saved.content == content
    assert saved.extra_data == {"type": "preference"}


@pytest.mark.asyncio
async def test_semantic_memory_retrieval_is_relevant_and_user_scoped(memory_service):
    user_id = f"test_user_{uuid.uuid4()}"
    other_user = f"test_user_{uuid.uuid4()}"
    await memory_service.save_semantic_memory(
        user_id,
        "The user likes jasmine tea.",
        {},
    )
    await memory_service.save_semantic_memory(
        user_id,
        "The user likes coffee.",
        {},
    )
    await memory_service.save_semantic_memory(
        other_user,
        "Other user's jasmine tea secret.",
        {},
    )

    memories = await memory_service.get_semantic_memory(
        user_id,
        "What tea does the user like?",
        top_k=1,
    )

    assert [memory["content"] for memory in memories] == ["The user likes jasmine tea."]
    assert memories[0]["retrieval"] == {
        "cosine_distance": 0.0,
        "relevance_score": 1.0,
    }


@pytest.mark.asyncio
async def test_semantic_memory_retrieval_excludes_threshold_misses(memory_service):
    user_id = f"test_user_{uuid.uuid4()}"
    await memory_service.save_semantic_memory(
        user_id,
        "The user likes coffee.",
        {},
    )

    memories = await memory_service.get_semantic_memory(
        user_id,
        "What tea does the user like?",
    )

    assert memories == []


@pytest.mark.asyncio
async def test_semantic_memory_retrieval_applies_content_budget(db_session):
    service = PostgresMemoryService(
        db_session,
        DeterministicEmbeddingProvider(),
        SemanticRetrievalPolicy(max_content_chars=25),
    )
    user_id = f"test_user_{uuid.uuid4()}"
    await service.save_semantic_memory(user_id, "tea memory one", {})
    await service.save_semantic_memory(user_id, "tea memory two", {})

    memories = await service.get_semantic_memory(user_id, "tea", top_k=5)

    assert len(memories) == 1
    assert len(memories[0]["content"]) <= 25


@pytest.mark.asyncio
async def test_semantic_memory_embedding_failure_is_not_treated_as_empty(db_session):
    class FailingEmbeddingProvider(DeterministicEmbeddingProvider):
        def embed_query(self, query):
            raise RuntimeError("embedding unavailable")

    service = PostgresMemoryService(db_session, FailingEmbeddingProvider())

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await service.get_semantic_memory("failure_user", "tea")
