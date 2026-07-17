import os
import uuid

from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.core.dependencies import get_embedding_provider
from backend.embeddings.base import EmbeddingProvider
from backend.main import app


def vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 766)]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    model = "tool-test-embedding"

    def embed_text(self, text: str) -> list[float]:
        return vector(0.0, 1.0) if "email" in text else vector(1.0)

    def embed_query(self, query: str) -> list[float]:
        return vector(0.0, 1.0) if "email" in query else vector(1.0)


def descriptor_payload(fingerprint: str, description: str = "List calendar events"):
    return {
        "server_id": "calendar-mcp",
        "tool_name": "list_events",
        "description": description,
        "input_purpose": "Select a calendar and date range",
        "schema_fingerprint": fingerprint,
        "tool_version": "1.0.0",
        "risk_classification": "read_only",
    }


def test_tool_memory_indexes_safe_descriptors_preferences_and_outcomes():
    user_id = f"tool_{uuid.uuid4()}"
    other_user = f"tool_{uuid.uuid4()}"
    trace_id = str(uuid.uuid4())
    first_fingerprint = "a" * 64
    second_fingerprint = "b" * 64
    app.dependency_overrides[get_embedding_provider] = (
        lambda: DeterministicEmbeddingProvider()
    )

    try:
        with TestClient(app) as client:
            first = client.post(
                f"/api/v1/memory/{user_id}/tools/descriptors",
                json=descriptor_payload(first_fingerprint),
            )
            repeated = client.post(
                f"/api/v1/memory/{user_id}/tools/descriptors",
                json=descriptor_payload(first_fingerprint),
            )
            changed = client.post(
                f"/api/v1/memory/{user_id}/tools/descriptors",
                json=descriptor_payload(
                    second_fingerprint, "List current calendar events"
                ),
            )
            assert first.status_code == 201
            assert repeated.json()["id"] == first.json()["id"]
            assert changed.status_code == 201
            assert changed.json()["id"] != first.json()["id"]

            search = client.get(
                f"/api/v1/memory/{user_id}/tools/search",
                params={"query": "calendar events", "server_id": "calendar-mcp"},
            )
            assert search.status_code == 200
            fingerprints = [
                item["schema_fingerprint"] for item in search.json()["descriptors"]
            ]
            assert fingerprints == [second_fingerprint]
            assert search.json()["descriptors"][0]["retrieval"] == {
                "cosine_distance": 0.0,
                "relevance_score": 1.0,
            }

            other_search = client.get(
                f"/api/v1/memory/{other_user}/tools/search",
                params={"query": "calendar events"},
            )
            assert other_search.json()["descriptors"] == []

            preference = client.post(
                f"/api/v1/memory/{user_id}/tools/preferences",
                json={
                    "server_id": "calendar-mcp",
                    "tool_name": "list_events",
                    "preference_key": "preferred_for",
                    "value": "work calendar lookups",
                    "purpose": "tool_personalization",
                    "source_trace_id": trace_id,
                },
            )
            outcome = client.post(
                f"/api/v1/memory/{user_id}/tools/outcomes",
                json={
                    "server_id": "calendar-mcp",
                    "tool_name": "list_events",
                    "outcome_category": "success",
                    "source_trace_id": trace_id,
                },
            )
            assert preference.status_code == 201
            assert preference.json()["approval_state"] == "approved"
            assert outcome.status_code == 201
            assert outcome.json()["extra_data"] == {}

            snapshot = client.get(f"/api/v1/memory/{user_id}/tools").json()
            assert [item["active"] for item in snapshot["descriptors"]] == [
                False,
                True,
            ]
            assert len(snapshot["preferences"]) == 1
            assert len(snapshot["outcomes"]) == 1

            blocked_descriptor = client.post(
                f"/api/v1/memory/{user_id}/tools/descriptors",
                json=descriptor_payload("c" * 64, "Use an API token to list events"),
            )
            blocked_preference = client.post(
                f"/api/v1/memory/{user_id}/tools/preferences",
                json={
                    "server_id": "calendar-mcp",
                    "tool_name": "list_events",
                    "preference_key": "display_label",
                    "value": "secret abc123",
                    "source_trace_id": trace_id,
                },
            )
            assert blocked_descriptor.status_code == 422
            assert blocked_preference.status_code == 422

            missing_tool = client.post(
                f"/api/v1/memory/{user_id}/tools/outcomes",
                json={
                    "server_id": "missing-mcp",
                    "tool_name": "missing_tool",
                    "outcome_category": "success",
                    "source_trace_id": trace_id,
                },
            )
            assert missing_tool.status_code == 409

            deleted = client.delete(f"/api/v1/memory/{user_id}/tools")
            assert deleted.json()["deleted"] == {
                "outcomes": 1,
                "preferences": 1,
                "descriptors": 2,
            }
            assert client.get(f"/api/v1/memory/{user_id}/tools").json() == {
                "descriptors": [],
                "preferences": [],
                "outcomes": [],
            }
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        with TestClient(app) as client:
            client.delete(f"/api/v1/memory/{user_id}/tools")
            client.delete(f"/api/v1/memory/{other_user}/tools")
