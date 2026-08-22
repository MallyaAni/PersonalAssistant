"""The task queue's contract: one run per slot, leased claims, once fires once.

Runs against the development database like the sweep-run tests do; every
row is tagged with a throwaway user id and removed afterwards.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal
from backend.discovery.schedule import Cadence
from backend.models.scheduled_task import ScheduledTask, ScheduledTaskRun
from backend.tasks.repository import ScheduledTaskRepository

_ZONE = "America/New_York"


def _daily(hour: int = 9) -> Cadence:
    return Cadence(cadence="daily", hour=hour, weekday=0, timezone=_ZONE)


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(ScheduledTaskRun).where(ScheduledTaskRun.user_id == user_id)
        )
        await session.execute(
            delete(ScheduledTask).where(ScheduledTask.user_id == user_id)
        )
        await session.commit()


async def _force_due(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(ScheduledTask)
            .where(ScheduledTask.user_id == user_id)
            .values(next_run_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()


def _mine(runs: list[dict], user_id: str) -> list[dict]:
    return [run for run in runs if run["user_id"] == user_id]


@pytest.mark.asyncio
async def test_create_arms_a_future_slot_and_lists_for_its_owner():
    user_id = f"task_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(
                user_id, "text me the weather", _daily(), "imessage"
            )
            assert task["next_run_at"] > datetime.now(UTC)
            assert task["channel"] == "imessage"
            assert task["conversation_id"]
            listed = await repo.list_for_user(user_id)
            assert [item["id"] for item in listed] == [task["id"]]
            assert await repo.get_owned("someone_else", task["id"]) is None
    finally:
        await _cleanup(user_id)


# A restarted or duplicated producer must not queue the same slot twice.
@pytest.mark.asyncio
async def test_due_slot_produces_exactly_one_run_however_often_it_is_polled():
    user_id = f"task_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(user_id, "remind me", _daily(), "web")
            await _force_due(user_id)
            first = _mine(await repo.enqueue_due_runs(), user_id)
            second = _mine(await repo.enqueue_due_runs(), user_id)
            assert len(first) == 1
            assert not second
            advanced = await repo.get_owned(user_id, task["id"])
            assert advanced["next_run_at"] > datetime.now(UTC)
    finally:
        await _cleanup(user_id)


# A one-time task takes its single slot and switches itself off.
@pytest.mark.asyncio
async def test_once_task_disables_itself_after_its_slot():
    user_id = f"task_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            once = Cadence(
                cadence="once",
                hour=9,
                weekday=0,
                timezone=_ZONE,
                on_date=(datetime.now(UTC) + timedelta(days=2)).date(),
            )
            task = await repo.create(user_id, "call mom", once, "imessage")
            await _force_due(user_id)
            assert len(_mine(await repo.enqueue_due_runs(), user_id)) == 1
            after = await repo.get_owned(user_id, task["id"])
            assert after["enabled"] is False
            assert after["next_run_at"] is None
            assert await repo.list_for_user(user_id) == []
            assert len(await repo.list_for_user(user_id, enabled_only=False)) == 1
    finally:
        await _cleanup(user_id)


# Two workers polling at once must not both take the same run, and a
# finished run stamps its task with the outcome.
@pytest.mark.asyncio
async def test_claim_is_exclusive_and_finish_stamps_the_task():
    user_id = f"task_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(user_id, "check the temps", _daily(), "imessage")
            await _force_due(user_id)
            await repo.enqueue_due_runs()

        async def claim(worker: str):
            async with AsyncSessionLocal() as session:
                run = await ScheduledTaskRepository(session).claim_next(worker, 60)
                return run if run and run["user_id"] == user_id else None

        claims = [c for c in await asyncio.gather(claim("a"), claim("b")) if c]
        assert len(claims) == 1
        run = claims[0]
        assert run["task"]["instruction"] == "check the temps"
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            await repo.finish(run["id"], "delivered", output="72F and sunny")
            stamped = await repo.get_owned(user_id, task["id"])
            assert stamped["last_status"] == "delivered"
            assert stamped["last_run_at"] is not None
    finally:
        await _cleanup(user_id)


# Pausing keeps the task; resuming re-arms it; cancelling removes it and
# its runs, and none of that works across owners.
@pytest.mark.asyncio
async def test_pause_resume_and_cancel_respect_ownership():
    user_id = f"task_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(user_id, "stretch", _daily(), "imessage")
            assert await repo.set_enabled("intruder", task["id"], False) is False
            assert await repo.set_enabled(user_id, task["id"], False) is True
            assert await repo.list_for_user(user_id) == []
            assert await repo.set_enabled(user_id, task["id"], True) is True
            assert (await repo.get_owned(user_id, task["id"]))["next_run_at"] > (
                datetime.now(UTC)
            )
            assert await repo.delete_owned("intruder", task["id"]) is False
            assert await repo.delete_owned(user_id, task["id"]) is True
            assert await repo.get_owned(user_id, task["id"]) is None
    finally:
        await _cleanup(user_id)
