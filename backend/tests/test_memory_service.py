import os
import pytest
import asyncio
from typing import Dict, Any
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Inject a mock secret key for testing purposes to satisfy Pydantic validation
os.environ["SECRET_KEY"] = "test_secret_key_only_for_testing"

from backend.config.settings import settings
from backend.models.memory import UserProfile, EpisodicMemory, SemanticMemory
from backend.services.postgres_memory_service import PostgresMemoryService

# Use a dedicated test database if possible, or the existing one with a prefix
DATABASE_URL = f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"

engine = create_async_engine(DATABASE_URL, echo=False)
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture
def event_loop():
    """Run tests with shared loop."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def db_session():
    # This ensures the session is created within the correct loop
    async with TestingSessionLocal() as session:
        yield session

@pytest.fixture
async def memory_service(db_session):
    return PostgresMemoryService(db_session)

@pytest.mark.asyncio
async def test_get_user_profile(memory_service):
    # Test retrieval of a non-existent user (should return default dict per our service implementation)
    profile = await memory_service.get_user_profile("non_existent_id")
    assert profile["user_id"] == "non_existent_id"
    assert "preferences" in profile

@pytest.mark.asyncio
async def test_save_user_profile(memory_service):
    new_profile = await memory_service.save_user_profile(
        UserProfile(user_id="test_user_1", name="Test User", preferences={"theme": "dark"})
    )
    assert new_profile.user_id == "test_user_1"
    assert new_profile.name == "Test User"

@pytest.mark.asyncio
async def test_save_episodic_memory(memory_service):
    content = "This is a test episodic memory."
    await memory_service.save_episodic_memory("test_user_1", content, {"source": "manual"})
    
    memories = await memory_service.get_episodic_memories("test_user_1", "test")
    assert len(memories) > 0
    assert memories[0]["content"] == content

@pytest.mark.asyncio
async def test_save_semantic_memory(memory_service):
    # Note: This will fail if pgvector is not initialized or embedding dimension mismatch
    # We'll handle this as an "in-progress" check for the production environment
    content = "This is a semantic memory chunk."
    embedding = [0.1] * 1536 # Mocking 1536-dim vector
    await memory_service.save_semantic_memory(content, embedding, {"type": "knowledge"})
    
    memories = await memory_service.get_semantic_memories("query", top_k=1)
    assert len(memories) > 0
    assert memories[0]["content"] == content