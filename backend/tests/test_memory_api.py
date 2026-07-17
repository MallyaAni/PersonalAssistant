import os
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.core.dependencies import get_embedding_provider
from backend.database.session import SessionLocal
from backend.embeddings.base import EmbeddingProvider
from backend.main import app
from backend.models.conversation import Conversation
from backend.models.memory import (
    EpisodicMemory,
    MemoryFact,
    SemanticMemory,
    UserProfile,
)


def vector(first: float, second: float = 0.0):
    return [first, second, *([0.0] * 766)]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    def embed_text(self, text):
        return vector(0.0, 1.0) if "coffee" in text else vector(1.0)

    def embed_query(self, query):
        return vector(0.0, 1.0) if "coffee" in query else vector(1.0)


def _remove_test_user(user_id: str):
    with SessionLocal() as session:
        session.execute(delete(MemoryFact).where(MemoryFact.user_id == user_id))
        session.execute(delete(SemanticMemory).where(SemanticMemory.user_id == user_id))
        session.execute(delete(EpisodicMemory).where(EpisodicMemory.user_id == user_id))
        session.execute(delete(UserProfile).where(UserProfile.user_id == user_id))
        session.commit()


def test_memory_api_persists_searches_scopes_and_deletes_personal_memory():
    user_id = f"memory_api_{uuid.uuid4()}"
    other_user = f"memory_api_{uuid.uuid4()}"
    app.dependency_overrides[get_embedding_provider] = (
        lambda: DeterministicEmbeddingProvider()
    )

    try:
        with TestClient(app) as client:
            profile = client.put(
                f"/api/v1/memory/{user_id}/profile",
                json={
                    "name": "Memory Test User",
                    "preferences": {"response_style": "concise"},
                },
            )
            episodic = client.post(
                f"/api/v1/memory/{user_id}/episodic",
                json={
                    "content": "The user visited Kyoto in spring.",
                    "metadata": {"source": "user"},
                },
            )
            semantic = client.post(
                f"/api/v1/memory/{user_id}/semantic",
                json={
                    "content": "The user likes jasmine tea.",
                    "metadata": {"kind": "preference"},
                },
            )

            assert profile.status_code == 200
            assert profile.json()["name"] == "Memory Test User"
            assert episodic.status_code == 201
            assert semantic.status_code == 201

            updated_profile = client.put(
                f"/api/v1/memory/{user_id}/profile",
                json={
                    "name": "Updated Memory User",
                    "preferences": {"response_style": "detailed"},
                },
            )
            assert updated_profile.status_code == 200
            assert updated_profile.json()["name"] == "Updated Memory User"

            snapshot = client.get(f"/api/v1/memory/{user_id}")
            assert snapshot.status_code == 200
            assert snapshot.json()["profile"]["preferences"] == {
                "response_style": "detailed"
            }
            assert [item["content"] for item in snapshot.json()["episodic"]] == [
                "The user visited Kyoto in spring."
            ]
            assert [item["content"] for item in snapshot.json()["semantic"]] == [
                "The user likes jasmine tea."
            ]

            search = client.get(
                f"/api/v1/memory/{user_id}/search",
                params={"query": "preferred tea", "top_k": 1},
            )
            assert search.status_code == 200
            assert [item["content"] for item in search.json()["memories"]] == [
                "The user likes jasmine tea."
            ]
            assert search.json()["memories"][0]["retrieval"] == {
                "cosine_distance": 0.0,
                "relevance_score": 1.0,
            }

            corrected = client.put(
                f"/api/v1/memory/{user_id}/semantic/{semantic.json()['id']}",
                json={
                    "content": "The user likes coffee.",
                    "metadata": {"kind": "corrected_preference"},
                },
            )
            assert corrected.status_code == 200
            assert corrected.json()["content"] == "The user likes coffee."
            coffee_search = client.get(
                f"/api/v1/memory/{user_id}/search",
                params={"query": "preferred coffee", "top_k": 1},
            )
            assert [item["content"] for item in coffee_search.json()["memories"]] == [
                "The user likes coffee."
            ]

            export = client.get(f"/api/v1/memory/{user_id}/export")
            assert export.status_code == 200
            assert export.json()["schema_version"] == 1
            assert export.json()["user_id"] == user_id
            assert export.json()["memory"]["semantic"][0]["content"] == (
                "The user likes coffee."
            )
            assert export.json()["conversations"] == []

            cross_user_update = client.put(
                f"/api/v1/memory/{other_user}/semantic/{semantic.json()['id']}",
                json={"content": "stolen", "metadata": {}},
            )
            assert cross_user_update.status_code == 404

            cross_user_delete = client.delete(
                f"/api/v1/memory/{other_user}/semantic/{semantic.json()['id']}"
            )
            assert cross_user_delete.status_code == 404

            record_delete = client.delete(
                f"/api/v1/memory/{user_id}/episodic/{episodic.json()['id']}"
            )
            assert record_delete.status_code == 200
            assert record_delete.json() == {"deleted": True}

            deleted = client.delete(f"/api/v1/memory/{user_id}")
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] == {
                "tool_outcomes": 0,
                "tool_preferences": 0,
                "tool_descriptors": 0,
                "facts": 0,
                "profiles": 1,
                "episodic": 0,
                "semantic": 1,
                "conversations": 0,
            }

            empty_snapshot = client.get(f"/api/v1/memory/{user_id}").json()
            assert empty_snapshot["profile"] == {
                "user_id": user_id,
                "preferences": {},
            }
            assert empty_snapshot["episodic"] == []
            assert empty_snapshot["semantic"] == []

        with SessionLocal() as session:
            assert (
                session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id)
                ).scalar_one_or_none()
                is None
            )
            assert (
                session.execute(
                    select(EpisodicMemory).where(EpisodicMemory.user_id == user_id)
                )
                .scalars()
                .all()
                == []
            )
            assert (
                session.execute(
                    select(SemanticMemory).where(SemanticMemory.user_id == user_id)
                )
                .scalars()
                .all()
                == []
            )
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _remove_test_user(user_id)
        _remove_test_user(other_user)


def test_memory_api_rejects_empty_memory_content():
    app.dependency_overrides[get_embedding_provider] = (
        lambda: DeterministicEmbeddingProvider()
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/memory/validation_user/semantic",
                json={"content": "", "metadata": {}},
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)


def test_preferred_name_approval_correction_deletion_and_user_scoping():
    user_id = f"pname_{uuid.uuid4()}"
    other_user = f"pname_{uuid.uuid4()}"

    try:
        with TestClient(app) as client:
            before = client.get(f"/api/v1/memory/{user_id}")
            assert "name" not in before.json()["profile"]

            seeded_profile = client.put(
                f"/api/v1/memory/{user_id}/profile",
                json={
                    "name": None,
                    "preferences": {"response_style": "concise"},
                },
            )
            assert seeded_profile.status_code == 200

            approved = client.post(
                f"/api/v1/memory/{user_id}/profile/preferred-name",
                json={
                    "name": "Approved Name",
                    "source_conversation_id": "11111111-1111-4111-8111-111111111111",
                    "source_trace_id": "22222222-2222-4222-8222-222222222222",
                },
            )
            assert approved.status_code == 200
            assert approved.json()["profile"]["name"] == "Approved Name"
            assert approved.json()["profile"]["preferences"] == {
                "response_style": "concise"
            }
            first_fact = approved.json()["fact"]
            assert first_fact["fact_type"] == "profile"
            assert first_fact["fact_key"] == "preferred_name"
            assert first_fact["approval_state"] == "approved"
            assert first_fact["confidence"] == 1.0
            assert first_fact["purpose"] == "personalization"
            assert first_fact["source_conversation_id"] == (
                "11111111-1111-4111-8111-111111111111"
            )
            assert first_fact["source_trace_id"] == (
                "22222222-2222-4222-8222-222222222222"
            )
            assert first_fact["version"] == 1
            assert first_fact["supersedes_id"] is None
            assert first_fact["embedding_model"] is None

            other_snapshot = client.get(f"/api/v1/memory/{other_user}")
            assert "name" not in other_snapshot.json()["profile"]

            corrected = client.post(
                f"/api/v1/memory/{user_id}/profile/preferred-name",
                json={
                    "name": "Corrected Name",
                    "source_conversation_id": "33333333-3333-4333-8333-333333333333",
                    "source_trace_id": "44444444-4444-4444-8444-444444444444",
                },
            )
            assert corrected.status_code == 200
            assert corrected.json()["profile"]["name"] == "Corrected Name"
            assert corrected.json()["fact"]["version"] == 2
            assert corrected.json()["fact"]["supersedes_id"] == first_fact["id"]

            fact_snapshot = client.get(f"/api/v1/memory/{user_id}").json()
            assert [fact["approval_state"] for fact in fact_snapshot["facts"]] == [
                "approved",
                "superseded",
            ]

            cleared = client.delete(f"/api/v1/memory/{user_id}/profile/preferred-name")
            assert cleared.status_code == 200
            assert cleared.json()["name"] is None

        with SessionLocal() as session:
            profile = session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            ).scalar_one()
            assert profile.name is None
            assert (
                session.execute(select(MemoryFact).where(MemoryFact.user_id == user_id))
                .scalars()
                .all()
                == []
            )
            assert (
                session.execute(
                    select(UserProfile).where(UserProfile.user_id == other_user)
                ).scalar_one_or_none()
                is None
            )
    finally:
        _remove_test_user(user_id)
        _remove_test_user(other_user)


def test_preferred_name_approval_rejects_blank_and_extra_input():
    with TestClient(app) as client:
        blank = client.post(
            "/api/v1/memory/validation_user/profile/preferred-name",
            json={
                "name": "   ",
                "source_conversation_id": "11111111-1111-4111-8111-111111111111",
                "source_trace_id": "22222222-2222-4222-8222-222222222222",
            },
        )
        extra = client.post(
            "/api/v1/memory/validation_user/profile/preferred-name",
            json={
                "name": "Valid",
                "source_conversation_id": "11111111-1111-4111-8111-111111111111",
                "source_trace_id": "22222222-2222-4222-8222-222222222222",
                "approved": True,
            },
        )

    assert blank.status_code == 422
    assert extra.status_code == 422


def test_preferred_name_approval_is_idempotent_per_source_trace():
    user_id = f"pname_idem_{uuid.uuid4()}"
    payload = {
        "name": "Idempotent Name",
        "source_conversation_id": "11111111-1111-4111-8111-111111111111",
        "source_trace_id": "22222222-2222-4222-8222-222222222222",
    }

    try:
        with TestClient(app) as client:
            first = client.post(
                f"/api/v1/memory/{user_id}/profile/preferred-name", json=payload
            )
            repeated = client.post(
                f"/api/v1/memory/{user_id}/profile/preferred-name", json=payload
            )
            conflict = client.post(
                f"/api/v1/memory/{user_id}/profile/preferred-name",
                json={**payload, "name": "Different Name"},
            )

        assert first.status_code == 200
        assert repeated.status_code == 200
        assert repeated.json()["fact"]["id"] == first.json()["fact"]["id"]
        assert repeated.json()["fact"]["version"] == 1
        assert conflict.status_code == 409

        with SessionLocal() as session:
            facts = (
                session.execute(select(MemoryFact).where(MemoryFact.user_id == user_id))
                .scalars()
                .all()
            )
            assert len(facts) == 1
    finally:
        _remove_test_user(user_id)


def test_expired_preferred_name_is_not_supplied_as_current_memory():
    user_id = f"expiry_{uuid.uuid4()}"
    future = datetime.now(UTC) + timedelta(days=1)

    try:
        with TestClient(app) as client:
            approved = client.post(
                f"/api/v1/memory/{user_id}/profile/preferred-name",
                json={
                    "name": "Temporary Name",
                    "source_conversation_id": "11111111-1111-4111-8111-111111111111",
                    "source_trace_id": "22222222-2222-4222-8222-222222222222",
                    "expires_at": future.isoformat(),
                },
            )
            assert approved.status_code == 200
            assert approved.json()["fact"]["expires_at"] is not None

        with SessionLocal() as session:
            session.execute(
                update(MemoryFact)
                .where(MemoryFact.user_id == user_id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            session.commit()

        with TestClient(app) as client:
            snapshot = client.get(f"/api/v1/memory/{user_id}").json()
            assert snapshot["profile"]["name"] is None
            assert snapshot["facts"][0]["approval_state"] == "approved"
    finally:
        _remove_test_user(user_id)


def test_preferred_name_approval_rejects_past_or_naive_expiry():
    base_payload = {
        "name": "Temporary Name",
        "source_conversation_id": "11111111-1111-4111-8111-111111111111",
        "source_trace_id": "22222222-2222-4222-8222-222222222222",
    }
    with TestClient(app) as client:
        past = client.post(
            "/api/v1/memory/validation_user/profile/preferred-name",
            json={
                **base_payload,
                "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            },
        )
        naive = client.post(
            "/api/v1/memory/validation_user/profile/preferred-name",
            json={**base_payload, "expires_at": "2030-01-01T00:00:00"},
        )

    assert past.status_code == 422
    assert naive.status_code == 422


def test_semantic_memory_metadata_and_expiry_are_enforced():
    user_id = f"sem_exp_{uuid.uuid4()}"
    app.dependency_overrides[get_embedding_provider] = (
        lambda: DeterministicEmbeddingProvider()
    )
    future = datetime.now(UTC) + timedelta(days=1)

    try:
        with TestClient(app) as client:
            created = client.post(
                f"/api/v1/memory/{user_id}/semantic",
                json={
                    "content": "Temporary jasmine tea preference.",
                    "metadata": {"source": "expiry_test"},
                    "purpose": "temporary_personalization",
                    "expires_at": future.isoformat(),
                },
            )
            assert created.status_code == 201
            assert created.json()["purpose"] == "temporary_personalization"
            assert created.json()["embedding_model"] == "unknown"
            assert created.json()["embedding_version"] == "nomic-embed-text-v1.5"
            assert created.json()["embedding_dimension"] == 768
            assert created.json()["expires_at"] is not None

        with SessionLocal() as session:
            session.execute(
                update(SemanticMemory)
                .where(SemanticMemory.user_id == user_id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            session.commit()

        with TestClient(app) as client:
            search = client.get(
                f"/api/v1/memory/{user_id}/search",
                params={"query": "jasmine tea"},
            )
            assert search.status_code == 200
            assert search.json()["memories"] == []
            export = client.get(f"/api/v1/memory/{user_id}/export").json()
            assert export["memory"]["semantic"][0]["content"] == (
                "Temporary jasmine tea preference."
            )
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _remove_test_user(user_id)


def test_delete_all_propagates_to_conversations_and_tool_memory():
    user_id = f"prop_{uuid.uuid4()}"
    app.dependency_overrides[get_embedding_provider] = (
        lambda: DeterministicEmbeddingProvider()
    )
    descriptor = {
        "server_id": "calendar-mcp",
        "tool_name": "list_events",
        "description": "List calendar events",
        "input_purpose": "Select a calendar and date range",
        "schema_fingerprint": "d" * 64,
        "tool_version": "1.0.0",
        "risk_classification": "read_only",
    }

    try:
        with SessionLocal() as session:
            session.add(
                Conversation(
                    conversation_id=uuid.uuid4(),
                    user_id=user_id,
                    query="private query",
                    response="private response",
                    extra_data={},
                )
            )
            session.commit()

        with TestClient(app) as client:
            created = client.post(
                f"/api/v1/memory/{user_id}/tools/descriptors", json=descriptor
            )
            assert created.status_code == 201
            exported = client.get(f"/api/v1/memory/{user_id}/export").json()
            assert len(exported["conversations"]) == 1

            deleted = client.delete(f"/api/v1/memory/{user_id}").json()["deleted"]
            assert deleted["tool_descriptors"] == 1
            assert deleted["conversations"] == 1
            assert (
                client.get(f"/api/v1/memory/{user_id}/export").json()["conversations"]
                == []
            )
            assert (
                client.get(f"/api/v1/memory/{user_id}/tools").json()["descriptors"]
                == []
            )
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _remove_test_user(user_id)
