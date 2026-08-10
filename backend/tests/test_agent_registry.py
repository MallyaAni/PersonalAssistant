"""The agent registry reports live state, not a stored description.

The value of this surface is that it cannot lie: every field is derived from the
tables each agent writes. These tests change the underlying rows and assert the
reported status follows.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.agents.registry import AgentRegistry
from backend.core.auth import issue_user_token
from backend.database.session import AsyncSessionLocal
from backend.discovery.repository import DiscoveryProfileRepository
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.schedule import Cadence
from backend.discovery.sources_repository import DiscoverySourceRepository
from backend.main import app
from backend.models.discovery import DiscoveryInterest
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule
from backend.models.discovery_source import DiscoverySource


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        schedules = (
            (
                await session.execute(
                    select(DiscoverySchedule).where(
                        DiscoverySchedule.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        for schedule in schedules:
            await session.execute(
                delete(DiscoveryRun).where(DiscoveryRun.schedule_id == schedule.id)
            )
            await session.delete(schedule)
        await session.execute(
            delete(DiscoverySource).where(DiscoverySource.user_id == user_id)
        )
        await session.execute(
            delete(DiscoveryInterest).where(DiscoveryInterest.user_id == user_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_a_new_user_sees_discovery_as_needing_setup():
    user_id = f"reg_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            agents = await AgentRegistry(session).describe_all(user_id)

        scout = next(agent for agent in agents if agent.id == "discovery")
        assert scout.status == "needs_setup"
        # The panel must name what is missing rather than saying "idle".
        assert "interest" in scout.detail
        assert scout.last_active_at is None
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_a_feed_is_only_demanded_when_search_cannot_enumerate(monkeypatch):
    # Search finds happenings that publish no feed at all, so with it available
    # an interest and a place are enough. Demanding a feed anyway would send the
    # user hunting for .ics URLs they do not need.
    user_id = f"reg_{uuid.uuid4().hex[:12]}"
    # `_can_search` moved with Scout's card when each agent got its own
    # folder; the registry no longer knows anything about any one agent.
    import backend.agents.scout.card as scout_card

    try:
        async with AsyncSessionLocal() as session:
            await DiscoveryProfileRepository(session).upsert_interest(
                user_id, "hiking", 3, "user_explicit"
            )

            monkeypatch.setattr(scout_card, "_can_search", lambda: True)
            with_search = await AgentRegistry(session).describe_all(user_id)

            monkeypatch.setattr(scout_card, "_can_search", lambda: False)
            without_search = await AgentRegistry(session).describe_all(user_id)

        searching = next(a for a in with_search if a.id == "discovery")
        blind = next(a for a in without_search if a.id == "discovery")

        assert searching.status != "needs_setup"
        assert blind.status == "needs_setup"
        assert "feed" in blind.detail
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_a_configured_schedule_reports_when_the_next_sweep_is():
    user_id = f"reg_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            await DiscoveryProfileRepository(session).upsert_interest(
                user_id, "jazz", 3, "user_explicit"
            )
            await DiscoverySourceRepository(session).upsert_source(
                user_id, "ics", "https://example.org/feed.ics"
            )
            await DiscoveryRunRepository(session).upsert_schedule(
                user_id,
                Cadence(
                    cadence="weekly", hour=9, weekday=4, timezone="America/New_York"
                ),
            )

            agents = await AgentRegistry(session).describe_all(user_id)

        scout = next(agent for agent in agents if agent.id == "discovery")
        assert scout.status == "scheduled"
        assert "Next sweep in" in scout.detail
        facts = {fact.label: fact.value for fact in scout.facts}
        assert facts["Feeds"] == "1"
        assert facts["Interests"] == "1"
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_a_running_sweep_reports_as_working():
    user_id = f"reg_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            await DiscoveryProfileRepository(session).upsert_interest(
                user_id, "jazz", 3, "user_explicit"
            )
            await DiscoverySourceRepository(session).upsert_source(
                user_id, "ics", "https://example.org/feed.ics"
            )
            runs = DiscoveryRunRepository(session)
            await runs.upsert_schedule(
                user_id,
                Cadence(
                    cadence="daily", hour=9, weekday=0, timezone="America/New_York"
                ),
            )
            schedule = (
                (
                    await session.execute(
                        select(DiscoverySchedule).where(
                            DiscoverySchedule.user_id == user_id
                        )
                    )
                )
                .scalars()
                .one()
            )
            session.add(
                DiscoveryRun(
                    schedule_id=schedule.id,
                    user_id=user_id,
                    status="running",
                    scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
                )
            )
            await session.commit()

            agents = await AgentRegistry(session).describe_all(user_id)

        scout = next(agent for agent in agents if agent.id == "discovery")
        assert scout.status == "working"
        assert "Sweeping" in scout.detail
    finally:
        await _cleanup(user_id)


def test_the_api_returns_every_agent_for_a_user():
    user_id = f"reg_{uuid.uuid4().hex[:12]}"
    # The deployment requires authentication and pytest reads the same .env, so
    # an unauthenticated request 401s before reaching the route under test.
    with TestClient(
        app, headers={"Authorization": f"Bearer {issue_user_token(user_id)}"}
    ) as client:
        response = client.get(f"/api/v1/agents/{user_id}")

        assert response.status_code == 200
        payload = response.json()
        identifiers = {agent["id"] for agent in payload["agents"]}
        assert identifiers == {"discovery", "presentation"}
        for agent in payload["agents"]:
            # A card with no name or no explanation is not usable.
            assert agent["name"]
            assert agent["role"]
            assert agent["detail"]
            assert agent["trigger"]
