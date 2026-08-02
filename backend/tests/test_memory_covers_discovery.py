"""Forgetting a user must actually forget them.

Ambient discovery grew outside the memory subsystem, so it silently escaped
memory's guarantees: a full wipe once left behind where the user lives, what they
like, everything they had been shown, and other people's phone numbers. These
tests assert the tables are covered, so the next subsystem added outside memory
fails here rather than in someone's data.
"""

import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal
from backend.discovery.familiarity import FamiliarItemRepository
from backend.discovery.repository import DiscoveryProfileRepository
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.schedule import Cadence
from backend.discovery.sources_repository import DiscoverySourceRepository
from backend.discovery.subscribers import SubscriberRepository
from backend.main import app
from backend.memory.repository import MemoryRepository
from backend.models.discovery import DiscoveryInterest, DiscoveryLocality
from backend.models.discovery_familiar import DiscoveryFamiliarItem
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule
from backend.models.discovery_source import DiscoverySeenItem, DiscoverySource
from backend.models.discovery_subscriber import DiscoverySubscriber

_DISCOVERY_MODELS = (
    DiscoveryInterest,
    DiscoveryLocality,
    DiscoverySource,
    DiscoverySeenItem,
    DiscoverySubscriber,
    DiscoveryFamiliarItem,
    DiscoverySchedule,
    DiscoveryRun,
)


# Seed one owned row in every discovery table covered by export and deletion.
async def _seed_everything(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        profile = DiscoveryProfileRepository(session)
        await profile.upsert_interest(user_id, "hiking", 3, "user_explicit")
        await profile.upsert_locality(
            user_id, "Arlington", "Virginia, US", 25, "America/New_York", True
        )
        await DiscoverySourceRepository(session).upsert_source(
            user_id, "ics", "https://example.org/feed.ics"
        )
        await SubscriberRepository(session).enroll(
            user_id, "imessage", "+15550100", consented=True
        )
        await FamiliarItemRepository(session).remember_known(
            user_id, "Arlington", "Four Mile Run Trail", None
        )
        runs = DiscoveryRunRepository(session)
        await runs.upsert_schedule(
            user_id,
            Cadence(cadence="weekly", hour=9, weekday=4, timezone="America/New_York"),
        )
        schedule = await session.scalar(
            select(DiscoverySchedule).where(DiscoverySchedule.user_id == user_id)
        )
        assert schedule is not None
        session.add(
            DiscoveryRun(
                schedule_id=schedule.id,
                user_id=user_id,
                status="queued",
                scheduled_for=datetime.now(UTC),
            )
        )
        session.add(
            DiscoverySeenItem(
                user_id=user_id,
                item_digest="a" * 64,
                source_id="review-source",
                title="A private discovery",
            )
        )
        await session.commit()


# Count every discovery row still owned by one user.
async def _count_all(user_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with AsyncSessionLocal() as session:
        for model in _DISCOVERY_MODELS:
            value = await session.scalar(
                select(func.count(model.id)).where(model.user_id == user_id)
            )
            counts[model.__tablename__] = int(value or 0)
    return counts


# Verify a full repository wipe removes every owned discovery row.
@pytest.mark.asyncio
async def test_forgetting_a_user_removes_their_discovery_data():
    """The privacy hole this exists to prevent."""
    user_id = f"del_{uuid.uuid4().hex[:12]}"
    await _seed_everything(user_id)

    before = await _count_all(user_id)
    # Everything seeded should be present, or the test is not proving anything.
    assert before["discovery_interests"] == 1
    assert before["discovery_localities"] == 1
    assert before["discovery_sources"] == 1
    assert before["discovery_seen_items"] == 1
    assert before["discovery_subscribers"] == 1
    assert before["discovery_familiar_items"] == 1
    assert before["discovery_schedules"] == 1
    assert before["discovery_runs"] == 1

    async with AsyncSessionLocal() as session:
        await MemoryRepository(session).delete_all_user_memory(user_id)

    after = await _count_all(user_id)
    remaining = {name: count for name, count in after.items() if count}
    assert remaining == {}, f"a full wipe left data behind: {remaining}"


# Verify one user's wipe cannot remove another user's discovery rows.
@pytest.mark.asyncio
async def test_a_wipe_does_not_reach_another_user():
    owner = f"del_{uuid.uuid4().hex[:12]}"
    other = f"del_{uuid.uuid4().hex[:12]}"
    await _seed_everything(owner)
    await _seed_everything(other)
    try:
        async with AsyncSessionLocal() as session:
            await MemoryRepository(session).delete_all_user_memory(owner)

        assert not any((await _count_all(owner)).values())
        # Someone else asking to be forgotten must not forget you.
        assert (await _count_all(other))["discovery_interests"] == 1
    finally:
        async with AsyncSessionLocal() as session:
            await MemoryRepository(session).delete_all_user_memory(other)


# Verify wipe results name every discovery category they removed.
@pytest.mark.asyncio
async def test_the_wipe_reports_what_it_removed():
    user_id = f"del_{uuid.uuid4().hex[:12]}"
    await _seed_everything(user_id)

    async with AsyncSessionLocal() as session:
        counts = await MemoryRepository(session).delete_all_user_memory(user_id)

    # Named in the result, so an operator can see discovery was covered rather
    # than assuming it.
    for key in (
        "discovery_interests",
        "discovery_localities",
        "discovery_sources",
        "discovery_seen",
        "discovery_subscribers",
        "discovery_familiar",
        "discovery_schedules",
        "discovery_runs",
        "discovery_localities",
    ):
        assert key in counts


# Exercise the public export and forget-me APIs over every discovery table.
@pytest.mark.asyncio
async def test_export_and_delete_api_cover_every_discovery_table():
    user_id = f"api_del_{uuid.uuid4().hex[:12]}"
    await _seed_everything(user_id)
    try:
        with TestClient(app) as client:
            exported = client.get(f"/api/v1/memory/{user_id}/export")
            assert exported.status_code == 200
            agent_memory = exported.json()["agent_memory"]
            for key in (
                "discovery_interests",
                "discovery_localities",
                "discovery_sources",
                "discovery_seen",
                "discovery_subscribers",
                "discovery_familiar",
                "discovery_schedules",
                "discovery_runs",
            ):
                assert len(agent_memory[key]) == 1

            deleted = client.delete(f"/api/v1/memory/{user_id}")
            assert deleted.status_code == 200
            counts = deleted.json()["deleted"]
            for key in (
                "discovery_interests",
                "discovery_localities",
                "discovery_sources",
                "discovery_seen",
                "discovery_subscribers",
                "discovery_familiar",
                "discovery_schedules",
                "discovery_runs",
            ):
                assert counts[key] == 1

        assert not any((await _count_all(user_id)).values())
    finally:
        async with AsyncSessionLocal() as session:
            await MemoryRepository(session).delete_all_user_memory(user_id)
