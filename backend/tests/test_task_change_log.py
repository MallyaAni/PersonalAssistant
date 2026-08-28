"""The change log behind "undo that": what a cancel or reschedule replaced,
and putting it back. Runs against the compose database like the other
repository tests.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.database.session import AsyncSessionLocal
from backend.discovery.schedule import Cadence
from backend.models.scheduled_task import ScheduledTask, ScheduledTaskChange
from backend.tasks.repository import ScheduledTaskRepository

pytestmark = pytest.mark.asyncio


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ScheduledTaskChange).where(ScheduledTaskChange.user_id == user_id))
        await session.execute(delete(ScheduledTask).where(ScheduledTask.user_id == user_id))
        await session.commit()


async def test_a_cancelled_task_comes_back_from_its_snapshot_under_its_old_id():
    user = f"undo_{uuid.uuid4().hex[:10]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(user, "stretch", Cadence("daily", 18, 0, "America/New_York", 0), "imessage")
            await repo.delete_owned(user, task["id"])
            change = await repo.record_change(user, "task", "cancel", task, None, task_id=task["id"])
            assert change["before"]["instruction"] == "stretch" and change["after"] is None

            latest = await repo.latest_undoable(user)
            assert latest["id"] == change["id"]
            restored = await repo.restore(user, latest["before"])
            assert restored["id"] == task["id"]
            assert (restored["cadence"], restored["hour"], restored["enabled"]) == ("daily", 18, True)
            assert restored["next_run_at"] is not None
            assert await repo.mark_undone(user, change["id"])
            assert await repo.latest_undoable(user) is None
    finally:
        await _cleanup(user)


async def test_undo_itself_is_recorded_but_never_undoable():
    user = f"undo_{uuid.uuid4().hex[:10]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            await repo.record_change(user, "scout_schedule", "schedule", None, {"cadence": "daily", "hour": 15})
            await repo.record_change(user, "scout_schedule", "undo", {"cadence": "daily", "hour": 15}, None)
            latest = await repo.latest_undoable(user)
            assert latest["operation"] == "schedule"
    finally:
        await _cleanup(user)


@pytest.mark.asyncio
async def test_undo_never_reaches_another_conversation():
    """Deploy #16, 2026-08-28: "forget that" in a fresh conversation cancelled
    a reminder set minutes earlier in another one. The latest undoable change
    is looked up within the conversation that asks."""
    import uuid

    from backend.database.session import AsyncSessionLocal
    from backend.tasks.repository import ScheduledTaskRepository

    user = f"undo_{uuid.uuid4().hex[:8]}"
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        repo = ScheduledTaskRepository(db)
        try:
            await repo.record_change(user, "task", "cancel", {"x": 1}, None, conversation_id=a)
            saved = await repo.record_change(user, "memory", "save", None, {"kind": "semantic_fact", "id": "m1"}, conversation_id=b)
            assert saved["conversation_id"] == b
            # Asked from conversation b: the memory save, not a's reminder.
            latest = await repo.latest_undoable(user, b)
            assert latest is not None and latest["kind"] == "memory"
            # Asked from a conversation with no changes: nothing, never a's.
            assert await repo.latest_undoable(user, str(uuid.uuid4())) is None
            # Unscoped (older callers): the most recent overall, as before.
            assert (await repo.latest_undoable(user))["kind"] == "memory"
        finally:
            from sqlalchemy import text

            await db.execute(text("delete from scheduled_task_changes where user_id = :u"), {"u": user})
            await db.commit()
