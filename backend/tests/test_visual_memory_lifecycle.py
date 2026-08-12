"""Keep the derived visual index aligned with owned artifact lifecycle."""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.database.session import ASYNC_DATABASE_URL
from backend.memory.purposes import VISUAL_ANALYSIS_PURPOSE
from backend.memory.repository import MemoryRepository
from backend.models.artifact import VisualArtifact
from backend.models.memory import SemanticMemory
from backend.services.artifact_deletion_service import ArtifactDeletionService
from backend.services.artifact_repository import SQLAlchemyArtifactRepository

pytestmark = pytest.mark.asyncio


# Open PostgreSQL because the JSON join and vector ordering are under test.
@pytest_asyncio.fixture
async def session() -> AsyncGenerator[Any, None]:
    engine = create_async_engine(ASYNC_DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as opened:
            await opened.connection()
    except Exception as exc:  # pragma: no cover - depends on the host
        await engine.dispose()
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    async with factory() as opened:
        yield opened
    await engine.dispose()


# Build one ready owned image without invoking binary storage or a vision model.
def _artifact(user_id: str, artifact_id: uuid.UUID) -> VisualArtifact:
    return VisualArtifact(
        id=artifact_id,
        user_id=user_id,
        conversation_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        kind="uploaded_image",
        status="ready",
        title="Lifecycle test image",
        provider="test",
        extra_data={"analysis": "A tailored navy jacket and straw hat."},
    )


# Build one derived description that points back to an artifact handle.
def _memory(user_id: str, artifact_id: uuid.UUID) -> SemanticMemory:
    vector = [0.0] * 768
    vector[0] = 1.0
    return SemanticMemory(
        user_id=user_id,
        content="Description of an uploaded image: tailored navy jacket and straw hat.",
        embedding=vector,
        purpose=VISUAL_ANALYSIS_PURPOSE,
        embedding_model="test",
        embedding_version="test",
        embedding_dimension=768,
        extra_data={"artifact_id": str(artifact_id), "source": "vision_analysis"},
    )


# Remove the unique test account's rows after a repository commit.
async def _cleanup(session: Any, user_id: str) -> None:
    await session.execute(
        delete(SemanticMemory).where(SemanticMemory.user_id == user_id)
    )
    await session.execute(
        delete(VisualArtifact).where(VisualArtifact.user_id == user_id)
    )
    await session.commit()


# Stale descriptions must not consume the bounded shortlist ahead of live images.
async def test_visual_candidates_require_a_live_owned_artifact(session: Any) -> None:
    user_id = f"vl-{uuid.uuid4().hex[:24]}"
    live_id = uuid.uuid4()
    orphan_id = uuid.uuid4()
    live = _memory(user_id, live_id)
    orphan = _memory(user_id, orphan_id)
    session.add_all([_artifact(user_id, live_id), live, orphan])
    await session.commit()
    try:
        vector = [0.0] * 768
        vector[0] = 1.0

        rows = await MemoryRepository(session).get_visual_semantic_memories(
            user_id, vector, top_k=1, max_cosine_distance=0.65
        )

        assert [memory.id for memory, _distance in rows] == [live.id]
    finally:
        await _cleanup(session, user_id)


# Deleting an artifact must remove its derived description in the same database commit.
async def test_artifact_delete_removes_its_visual_memory(session: Any) -> None:
    user_id = f"vd-{uuid.uuid4().hex[:24]}"
    artifact_id = uuid.uuid4()
    memory = _memory(user_id, artifact_id)
    session.add_all([_artifact(user_id, artifact_id), memory])
    await session.commit()
    try:
        assert await SQLAlchemyArtifactRepository(session).delete(
            user_id, str(artifact_id)
        )

        assert (
            await session.scalar(
                select(SemanticMemory).where(SemanticMemory.id == memory.id)
            )
            is None
        )
    finally:
        await _cleanup(session, user_id)


# Deleting all memory must remove owned artifact rows and bytes without crossing users.
async def test_delete_all_owned_artifacts_removes_rows_bytes_and_visual_memory(
    session: Any,
    tmp_path: Any,
) -> None:
    user_id = f"va-{uuid.uuid4().hex[:24]}"
    other_user = f"vo-{uuid.uuid4().hex[:24]}"
    artifact_id = uuid.uuid4()
    diagram_id = uuid.uuid4()
    other_id = uuid.uuid4()
    store = LocalBinaryArtifactStore(tmp_path)
    owned_binary = await store.write(user_id, str(artifact_id), "png", b"owned")
    other_binary = await store.write(other_user, str(other_id), "png", b"other")
    owned = _artifact(user_id, artifact_id)
    owned.storage_key = owned_binary.storage_key
    diagram = _artifact(user_id, diagram_id)
    diagram.kind = "diagram"
    other = _artifact(other_user, other_id)
    other.storage_key = other_binary.storage_key
    session.add_all([owned, diagram, other, _memory(user_id, artifact_id)])
    await session.commit()
    try:
        deleted = await ArtifactDeletionService(
            SQLAlchemyArtifactRepository(session), store
        ).delete_all_owned(user_id)

        assert deleted == 2
        assert not store._path_for_key(owned_binary.storage_key).exists()
        assert store._path_for_key(other_binary.storage_key).exists()
        assert not (
            await session.scalars(
                select(VisualArtifact).where(VisualArtifact.user_id == user_id)
            )
        ).all()
        assert len(
            (
                await session.scalars(
                    select(VisualArtifact).where(
                        VisualArtifact.user_id == other_user
                    )
                )
            ).all()
        ) == 1
        assert not (
            await session.scalars(
                select(SemanticMemory).where(SemanticMemory.user_id == user_id)
            )
        ).all()
    finally:
        await _cleanup(session, user_id)
        await _cleanup(session, other_user)
        await store.delete(other_binary.storage_key)
