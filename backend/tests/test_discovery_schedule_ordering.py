"""A time cannot be set before the place it would be in.

The zone used to come from the request, which meant the browser's. An account
living in Canggu, Bali held a schedule reading 11:15 America/New_York, which
fires at 23:15 where they are. Nothing in the product ever said so, because a
stored zone looks equally plausible whichever one it is.
"""

import os
import uuid

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.database.session import AsyncSessionLocal
from backend.main import app
from backend.models.discovery import DiscoveryLocality
from backend.models.discovery_run import DiscoverySchedule


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DiscoverySchedule).where(DiscoverySchedule.user_id == user_id)
        )
        await session.execute(
            delete(DiscoveryLocality).where(DiscoveryLocality.user_id == user_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_a_schedule_is_refused_until_a_place_exists():
    user_id = f"sch_{uuid.uuid4().hex[:12]}"
    try:
        with TestClient(app) as client:
            response = client.put(
                f"/api/v1/discovery/{user_id}/schedule",
                json={"cadence": "daily", "hour": 9, "minute": 0},
            )

        assert response.status_code == 409, response.text
        # The message has to say what to do, not only that something is wrong.
        assert "before setting a time" in response.json()["detail"]
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_the_schedule_takes_its_zone_from_the_place_not_the_caller():
    user_id = f"sch_{uuid.uuid4().hex[:12]}"
    try:
        with TestClient(app) as client:
            client.put(
                f"/api/v1/discovery/{user_id}/localities",
                json={
                    "label": "Canggu",
                    "region": "Bali",
                    "timezone": "Asia/Makassar",
                    "is_primary": True,
                },
            )
            response = client.put(
                f"/api/v1/discovery/{user_id}/schedule",
                json={
                    "cadence": "daily",
                    "hour": 11,
                    "minute": 15,
                    "timezone": "America/New_York",
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["timezone"] == "Asia/Makassar", response.json()
    finally:
        await _cleanup(user_id)
