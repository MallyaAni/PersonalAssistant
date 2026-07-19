import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import SessionLocal
from backend.main import app
from backend.models.memory import MemoryFact, UserProfile


# Delete all test-owned memory for the supplied users.
def _cleanup(*user_ids: str) -> None:
    with SessionLocal() as session:
        session.execute(delete(MemoryFact).where(MemoryFact.user_id.in_(user_ids)))
        session.execute(delete(UserProfile).where(UserProfile.user_id.in_(user_ids)))
        session.commit()


# Build a valid fact request payload with optional overrides.
def _fact_payload(
    *,
    value: str,
    trace_id: uuid.UUID,
    fact_key: str = "home_airport",
    fact_type: str = "preference",
) -> dict[str, str]:
    return {
        "fact_type": fact_type,
        "fact_key": fact_key,
        "value": value,
        "purpose": "personalization",
        "source_trace_id": str(trace_id),
    }


# Verify fact deduplication, correction, ownership, and record deletion.
def test_general_fact_deduplication_correction_and_per_record_deletion() -> None:
    user_id = f"facts_{uuid.uuid4()}"
    other_user = f"facts_{uuid.uuid4()}"
    first_trace = uuid.uuid4()
    correction_trace = uuid.uuid4()

    try:
        with TestClient(app) as client:
            first = client.post(
                f"/api/v1/memory/{user_id}/facts",
                json=_fact_payload(value="JFK", trace_id=first_trace),
            )
            repeated_trace = client.post(
                f"/api/v1/memory/{user_id}/facts",
                json=_fact_payload(value="JFK", trace_id=first_trace),
            )
            duplicate_value = client.post(
                f"/api/v1/memory/{user_id}/facts",
                json=_fact_payload(value="  jfk  ", trace_id=uuid.uuid4()),
            )

            assert first.status_code == 201
            assert first.json()["fact"]["version"] == 1
            assert first.json()["deduplicated"] is False
            assert repeated_trace.status_code == 201
            assert repeated_trace.json()["fact"]["id"] == first.json()["fact"]["id"]
            assert repeated_trace.json()["deduplicated"] is True
            assert duplicate_value.json()["fact"]["id"] == first.json()["fact"]["id"]
            assert duplicate_value.json()["deduplicated"] is True

            corrected = client.put(
                f"/api/v1/memory/{user_id}/facts/{first.json()['fact']['id']}",
                json={
                    "value": "EWR",
                    "source_trace_id": str(correction_trace),
                    "metadata": {"reason": "user correction"},
                },
            )
            assert corrected.status_code == 200
            assert corrected.json()["fact"]["version"] == 2
            assert (
                corrected.json()["fact"]["supersedes_id"] == first.json()["fact"]["id"]
            )
            assert corrected.json()["fact"]["value"] == "EWR"

            conflict = client.post(
                f"/api/v1/memory/{user_id}/facts",
                json=_fact_payload(value="LGA", trace_id=correction_trace),
            )
            assert conflict.status_code == 409

            facts = client.get(f"/api/v1/memory/{user_id}").json()["facts"]
            assert [(fact["value"], fact["approval_state"]) for fact in facts] == [
                ("EWR", "approved"),
                ("JFK", "superseded"),
            ]
            cross_user_delete = client.delete(
                f"/api/v1/memory/{other_user}/facts/{corrected.json()['fact']['id']}"
            )
            assert cross_user_delete.status_code == 404

            deleted_history = client.delete(
                f"/api/v1/memory/{user_id}/facts/{first.json()['fact']['id']}"
            )
            assert deleted_history.status_code == 200
            remaining = client.get(f"/api/v1/memory/{user_id}").json()["facts"]
            assert [fact["value"] for fact in remaining] == ["EWR"]

            deleted_current = client.delete(
                f"/api/v1/memory/{user_id}/facts/{corrected.json()['fact']['id']}"
            )
            assert deleted_current.status_code == 200
            assert client.get(f"/api/v1/memory/{user_id}").json()["facts"] == []

        with SessionLocal() as session:
            assert (
                session.execute(select(MemoryFact).where(MemoryFact.user_id == user_id))
                .scalars()
                .all()
                == []
            )
    finally:
        _cleanup(user_id, other_user)


# Verify response-style facts are versioned and clear their profile projection.
def test_response_style_fact_projection_is_versioned_and_cleared_by_key() -> None:
    user_id = f"facts_{uuid.uuid4()}"

    try:
        with TestClient(app) as client:
            client.put(
                f"/api/v1/memory/{user_id}/profile",
                json={"name": "Projection User", "preferences": {"theme": "light"}},
            )
            concise = client.post(
                f"/api/v1/memory/{user_id}/facts",
                json=_fact_payload(
                    value="concise",
                    trace_id=uuid.uuid4(),
                    fact_key="response_style",
                    fact_type="profile",
                ),
            )
            assert concise.status_code == 201
            snapshot = client.get(f"/api/v1/memory/{user_id}").json()
            assert snapshot["profile"]["preferences"] == {
                "theme": "light",
                "response_style": "concise",
            }

            detailed = client.post(
                f"/api/v1/memory/{user_id}/facts",
                json=_fact_payload(
                    value="detailed",
                    trace_id=uuid.uuid4(),
                    fact_key="response_style",
                    fact_type="profile",
                ),
            )
            assert detailed.json()["fact"]["version"] == 2
            assert (
                detailed.json()["fact"]["supersedes_id"] == concise.json()["fact"]["id"]
            )

            cleared = client.delete(
                f"/api/v1/memory/{user_id}/facts/key/response_style"
            )
            assert cleared.status_code == 200
            assert cleared.json() == {"deleted": 2}
            profile = client.get(f"/api/v1/memory/{user_id}").json()["profile"]
            assert profile["name"] == "Projection User"
            assert profile["preferences"] == {"theme": "light"}
    finally:
        _cleanup(user_id)


# Verify the fact API rejects invalid keys and unbounded text.
def test_general_fact_schema_rejects_unbounded_or_ambiguous_keys() -> None:
    with TestClient(app) as client:
        uppercase_key = client.post(
            "/api/v1/memory/fact_validation/facts",
            json=_fact_payload(
                value="value",
                trace_id=uuid.uuid4(),
                fact_key="Home Airport",
            ),
        )
        extra_field = client.post(
            "/api/v1/memory/fact_validation/facts",
            json={
                **_fact_payload(value="value", trace_id=uuid.uuid4()),
                "approved": True,
            },
        )

    assert uppercase_key.status_code == 422
    assert extra_field.status_code == 422
