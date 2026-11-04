"""Resuming a one-time task whose time has passed is refused, not promised.

The task panel's toggle is the same resume path the conversation uses. Arming
a one-time task whose stated instant is in the past would fire it immediately
or apologise for a slot that passed while the person themselves had paused it,
so the panel answers 409 and asks for a new time.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.core.auth import issue_user_token
from backend.database.session import AsyncSessionLocal
from backend.discovery.schedule import Cadence
from backend.main import app
from backend.models.scheduled_task import ScheduledTask, ScheduledTaskRun
from backend.tasks.repository import ScheduledTaskRepository


def _as(user_id: str) -> TestClient:
    return TestClient(
        app, headers={"Authorization": f"Bearer {issue_user_token(user_id)}"}
    )


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(ScheduledTaskRun).where(ScheduledTaskRun.user_id == user_id)
        )
        await session.execute(
            delete(ScheduledTask).where(ScheduledTask.user_id == user_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_resuming_a_one_time_task_after_its_slot_is_a_conflict():
    user_id = f"auto_{uuid.uuid4().hex[:12]}"
    try:
        past = datetime.now(UTC) - timedelta(days=1)
        async with AsyncSessionLocal() as session:
            task = await ScheduledTaskRepository(session).create(
                user_id,
                "call the dentist",
                Cadence(
                    cadence="once",
                    hour=9,
                    minute=0,
                    weekday=0,
                    timezone="America/New_York",
                    on_date=past.date(),
                ),
                "imessage",
            )

        with _as(user_id) as client:
            response = client.patch(
                f"/api/v1/automations/{user_id}/tasks/{task['id']}",
                json={"enabled": True},
            )

        assert response.status_code == 409, response.text
        assert "already passed" in response.json()["detail"]
    finally:
        await _cleanup(user_id)


# Pausing is still allowed: the row is kept and its slot is not armed.
@pytest.mark.asyncio
async def test_pausing_a_one_time_task_is_still_allowed():
    user_id = f"auto_{uuid.uuid4().hex[:12]}"
    try:
        past = datetime.now(UTC) - timedelta(days=1)
        async with AsyncSessionLocal() as session:
            task = await ScheduledTaskRepository(session).create(
                user_id,
                "call the dentist",
                Cadence(
                    cadence="once",
                    hour=9,
                    minute=0,
                    weekday=0,
                    timezone="America/New_York",
                    on_date=past.date(),
                ),
                "imessage",
            )

        with _as(user_id) as client:
            response = client.patch(
                f"/api/v1/automations/{user_id}/tasks/{task['id']}",
                json={"enabled": False},
            )

        assert response.status_code == 200, response.text
        assert response.json()["enabled"] is False
    finally:
        await _cleanup(user_id)
