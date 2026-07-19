import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.cli.purge_memory import main as purge_memory_main
from backend.database.session import SessionLocal
from backend.main import app
from backend.models.agent_memory import (
    MemoryEntity,
    MemoryEntityRelation,
    ProcedureMemory,
    SemanticCacheEntry,
    WorkingMemoryItem,
)
from backend.models.memory import (
    EpisodicMemory,
    MemoryFact,
    SemanticMemory,
    UserProfile,
)
from backend.models.tool_memory import ToolPreference


# Build the stable embedding used by retention fixtures.
def _vector() -> list[float]:
    return [1.0, *([0.0] * 767)]


# Delete all retention fixtures for the supplied users.
def _cleanup(*user_ids: str) -> None:
    with SessionLocal() as session:
        for model in (
            MemoryEntityRelation,
            MemoryEntity,
            ProcedureMemory,
            SemanticCacheEntry,
            WorkingMemoryItem,
            MemoryFact,
            EpisodicMemory,
            SemanticMemory,
            ToolPreference,
            UserProfile,
        ):
            session.execute(delete(model).where(model.user_id.in_(user_ids)))
        session.commit()


# Seed expired and active records across every retention-managed store.
def _seed_retention_rows(user_id: str, other_user: str) -> dict[str, uuid.UUID]:
    now = datetime.now(UTC)
    past = now - timedelta(hours=1)
    future = now + timedelta(hours=1)
    conversation_id = uuid.uuid4()
    trace_ids = iter(uuid.uuid4() for _ in range(20))
    expired_entity = MemoryEntity(
        user_id=user_id,
        entity_type="person",
        canonical_name="Expired Person",
        normalized_name="expired person",
        attributes={},
        approval_state="approved",
        source_trace_id=next(trace_ids),
        embedding=_vector(),
        embedding_model="retention-test",
        embedding_version="1",
        embedding_dimension=768,
        expires_at=past,
    )
    active_entity = MemoryEntity(
        user_id=user_id,
        entity_type="project",
        canonical_name="Active Project",
        normalized_name="active project",
        attributes={},
        approval_state="approved",
        source_trace_id=next(trace_ids),
        embedding=_vector(),
        embedding_model="retention-test",
        embedding_version="1",
        embedding_dimension=768,
        expires_at=future,
    )
    rows = [
        UserProfile(user_id=user_id, name="Expired Name", preferences={}),
        SemanticCacheEntry(
            user_id=user_id,
            cache_key="expired-cache",
            query="expired query",
            response="expired response",
            embedding=_vector(),
            model="retention-test",
            embedding_model="retention-test",
            embedding_version="1",
            embedding_dimension=768,
            expires_at=past,
        ),
        SemanticCacheEntry(
            user_id=user_id,
            cache_key="active-cache",
            query="active query",
            response="active response",
            embedding=_vector(),
            model="retention-test",
            embedding_model="retention-test",
            embedding_version="1",
            embedding_dimension=768,
            expires_at=future,
        ),
        WorkingMemoryItem(
            user_id=user_id,
            conversation_id=conversation_id,
            memory_key="expired",
            value="expired",
            purpose="retention_test",
            expires_at=past,
        ),
        WorkingMemoryItem(
            user_id=user_id,
            conversation_id=conversation_id,
            memory_key="active",
            value="active",
            purpose="retention_test",
            expires_at=future,
        ),
        ProcedureMemory(
            user_id=user_id,
            name="Expired Procedure",
            description="expired",
            steps=[{"order": 1, "instruction": "expire"}],
            approval_state="approved",
            version=1,
            source_trace_id=next(trace_ids),
            embedding=_vector(),
            embedding_model="retention-test",
            embedding_version="1",
            embedding_dimension=768,
            active=True,
            expires_at=past,
            extra_data={},
        ),
        ProcedureMemory(
            user_id=user_id,
            name="Active Procedure",
            description="active",
            steps=[{"order": 1, "instruction": "keep"}],
            approval_state="approved",
            version=1,
            source_trace_id=next(trace_ids),
            embedding=_vector(),
            embedding_model="retention-test",
            embedding_version="1",
            embedding_dimension=768,
            active=True,
            expires_at=future,
            extra_data={},
        ),
        expired_entity,
        active_entity,
        MemoryFact(
            user_id=user_id,
            fact_type="identity",
            fact_key="preferred_name",
            value="Expired Name",
            normalized_value="expired name",
            approval_state="approved",
            confidence=1.0,
            purpose="user_explicit",
            source_trace_id=next(trace_ids),
            version=1,
            expires_at=past,
            extra_data={},
        ),
        EpisodicMemory(
            user_id=user_id,
            content="expired episode",
            purpose="retention_test",
            expires_at=past,
            extra_data={},
        ),
        EpisodicMemory(
            user_id=user_id,
            content="active episode",
            purpose="retention_test",
            expires_at=future,
            extra_data={},
        ),
        SemanticMemory(
            user_id=user_id,
            content="expired semantic",
            embedding=_vector(),
            purpose="retention_test",
            embedding_model="retention-test",
            embedding_version="1",
            embedding_dimension=768,
            expires_at=past,
            extra_data={},
        ),
        SemanticMemory(
            user_id=user_id,
            content="active semantic",
            embedding=_vector(),
            purpose="retention_test",
            embedding_model="retention-test",
            embedding_version="1",
            embedding_dimension=768,
            expires_at=future,
            extra_data={},
        ),
        ToolPreference(
            user_id=user_id,
            server_id="retention-server",
            tool_name="retention-tool",
            preference_key="expired",
            value="expired",
            purpose="retention_test",
            approval_state="approved",
            source_trace_id=next(trace_ids),
            expires_at=past,
        ),
        ToolPreference(
            user_id=user_id,
            server_id="retention-server",
            tool_name="retention-tool",
            preference_key="active",
            value="active",
            purpose="retention_test",
            approval_state="approved",
            source_trace_id=next(trace_ids),
            expires_at=future,
        ),
        WorkingMemoryItem(
            user_id=other_user,
            conversation_id=uuid.uuid4(),
            memory_key="expired-other-user",
            value="must survive scoped purge",
            purpose="retention_test",
            expires_at=past,
        ),
    ]
    with SessionLocal() as session:
        session.add_all(rows)
        session.flush()
        relation = MemoryEntityRelation(
            user_id=user_id,
            source_entity_id=expired_entity.id,
            target_entity_id=active_entity.id,
            relation_type="mentions",
            attributes={},
            approval_state="approved",
            source_trace_id=next(trace_ids),
        )
        session.add(relation)
        session.commit()
        return {
            "expired_cache": rows[1].id,
            "active_cache": rows[2].id,
            "other_working": rows[-1].id,
            "relation": relation.id,
        }


# Verify retention preview and apply modes are scoped and atomic.
def test_retention_api_dry_run_and_apply_are_scoped_and_atomic() -> None:
    user_id = f"retention_{uuid.uuid4()}"
    other_user = f"retention_{uuid.uuid4()}"
    ids = _seed_retention_rows(user_id, other_user)

    try:
        with TestClient(app) as client:
            dry_run = client.post(f"/api/v1/memory/{user_id}/agent/retention/purge")
            assert dry_run.status_code == 200
            assert dry_run.json()["dry_run"] is True
            assert dry_run.json()["counts"] == {
                "semantic_cache": 1,
                "working": 1,
                "procedures": 1,
                "entity_relations": 1,
                "entities": 1,
                "facts": 1,
                "episodic": 1,
                "semantic": 1,
                "tool_preferences": 1,
                "profiles_cleared": 1,
            }
            assert dry_run.json()["affected_total"] == 10

            with SessionLocal() as session:
                assert session.get(SemanticCacheEntry, ids["expired_cache"])
                assert session.get(MemoryEntityRelation, ids["relation"])
                profile = session.query(UserProfile).filter_by(user_id=user_id).one()
                assert profile.name == "Expired Name"

            applied = client.post(
                f"/api/v1/memory/{user_id}/agent/retention/purge",
                params={"dry_run": "false"},
            )
            assert applied.status_code == 200
            assert applied.json()["dry_run"] is False
            assert applied.json()["affected_total"] == 10

            with SessionLocal() as session:
                assert session.get(SemanticCacheEntry, ids["expired_cache"]) is None
                assert session.get(MemoryEntityRelation, ids["relation"]) is None
                assert session.get(SemanticCacheEntry, ids["active_cache"])
                assert session.get(WorkingMemoryItem, ids["other_working"])
                profile = session.query(UserProfile).filter_by(user_id=user_id).one()
                assert profile.name is None

            repeated = client.post(
                f"/api/v1/memory/{user_id}/agent/retention/purge",
                params={"dry_run": "false"},
            )
            assert repeated.status_code == 200
            assert repeated.json()["affected_total"] == 0
    finally:
        _cleanup(user_id, other_user)


# Verify the retention CLI defaults safely and requires write scope.
def test_retention_cli_defaults_to_dry_run_and_requires_explicit_apply_scope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    user_id = f"retention_{uuid.uuid4()}"
    row_id = uuid.uuid4()
    with SessionLocal() as session:
        session.add(
            WorkingMemoryItem(
                id=row_id,
                user_id=user_id,
                conversation_id=uuid.uuid4(),
                memory_key="cli-expired",
                value="expired",
                purpose="retention_test",
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        session.commit()

    try:
        assert purge_memory_main(["--user-id", user_id]) == 0
        dry_run = json.loads(capsys.readouterr().out)
        assert dry_run["dry_run"] is True
        assert dry_run["counts"]["working"] == 1
        with SessionLocal() as session:
            assert session.get(WorkingMemoryItem, row_id)

        assert purge_memory_main(["--user-id", user_id, "--apply"]) == 0
        applied = json.loads(capsys.readouterr().out)
        assert applied["dry_run"] is False
        assert applied["counts"]["working"] == 1
        with SessionLocal() as session:
            assert session.get(WorkingMemoryItem, row_id) is None

        with pytest.raises(SystemExit) as error:
            purge_memory_main(["--apply"])
        assert error.value.code == 2
    finally:
        _cleanup(user_id)
