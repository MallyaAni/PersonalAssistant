"""What a scheduled firing is not allowed to do.

A fired task carries the person's own instruction and runs with nobody
watching. The instruction reads exactly like a request to schedule
("remind me every morning to take my meds"), so without a gate the router
calls schedule_task again: the person receives a confirmation instead of
their reminder, and a second task appears - then four. The cancel side is
worse, hard-deleting the task that was firing. These pin the gate.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.database.session import AsyncSessionLocal
from backend.discovery.schedule import Cadence
from backend.models.scheduled_task import ScheduledTask, ScheduledTaskRun
from backend.services.conversation_service import ConversationService
from backend.tasks.repository import ScheduledTaskRepository
from backend.tools import AUTOMATION_TOOLS, ManageTasksAction, ScheduleTaskAction
from backend.tools.registry import builtin_tools

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


def test_the_automation_tools_are_withheld_from_an_unattended_turn():
    attended = {row.name for row in builtin_tools(("diagram", "presentation"))}
    unattended = {
        row.name for row in builtin_tools(("diagram", "presentation"), AUTOMATION_TOOLS)
    }
    assert attended >= AUTOMATION_TOOLS
    assert not (AUTOMATION_TOOLS & unattended)
    # Everything else a turn might legitimately need still is offered.
    assert unattended >= {"generate_image", "edit_image", "create_diagram"}


# The second wall: even a provider response naming a withheld tool cannot
# reach the repository, because the bookkeeping path refuses a fired turn.
@pytest.mark.asyncio
async def test_a_fired_turn_never_writes_to_the_schedule():
    user_id = f"gate_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            existing = await repo.create(user_id, "take my meds", _daily(), "imessage")
            service = ConversationService.__new__(ConversationService)
            service.scheduled_tasks = repo
            service.skills = None

            for action in (
                ScheduleTaskAction("take my meds", "daily", 9, 0),
                ManageTasksAction("cancel", "the meds one"),
            ):
                outcome = await service._task_turn_context(
                    user_id, action, {"scheduled_task": True}
                )
                assert outcome is None, action

            tasks = await repo.list_for_user(user_id, enabled_only=False)
            assert [task["id"] for task in tasks] == [existing["id"]]
    finally:
        await _cleanup(user_id)


# An attended turn is unchanged: the same action still schedules.
@pytest.mark.asyncio
async def test_an_ordinary_turn_still_schedules():
    user_id = f"gate_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            service = ConversationService.__new__(ConversationService)
            service.scheduled_tasks = repo
            service.skills = None
            service.discovery_profile = None
            service.main_action_selector = None

            outcome = await service._task_turn_context(
                user_id,
                ScheduleTaskAction("take my meds", "daily", 9, 0),
                {"channel": "imessage"},
            )
            # No locality is configured for this throwaway user, so the reply
            # is told to ask for the place - which is the attended path
            # running, not the gate refusing it.
            assert outcome is not None
            assert outcome["task_outcome"]["kind"] == "needs_place"
    finally:
        await _cleanup(user_id)


# A slot the worker slept through is skipped rather than fired at the wrong
# hour: a 7am briefing delivered at 11pm reads as a bug, not as news.
@pytest.mark.asyncio
async def test_a_slot_the_worker_slept_through_is_skipped():
    user_id = f"gate_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            task = await repo.create(user_id, "morning brief", _daily(7), "imessage")
            await session.execute(
                update(ScheduledTask)
                .where(ScheduledTask.user_id == user_id)
                .values(next_run_at=datetime.now(UTC) - timedelta(hours=16))
            )
            await session.commit()

            created = await repo.enqueue_due_runs()

            assert not [run for run in created if run["user_id"] == user_id]
            # The task itself has moved on to its next real slot.
            after = await repo.get_owned(user_id, task["id"])
            assert after["next_run_at"] > datetime.now(UTC)
            assert after["enabled"] is True
    finally:
        await _cleanup(user_id)


# A failure with attempts left goes back on the queue instead of dying.
@pytest.mark.asyncio
async def test_a_failed_run_is_retried_then_finally_reported():
    user_id = f"gate_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = ScheduledTaskRepository(session)
            await repo.create(user_id, "check the temps", _daily(), "imessage")
            await session.execute(
                update(ScheduledTask)
                .where(ScheduledTask.user_id == user_id)
                .values(next_run_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await session.commit()
            await repo.enqueue_due_runs()

            outcomes = []
            for _ in range(4):
                run = await repo.claim_next("worker-a", 60)
                if run is None or run["user_id"] != user_id:
                    break
                outcomes.append(
                    await repo.finish(
                        run["id"],
                        "failed",
                        error_code="turn_failed",
                        worker_id="worker-a",
                    )
                )
            assert outcomes == ["requeued", "requeued", "failed"]

            # And a worker whose lease lapsed cannot close another's run.
            await repo.create(user_id, "second", _daily(), "imessage")
            await session.execute(
                update(ScheduledTask)
                .where(ScheduledTask.user_id == user_id)
                .values(next_run_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await session.commit()
            await repo.enqueue_due_runs()
            mine = await repo.claim_next("worker-b", 60)
            assert mine is not None
            assert (
                await repo.finish(mine["id"], "delivered", worker_id="worker-ghost")
                == "not_mine"
            )
    finally:
        await _cleanup(user_id)
