"""Storage for scheduled tasks and their fired runs.

The queue half is a copy of the shape Scout's run repository proved in
production: due tasks become queued runs (one per slot, unique by
constraint), a worker claims the oldest with a lease, a crashed worker's
lease lapses and the run is reclaimed, and finishing a run advances the
task's next slot - or disables a one-time task.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.schedule import Cadence, next_run_at
from backend.models.scheduled_task import ScheduledTask, ScheduledTaskRun


# A task row as plain data, so callers never hold a live ORM object.
def _task_dict(task: ScheduledTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "user_id": task.user_id,
        "instruction": task.instruction,
        "cadence": task.cadence,
        "hour": task.hour,
        "minute": task.minute,
        "weekday": task.weekday,
        "on_date": task.on_date.isoformat() if task.on_date else None,
        "timezone": task.timezone,
        "channel": task.channel,
        "conversation_id": str(task.conversation_id) if task.conversation_id else None,
        "next_run_at": task.next_run_at,
        "enabled": task.enabled,
        "last_run_at": task.last_run_at,
        "last_status": task.last_status,
    }


# A run row as plain data.
def _run_dict(run: ScheduledTaskRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "task_id": str(run.task_id),
        "user_id": run.user_id,
        "status": run.status,
        "scheduled_for": run.scheduled_for,
        "attempt_count": run.attempt_count,
        "worker_id": run.worker_id,
        "output": run.output,
        "error_code": run.error_code,
    }


class ScheduledTaskRepository:
    """Tasks and runs, on the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Create a task and arm its first slot.
    async def create(
        self,
        user_id: str,
        instruction: str,
        cadence: Cadence,
        channel: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        task = ScheduledTask(
            user_id=user_id,
            instruction=instruction.strip(),
            cadence=cadence.cadence,
            hour=cadence.hour,
            minute=cadence.minute,
            weekday=cadence.weekday,
            on_date=cadence.on_date,
            timezone=cadence.timezone,
            channel=channel,
            conversation_id=uuid.uuid4(),
            next_run_at=next_run_at(cadence, moment),
            enabled=True,
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return _task_dict(task)

    # The person's tasks, oldest first; enabled only unless asked otherwise.
    async def list_for_user(
        self, user_id: str, enabled_only: bool = True
    ) -> list[dict[str, Any]]:
        stmt = select(ScheduledTask).where(ScheduledTask.user_id == user_id)
        if enabled_only:
            stmt = stmt.where(ScheduledTask.enabled.is_(True))
        rows = (
            await self.session.execute(stmt.order_by(ScheduledTask.created_at))
        ).scalars()
        return [_task_dict(task) for task in rows]

    # One task, only if it belongs to this person.
    async def get_owned(self, user_id: str, task_id: str) -> dict[str, Any] | None:
        task = await self._owned(user_id, task_id)
        return _task_dict(task) if task else None

    # Enabling re-arms the next slot from now; disabling leaves the slot as
    # is but skipped, so re-enabling later never fires a stale one.
    async def set_enabled(self, user_id: str, task_id: str, enabled: bool) -> bool:
        task = await self._owned(user_id, task_id)
        if task is None:
            return False
        task.enabled = enabled
        if enabled:
            task.next_run_at = next_run_at(self._cadence(task), datetime.now(UTC))
        await self.session.commit()
        return True

    # Remove a task outright; its runs go with it by the foreign key.
    async def delete_owned(self, user_id: str, task_id: str) -> bool:
        task = await self._owned(user_id, task_id)
        if task is None:
            return False
        await self.session.delete(task)
        await self.session.commit()
        return True

    async def _owned(self, user_id: str, task_id: str) -> ScheduledTask | None:
        try:
            key = uuid.UUID(str(task_id))
        except ValueError:
            return None
        return await self.session.scalar(
            select(ScheduledTask).where(
                ScheduledTask.id == key, ScheduledTask.user_id == user_id
            )
        )

    # The row's schedule columns back as the value next_run_at understands.
    @staticmethod
    def _cadence(task: ScheduledTask) -> Cadence:
        return Cadence(
            cadence=task.cadence,
            hour=task.hour,
            minute=task.minute,
            weekday=task.weekday,
            timezone=task.timezone,
            on_date=task.on_date,
        )

    # Every enabled task whose slot has arrived becomes one queued run. The
    # slot advances first so a failure to insert still moves the task on
    # rather than leaving it permanently due; a once-task is disabled here,
    # its single slot having been taken.
    async def enqueue_due_runs(
        self, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        moment = now or datetime.now(UTC)
        tasks = (
            (
                await self.session.execute(
                    select(ScheduledTask)
                    .where(
                        ScheduledTask.enabled.is_(True),
                        ScheduledTask.next_run_at <= moment,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        created: list[dict[str, Any]] = []
        for task in tasks:
            slot = task.next_run_at
            if task.cadence == "once":
                task.enabled = False
                task.next_run_at = None
            else:
                task.next_run_at = next_run_at(self._cadence(task), moment)
            run = ScheduledTaskRun(
                task_id=task.id,
                user_id=task.user_id,
                status="queued",
                scheduled_for=slot,
            )
            self.session.add(run)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                continue
            created.append(_run_dict(run))
        await self.session.commit()
        return created

    # Take the oldest claimable run: queued, or running with a lapsed lease.
    async def claim_next(
        self, worker_id: str, lease_seconds: float, now: datetime | None = None
    ) -> dict[str, Any] | None:
        moment = now or datetime.now(UTC)
        run = cast(
            ScheduledTaskRun | None,
            await self.session.scalar(
                select(ScheduledTaskRun)
                .where(
                    or_(
                        ScheduledTaskRun.status == "queued",
                        (ScheduledTaskRun.status == "running")
                        & (ScheduledTaskRun.lease_expires_at < moment),
                    )
                )
                .order_by(ScheduledTaskRun.scheduled_for.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            ),
        )
        if run is None:
            await self.session.rollback()
            return None
        run.status = "running"
        run.worker_id = worker_id
        run.lease_expires_at = moment + timedelta(seconds=lease_seconds)
        run.attempt_count += 1
        run.started_at = run.started_at or moment
        await self.session.commit()
        await self.session.refresh(run)
        task = await self.session.get(ScheduledTask, run.task_id)
        return {**_run_dict(run), "task": _task_dict(task) if task else None}

    # Keep a long turn's claim alive.
    async def renew_lease(
        self, run_id: str, worker_id: str, lease_seconds: float
    ) -> bool:
        run = await self.session.get(ScheduledTaskRun, uuid.UUID(str(run_id)))
        if run is None or run.worker_id != worker_id or run.status != "running":
            return False
        run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        await self.session.commit()
        return True

    # Close a run with what happened, and stamp the task with the outcome.
    async def finish(
        self,
        run_id: str,
        status: str,
        output: str | None = None,
        error_code: str | None = None,
    ) -> None:
        run = await self.session.get(ScheduledTaskRun, uuid.UUID(str(run_id)))
        if run is None:
            return
        moment = datetime.now(UTC)
        run.status = status
        run.output = output
        run.error_code = error_code
        run.completed_at = moment
        if status == "delivered":
            run.delivered_at = moment
        task = await self.session.get(ScheduledTask, run.task_id)
        if task is not None:
            task.last_run_at = moment
            task.last_status = status
        await self.session.commit()
