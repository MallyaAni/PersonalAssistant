import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.core.dependencies import get_embedding_provider
from backend.database.session import SessionLocal
from backend.embeddings.base import EmbeddingProvider
from backend.main import app
from backend.models.agent_memory import ProcedureMemory
from backend.models.memory import MemoryFact


class ConcurrentEmbeddingProvider(EmbeddingProvider):
    model = "concurrency-test"

    # Return one stable embedding for stored text.
    def embed_text(self, text: str) -> list[float]:
        return [1.0, *([0.0] * 767)]

    # Return one stable embedding for queries.
    def embed_query(self, query: str) -> list[float]:
        return self.embed_text(query)


# Delete all test-owned facts and procedures for a user.
def _cleanup(user_id: str) -> None:
    with SessionLocal() as session:
        session.execute(delete(MemoryFact).where(MemoryFact.user_id == user_id))
        session.execute(
            delete(ProcedureMemory).where(ProcedureMemory.user_id == user_id)
        )
        session.commit()


# Verify concurrent duplicate fact approvals produce one approved version.
def test_concurrent_equal_fact_approvals_collapse_to_one_version() -> None:
    user_id = f"conc_{uuid.uuid4()}"
    worker_count = 12
    barrier = threading.Barrier(worker_count)

    # Submit one concurrent fact approval and return its result details.
    def approve(index: int) -> tuple[int, str, bool]:
        barrier.wait(timeout=10)
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/memory/{user_id}/facts",
                json={
                    "fact_type": "preference",
                    "fact_key": "home_airport",
                    "value": "JFK",
                    "purpose": "concurrency_test",
                    "source_trace_id": str(uuid.uuid5(uuid.NAMESPACE_OID, str(index))),
                },
            )
            return (
                response.status_code,
                response.json()["fact"]["id"],
                response.json()["deduplicated"],
            )

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(approve, range(worker_count)))

        assert {status for status, _, _ in results} == {201}
        assert len({fact_id for _, fact_id, _ in results}) == 1
        assert sum(not deduplicated for _, _, deduplicated in results) == 1
        with SessionLocal() as session:
            facts = list(
                session.execute(
                    select(MemoryFact).where(MemoryFact.user_id == user_id)
                ).scalars()
            )
            assert len(facts) == 1
            assert facts[0].version == 1
            assert facts[0].approval_state == "approved"
    finally:
        _cleanup(user_id)


# Verify concurrent procedure updates receive distinct version numbers.
def test_concurrent_procedure_corrections_receive_unique_versions() -> None:
    user_id = f"conc_{uuid.uuid4()}"
    worker_count = 8
    barrier = threading.Barrier(worker_count)
    app.dependency_overrides[get_embedding_provider] = (
        lambda: ConcurrentEmbeddingProvider()
    )

    # Submit one concurrent procedure approval and return its version.
    def approve(index: int) -> tuple[int, int]:
        barrier.wait(timeout=10)
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/memory/{user_id}/agent/procedures",
                json={
                    "name": "Concurrent procedure",
                    "description": f"Concurrent description {index}",
                    "steps": [{"order": 1, "instruction": f"Step {index}"}],
                    "source_trace_id": str(uuid.uuid4()),
                },
            )
            return response.status_code, response.json()["version"]

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(approve, range(worker_count)))

        assert {status for status, _ in results} == {201}
        assert sorted(version for _, version in results) == list(
            range(1, worker_count + 1)
        )
        with SessionLocal() as session:
            procedures = list(
                session.execute(
                    select(ProcedureMemory)
                    .where(ProcedureMemory.user_id == user_id)
                    .order_by(ProcedureMemory.version)
                ).scalars()
            )
            assert [item.version for item in procedures] == list(
                range(1, worker_count + 1)
            )
            assert sum(item.active for item in procedures) == 1
            assert procedures[-1].active is True
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
        _cleanup(user_id)
