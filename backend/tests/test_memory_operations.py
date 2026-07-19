import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.cli.check_memory_operations import main as check_memory_main
from backend.core.dependencies import get_embedding_provider
from backend.database.session import SessionLocal
from backend.embeddings.base import EmbeddingProvider
from backend.main import app
from backend.models.agent_memory import WorkingMemoryItem
from backend.models.memory import MemoryFact, SemanticMemory
from backend.services.memory_maintenance_service import MemoryMaintenanceService


class OperationsEmbeddingProvider(EmbeddingProvider):
    model = "operations-test-model"

    # Return one stable embedding for stored text.
    def embed_text(self, text: str) -> list[float]:
        return [1.0, *([0.0] * 767)]

    # Return one stable embedding for queries.
    def embed_query(self, query: str) -> list[float]:
        return self.embed_text(query)


# Delete all test-owned memory for the supplied users.
def _cleanup(*user_ids: str) -> None:
    with TestClient(app) as client:
        for user_id in user_ids:
            client.delete(f"/api/v1/memory/{user_id}")


# Verify operations reporting is scoped and detects maintenance backlog.
def test_operations_api_reports_scoped_backlog_vectors_and_invariants() -> None:
    user_id = f"ops_{uuid.uuid4()}"
    other_user = f"ops_{uuid.uuid4()}"
    app.dependency_overrides[get_embedding_provider] = (
        lambda: OperationsEmbeddingProvider()
    )

    try:
        with TestClient(app) as client:
            semantic = client.post(
                f"/api/v1/memory/{user_id}/semantic",
                json={"content": "operations semantic"},
            )
            assert semantic.status_code == 201

        with SessionLocal() as session:
            session.execute(
                update(SemanticMemory)
                .where(SemanticMemory.user_id == user_id)
                .values(embedding_model="retired-model")
            )
            session.add_all(
                [
                    WorkingMemoryItem(
                        user_id=user_id,
                        conversation_id=uuid.uuid4(),
                        memory_key="expired",
                        value="expired",
                        purpose="operations_test",
                        expires_at=datetime.now(UTC) - timedelta(hours=1),
                    ),
                    WorkingMemoryItem(
                        user_id=other_user,
                        conversation_id=uuid.uuid4(),
                        memory_key="expired-other",
                        value="expired",
                        purpose="operations_test",
                        expires_at=datetime.now(UTC) - timedelta(hours=1),
                    ),
                    MemoryFact(
                        user_id=user_id,
                        fact_type="preference",
                        fact_key="duplicate_key",
                        value="first",
                        normalized_value="first",
                        approval_state="approved",
                        confidence=1.0,
                        purpose="operations_test",
                        source_trace_id=uuid.uuid4(),
                        version=1,
                        extra_data={},
                    ),
                    MemoryFact(
                        user_id=user_id,
                        fact_type="preference",
                        fact_key="duplicate_key",
                        value="second",
                        normalized_value="second",
                        approval_state="approved",
                        confidence=1.0,
                        purpose="operations_test",
                        source_trace_id=uuid.uuid4(),
                        version=2,
                        extra_data={},
                    ),
                ]
            )
            session.commit()

        with TestClient(app) as client:
            response = client.get(f"/api/v1/memory/{user_id}/agent/operations")
            metrics_response = client.get(
                f"/api/v1/memory/{user_id}/agent/operations/metrics"
            )
        assert response.status_code == 200
        report = response.json()
        assert report["status"] == "attention"
        assert report["counts"]["semantic"] == 1
        assert report["counts"]["working"] == 1
        assert report["counts"]["facts"] == 2
        assert report["expired_backlog"]["working"] == 1
        assert report["expired_total"] == 1
        assert report["vectors"]["stale"]["semantic"] == 1
        assert report["vectors"]["stale_total"] == 1
        assert report["invariant_violations"] == {
            "fact_keys_with_multiple_approved": 1,
            "procedure_names_with_multiple_active": 0,
        }
        assert report["database"]["query_ok"] is True
        assert report["database"]["query_latency_ms"] >= 0
        assert report["database"]["pool"] == "NullPool"
        assert metrics_response.status_code == 200
        assert metrics_response.headers["content-type"].startswith("text/plain")
        assert 'anios_memory_records{store="semantic"} 1' in metrics_response.text
        assert "anios_memory_stale_vectors 1" in metrics_response.text
        assert "anios_memory_invariant_violations 1" in metrics_response.text
        assert "anios_memory_healthy 0" in metrics_response.text
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _cleanup(user_id, other_user)


# Verify the strict operations CLI succeeds for a clean user scope.
def test_operations_cli_strict_check_passes_for_an_empty_scope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    user_id = f"ops_{uuid.uuid4()}"
    try:
        assert check_memory_main(["--user-id", user_id, "--strict"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["status"] == "healthy"
        assert report["records_total"] == 0
        assert report["database"]["query_ok"] is True
    finally:
        with SessionLocal() as session:
            session.execute(
                delete(WorkingMemoryItem).where(WorkingMemoryItem.user_id == user_id)
            )
            session.commit()


class StubRetention:
    # Record retention scope and return one completed purge.
    async def purge_expired(self, user_id, *, dry_run):
        assert dry_run is False
        return {"user_id": user_id, "affected_total": 2}


class StubReembedding:
    # Record vector options and return one completed refresh.
    async def reembed(self, user_id, *, dry_run, batch_size):
        return {
            "user_id": user_id,
            "dry_run": dry_run,
            "batch_size": batch_size,
            "updated_total": int(not dry_run),
        }


class StubOperations:
    # Return healthy final state for the maintenance cycle.
    async def inspect(self, user_id):
        return {"status": "healthy", "user_id": user_id}


# Verify one maintenance cycle orchestrates lifecycle work and final inspection.
@pytest.mark.asyncio
async def test_memory_maintenance_cycle_orchestrates_lifecycle_services() -> None:
    service = MemoryMaintenanceService(
        StubRetention(),  # type: ignore[arg-type]
        StubReembedding(),  # type: ignore[arg-type]
        StubOperations(),  # type: ignore[arg-type]
    )
    result = await service.run_cycle(
        "maintenance-user",
        reembed=True,
        batch_size=25,
    )
    assert result == {
        "status": "healthy",
        "user_id": "maintenance-user",
        "retention": {"user_id": "maintenance-user", "affected_total": 2},
        "reembedding": {
            "user_id": "maintenance-user",
            "dry_run": False,
            "batch_size": 25,
            "updated_total": 1,
        },
        "operations": {"status": "healthy", "user_id": "maintenance-user"},
    }
