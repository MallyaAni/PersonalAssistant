import os
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.core.dependencies import get_embedding_provider
from backend.embeddings.base import EmbeddingProvider
from backend.main import app


# Build a deterministic embedding vector for API tests.
def vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 766)]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    model = "agent-memory-test-embedding"

    # Return deterministic stored-text embeddings for tests.
    def embed_text(self, text: str) -> list[float]:
        return vector(0.0, 1.0) if "project" in text.casefold() else vector(1.0)

    # Return deterministic query embeddings for tests.
    def embed_query(self, query: str) -> list[float]:
        return vector(0.0, 1.0) if "project" in query.casefold() else vector(1.0)


# Remove test-owned memory through the public deletion API.
def _cleanup(*user_ids: str) -> None:
    with TestClient(app) as client:
        for user_id in user_ids:
            client.delete(f"/api/v1/memory/{user_id}/agent")


# Verify cache and working memory are user-scoped and expire correctly.
def test_semantic_cache_and_session_working_memory_are_scoped_and_expiring():
    user_id = f"agent_cache_{uuid.uuid4()}"
    other_user = f"agent_cache_{uuid.uuid4()}"
    conversation_id = str(uuid.uuid4())
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    app.dependency_overrides[get_embedding_provider] = (
        lambda: DeterministicEmbeddingProvider()
    )

    try:
        with TestClient(app) as client:
            cached = client.put(
                f"/api/v1/memory/{user_id}/agent/cache",
                json={
                    "query": "How should I format this?",
                    "response": '{"stores":["persona"]}',
                    "model": "memory-coordinator-v1",
                    "expires_at": expires_at.isoformat(),
                },
            )
            assert cached.status_code == 200
            hit = client.get(
                f"/api/v1/memory/{user_id}/agent/cache",
                params={
                    "query": "How should I format this?",
                    "model": "memory-coordinator-v1",
                },
            )
            assert hit.status_code == 200
            assert hit.json()["entry"]["response"] == '{"stores":["persona"]}'
            assert hit.json()["entry"]["hit_count"] == 1
            other_hit = client.get(
                f"/api/v1/memory/{other_user}/agent/cache",
                params={
                    "query": "How should I format this?",
                    "model": "memory-coordinator-v1",
                },
            )
            assert other_hit.json()["entry"] is None

            working = client.put(
                f"/api/v1/memory/{user_id}/agent/working",
                json={
                    "conversation_id": conversation_id,
                    "memory_key": "current_goal",
                    "value": "Finish the migration",
                    "purpose": "session_coordination",
                    "expires_at": expires_at.isoformat(),
                },
            )
            assert working.status_code == 200
            listed = client.get(
                f"/api/v1/memory/{user_id}/agent/working/{conversation_id}"
            )
            assert [item["memory_key"] for item in listed.json()["items"]] == [
                "current_goal"
            ]
            assert (
                client.get(
                    f"/api/v1/memory/{other_user}/agent/working/{conversation_id}"
                ).json()["items"]
                == []
            )

            invalid_expiry = client.put(
                f"/api/v1/memory/{user_id}/agent/working",
                json={
                    "conversation_id": conversation_id,
                    "memory_key": "expired",
                    "value": "never persist",
                    "purpose": "validation",
                    "expires_at": (
                        datetime.now(UTC) - timedelta(seconds=1)
                    ).isoformat(),
                },
            )
            assert invalid_expiry.status_code == 422
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _cleanup(user_id, other_user)


# Verify procedural and entity memory require approval and user ownership.
def test_procedure_entity_and_relation_memory_are_approved_and_user_scoped():
    user_id = f"as_{uuid.uuid4()}"
    other_user = f"as_{uuid.uuid4()}"
    trace_id = str(uuid.uuid4())
    app.dependency_overrides[get_embedding_provider] = (
        lambda: DeterministicEmbeddingProvider()
    )

    try:
        with TestClient(app) as client:
            procedure_payload = {
                "name": "Weekly project review",
                "description": "Review current project progress",
                "steps": [{"order": 1, "instruction": "Open the project board"}],
                "source_trace_id": trace_id,
                "metadata": {"source": "explicit_test"},
            }
            first = client.post(
                f"/api/v1/memory/{user_id}/agent/procedures",
                json=procedure_payload,
            )
            second = client.post(
                f"/api/v1/memory/{user_id}/agent/procedures",
                json={
                    **procedure_payload,
                    "description": "Review the project and note blockers",
                },
            )
            assert first.status_code == 201
            assert first.json()["version"] == 1
            assert second.json()["version"] == 2
            procedures = client.get(
                f"/api/v1/memory/{user_id}/agent/procedures/search",
                params={"query": "project review"},
            ).json()["procedures"]
            assert [item["version"] for item in procedures] == [2]
            assert (
                client.get(
                    f"/api/v1/memory/{other_user}/agent/procedures/search",
                    params={"query": "project review"},
                ).json()["procedures"]
                == []
            )

            person = client.put(
                f"/api/v1/memory/{user_id}/agent/entities",
                json={
                    "entity_type": "person",
                    "canonical_name": "Avery",
                    "attributes": {"role": "designer"},
                    "source_trace_id": trace_id,
                },
            )
            project = client.put(
                f"/api/v1/memory/{user_id}/agent/entities",
                json={
                    "entity_type": "project",
                    "canonical_name": "Northstar project",
                    "attributes": {"status": "active"},
                    "source_trace_id": trace_id,
                },
            )
            assert person.status_code == 200
            assert project.status_code == 200
            relation = client.post(
                f"/api/v1/memory/{user_id}/agent/entity-relations",
                json={
                    "source_entity_id": person.json()["id"],
                    "target_entity_id": project.json()["id"],
                    "relation_type": "works_on",
                    "attributes": {},
                    "source_trace_id": trace_id,
                },
            )
            assert relation.status_code == 201
            entities = client.get(
                f"/api/v1/memory/{user_id}/agent/entities/search",
                params={"query": "project"},
            ).json()["entities"]
            assert entities[0]["canonical_name"] == "Northstar project"
            cross_user_relation = client.post(
                f"/api/v1/memory/{other_user}/agent/entity-relations",
                json={
                    "source_entity_id": person.json()["id"],
                    "target_entity_id": project.json()["id"],
                    "relation_type": "works_on",
                    "attributes": {},
                    "source_trace_id": trace_id,
                },
            )
            assert cross_user_relation.status_code == 404
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _cleanup(user_id, other_user)


# Verify knowledge and summary memory can be searched, counted, and deleted.
def test_knowledge_and_summary_memory_search_delete_and_snapshot():
    user_id = f"ak_{uuid.uuid4()}"
    other_user = f"ak_{uuid.uuid4()}"
    trace_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    app.dependency_overrides[get_embedding_provider] = (
        lambda: DeterministicEmbeddingProvider()
    )

    try:
        with TestClient(app) as client:
            document_payload = {
                "title": "Northstar project notes",
                "content": (
                    "The Northstar project uses a weekly review.\n\n"
                    "Its status is active."
                ),
                "source_uri": "local://northstar-notes",
                "purpose": "user_knowledge",
            }
            document = client.post(
                f"/api/v1/memory/{user_id}/agent/knowledge",
                json=document_payload,
            )
            duplicate = client.post(
                f"/api/v1/memory/{user_id}/agent/knowledge",
                json=document_payload,
            )
            assert document.status_code == 201
            assert duplicate.json()["id"] == document.json()["id"]
            assert len(document.json()["chunks"]) == 1
            chunks = client.get(
                f"/api/v1/memory/{user_id}/agent/knowledge/search",
                params={"query": "Northstar project"},
            ).json()["chunks"]
            assert chunks[0]["document"]["title"] == "Northstar project notes"
            assert (
                client.get(
                    f"/api/v1/memory/{other_user}/agent/knowledge/search",
                    params={"query": "Northstar project"},
                ).json()["chunks"]
                == []
            )

            summary = client.put(
                f"/api/v1/memory/{user_id}/agent/summaries",
                json={
                    "conversation_id": conversation_id,
                    "content": "We agreed to review the Northstar project weekly.",
                    "through_turn_count": 4,
                    "source_trace_id": trace_id,
                },
            )
            assert summary.status_code == 200
            latest = client.get(
                f"/api/v1/memory/{user_id}/agent/summaries/{conversation_id}"
            )
            assert latest.json()["summary"]["through_turn_count"] == 4
            summaries = client.get(
                f"/api/v1/memory/{user_id}/agent/summaries/search",
                params={"query": "project agreement"},
            ).json()["summaries"]
            assert summaries[0]["conversation_id"] == conversation_id

            snapshot = client.get(f"/api/v1/memory/{user_id}/agent").json()
            assert snapshot["knowledge_documents"] == 1
            assert snapshot["knowledge_chunks"] == 1
            assert snapshot["summaries"] == 1
            exported = client.get(f"/api/v1/memory/{user_id}/export").json()
            assert exported["agent_memory"]["knowledge_documents"][0]["title"] == (
                "Northstar project notes"
            )
            assert exported["agent_memory"]["summaries"][0]["through_turn_count"] == 4
            deleted_document = client.delete(
                f"/api/v1/memory/{user_id}/agent/knowledge/{document.json()['id']}"
            )
            assert deleted_document.status_code == 200
            deleted = client.delete(f"/api/v1/memory/{user_id}/agent").json()["deleted"]
            assert deleted["summaries"] == 1
            assert client.get(f"/api/v1/memory/{user_id}/agent").json() == {
                "semantic_cache": 0,
                "working": 0,
                "procedures": 0,
                "entities": 0,
                "entity_relations": 0,
                "knowledge_documents": 0,
                "knowledge_chunks": 0,
                "summaries": 0,
            }
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _cleanup(user_id, other_user)
