"""The discovery profile is a projection of memory, not a second truth.

This project already answers "where does a fact about the user live":
`approve_preferred_name_fact` writes a `MemoryFact` and `user_profiles` is a
projection of it. Discovery grew as a parallel store, and the cost was concrete —
it escaped memory's guarantees until that was fixed. These tests hold the two
directions that keep one truth.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal
from backend.discovery.fact_recorder import MemoryFactRecorder
from backend.discovery.projection import (
    INTEREST_KEY_PREFIX,
    LOCALITY_KEY,
    DiscoveryProjection,
    interest_fact,
    is_interest_key,
    locality_fact,
)
from backend.discovery.repository import DiscoveryProfileRepository
from backend.discovery.service import DiscoveryProfileService
from backend.discovery.types import MAX_INTERESTS_PER_USER
from backend.main import app
from backend.memory.errors import MemoryConflictError
from backend.memory.repository import MemoryRepository
from backend.models.discovery import DiscoveryInterest, DiscoveryLocality
from backend.models.memory import MemoryFact


# Remove both memory and projected discovery rows for one test user.
async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await MemoryRepository(session).delete_all_user_memory(user_id)


# Keep projected interest keys stable, namespaced, and distinct from other facts.
def test_keys_are_namespaced_so_an_unrelated_fact_is_never_mistaken():
    assert is_interest_key(interest_fact("hiking").fact_key)
    assert not is_interest_key("preferred_name")
    assert not is_interest_key(LOCALITY_KEY)
    assert interest_fact("Live  Jazz").fact_key == interest_fact("live jazz").fact_key
    assert interest_fact("Live  Jazz").fact_key.startswith(INTEREST_KEY_PREFIX)


# Preserve an optional region in the canonical locality fact value.
def test_a_locality_fact_carries_the_region():
    assert locality_fact("Arlington", "Virginia, US").value == (
        "Arlington, Virginia, US"
    )
    assert locality_fact("Arlington", None).value == "Arlington"


# Verify a direct profile edit records approved memory with provenance.
@pytest.mark.asyncio
async def test_editing_the_profile_records_the_fact_in_memory():
    """Editing in the panel is something the assistant then knows."""
    user_id = f"proj_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(
                DiscoveryProfileRepository(session), MemoryFactRecorder(session)
            )
            await service.add_locality(
                user_id, "Arlington", "Virginia, US", is_primary=True
            )
            await service.add_interest(user_id, "hiking")

            rows = (
                (
                    await session.execute(
                        select(MemoryFact).where(MemoryFact.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )

        keys = {row.fact_key: row.value for row in rows}
        assert keys[LOCALITY_KEY] == "Arlington, Virginia, US"
        assert keys[interest_fact("hiking").fact_key] == "hiking"
        # Provenance distinguishes a typed edit from an approved inference.
        assert all(row.approval_state == "approved" for row in rows)
    finally:
        await _cleanup(user_id)


# Verify approved chat facts configure the typed Scout profile projection.
@pytest.mark.asyncio
async def test_approving_a_fact_configures_the_agent():
    """Saying where you live in chat should configure the agent."""
    user_id = f"proj_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repository = DiscoveryProfileRepository(session)
            projection = DiscoveryProjection(session)

            applied = await projection.apply_fact(
                user_id, LOCALITY_KEY, "Arlington, Virginia"
            )
            await projection.apply_fact(
                user_id, interest_fact("hiking").fact_key, "hiking"
            )

            profile = await repository.get_profile(user_id)

        assert applied is True
        assert profile.primary_locality is not None
        assert profile.primary_locality.label == "Arlington"
        assert profile.primary_locality.region == "Virginia"
        assert [i.label for i in profile.interests] == ["hiking"]
    finally:
        await _cleanup(user_id)


# Ignore memory fact keys that belong to another projection.
@pytest.mark.asyncio
async def test_an_unrelated_fact_is_ignored_rather_than_rejected():
    # This is called for every approval, so it must not care about keys it does
    # not own.
    user_id = f"proj_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repository = DiscoveryProfileRepository(session)
            projection = DiscoveryProjection(session)

            assert (
                await projection.apply_fact(user_id, "preferred_name", "Ani") is False
            )
            profile = await repository.get_profile(user_id)

        assert profile.interests == ()
        assert profile.localities == ()
    finally:
        await _cleanup(user_id)


# Remove an interest projection when the owning memory fact is forgotten.
@pytest.mark.asyncio
async def test_forgetting_an_interest_fact_removes_the_projection():
    user_id = f"proj_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repository = DiscoveryProfileRepository(session)
            projection = DiscoveryProjection(session)
            await projection.apply_fact(
                user_id, interest_fact("hiking").fact_key, "hiking"
            )

            revoked = await projection.revoke_fact(
                user_id, interest_fact("hiking").fact_key
            )
            profile = await repository.get_profile(user_id)

        assert revoked is True
        assert profile.interests == ()
    finally:
        await _cleanup(user_id)


# Reject a profile edit when its owning memory fact cannot be recorded.
@pytest.mark.asyncio
async def test_a_memory_failure_does_not_create_an_unowned_profile_value():
    class _Broken:
        # Simulate an unavailable memory recorder.
        async def record(self, user_id: str, fact: object) -> None:
            raise RuntimeError("memory unavailable")

    user_id = f"proj_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(
                DiscoveryProfileRepository(session), _Broken()
            )
            with pytest.raises(RuntimeError, match="memory unavailable"):
                await service.add_interest(user_id, "hiking")
            profile = await service.get_profile(user_id)

        assert profile.interests == ()
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoveryInterest).where(DiscoveryInterest.user_id == user_id)
            )
            await session.execute(
                delete(DiscoveryLocality).where(DiscoveryLocality.user_id == user_id)
            )
            await session.commit()


# Verify the public chat-approval endpoints create both facts and Scout profile rows.
def test_chat_approval_endpoints_project_locality_and_interest():
    user_id = f"chat_proj_{uuid.uuid4().hex[:12]}"
    try:
        with TestClient(app) as client:
            locality = client.post(
                f"/api/v1/memory/{user_id}/profile/discovery-locality",
                json={
                    "label": "Arlington",
                    "region": "Virginia",
                    "source_conversation_id": "11111111-1111-4111-8111-111111111111",
                    "source_trace_id": "22222222-2222-4222-8222-222222222222",
                },
            )
            interest = client.post(
                f"/api/v1/memory/{user_id}/profile/discovery-interest",
                json={
                    "label": "hiking",
                    "source_conversation_id": "11111111-1111-4111-8111-111111111111",
                    "source_trace_id": "33333333-3333-4333-8333-333333333333",
                },
            )
            profile = client.get(f"/api/v1/discovery/{user_id}")
            memory = client.get(f"/api/v1/memory/{user_id}")

        assert locality.status_code == 201
        assert interest.status_code == 201
        assert profile.status_code == 200
        assert profile.json()["localities"][0]["label"] == "Arlington"
        assert profile.json()["localities"][0]["region"] == "Virginia"
        assert profile.json()["interests"][0]["label"] == "hiking"
        assert {fact["fact_key"] for fact in memory.json()["facts"]} == {
            LOCALITY_KEY,
            interest_fact("hiking").fact_key,
        }
    finally:
        with TestClient(app) as client:
            client.delete(f"/api/v1/memory/{user_id}")


# Approve a semantic interest list atomically and keep its projection user-scoped.
def test_chat_interest_batch_projects_only_into_its_owner() -> None:
    owner = f"batch_owner_{uuid.uuid4().hex[:10]}"
    other = f"batch_other_{uuid.uuid4().hex[:10]}"
    labels = ["basketball", "soccer", "baseball", "hiking"]
    try:
        with TestClient(app) as client:
            approved = client.post(
                f"/api/v1/memory/{owner}/profile/discovery-interests",
                json={
                    "labels": labels,
                    "source_conversation_id": ("11111111-1111-4111-8111-111111111111"),
                    "source_trace_id": "44444444-4444-4444-8444-444444444444",
                },
            )
            owner_profile = client.get(f"/api/v1/discovery/{owner}")
            other_profile = client.get(f"/api/v1/discovery/{other}")
            owner_memory = client.get(f"/api/v1/memory/{owner}")

        assert approved.status_code == 201
        assert {item["label"] for item in owner_profile.json()["interests"]} == set(
            labels
        )
        assert other_profile.json()["interests"] == []
        assert {fact["value"] for fact in owner_memory.json()["facts"]} == set(labels)
    finally:
        with TestClient(app) as client:
            client.delete(f"/api/v1/memory/{owner}")
            client.delete(f"/api/v1/memory/{other}")


# Prove a capacity failure rolls back every fact and projection in the batch.
@pytest.mark.asyncio
async def test_chat_interest_batch_is_all_or_nothing_at_profile_capacity() -> None:
    user_id = f"batch_limit_{uuid.uuid4().hex[:10]}"
    try:
        async with AsyncSessionLocal() as session:
            profile = DiscoveryProfileRepository(session)
            for index in range(MAX_INTERESTS_PER_USER - 1):
                await profile.upsert_interest(user_id, f"seed {index}", 2, "manual")

            repository = MemoryRepository(session)
            conversation_id = "11111111-1111-4111-8111-111111111111"
            trace_id = "55555555-5555-4555-8555-555555555555"
            items = []
            for label in ("would fit alone", "would exceed capacity"):
                fact = interest_fact(label)
                items.append(
                    {
                        "user_id": user_id,
                        "fact_type": fact.fact_type,
                        "fact_key": fact.fact_key,
                        "value": fact.value,
                        "purpose": fact.purpose,
                        "source_conversation_id": conversation_id,
                        "source_trace_id": trace_id,
                        "expires_at": None,
                        "extra_data": {"source": "test"},
                    }
                )

            with pytest.raises(MemoryConflictError):
                await repository.approve_facts(items)

            stored = await profile.list_interests(user_id)
            facts = list(
                (
                    await session.execute(
                        select(MemoryFact).where(MemoryFact.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(stored) == MAX_INTERESTS_PER_USER - 1
            assert {interest.label for interest in stored}.isdisjoint(
                {"would fit alone", "would exceed capacity"}
            )
            assert facts == []
    finally:
        await _cleanup(user_id)


# Verify removing a typed profile value also clears its approved memory fact.
def test_profile_deletion_forgets_the_owning_fact():
    user_id = f"profile_forget_{uuid.uuid4().hex[:12]}"
    try:
        with TestClient(app) as client:
            created = client.put(
                f"/api/v1/discovery/{user_id}/interests",
                json={"label": "hiking", "strength": 2},
            )
            assert created.status_code == 200
            before = client.get(f"/api/v1/memory/{user_id}").json()
            assert [fact["fact_key"] for fact in before["facts"]] == [
                interest_fact("hiking").fact_key
            ]

            deleted = client.delete(
                f"/api/v1/discovery/{user_id}/interests/{created.json()['id']}"
            )
            after = client.get(f"/api/v1/memory/{user_id}").json()

        assert deleted.status_code == 204
        assert after["facts"] == []
    finally:
        with TestClient(app) as client:
            client.delete(f"/api/v1/memory/{user_id}")
