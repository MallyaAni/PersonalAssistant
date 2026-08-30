"""Storage for scheduled tasks and their fired runs.

The queue half is a copy of the shape Scout's run repository proved in
production: due tasks become queued runs (one per slot, unique by
constraint), a worker claims the oldest with a lease, a crashed worker's
lease lapses and the run is reclaimed, and finishing a run advances the
task's next slot - or disables a one-time task.
"""

import logging
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.discovery.schedule import Cadence, next_run_at
from backend.models.scheduled_task import (
    ScheduledTask,
    ScheduledTaskChange,
    ScheduledTaskRun,
)

logger = logging.getLogger(__name__)


# A task row as plain data, so callers never hold a live ORM object.
def _task_dict(task: ScheduledTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "user_id": task.user_id,
        "instruction": task.instruction,
        "cadence": task.cadence,
        "kind": task.kind,
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


# A change row as plain data, snapshots decoded.
# A conversation id as the column stores it, or None for anything that is
# not a UUID (older callers, tests).
def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _change_dict(change: ScheduledTaskChange) -> dict[str, Any]:
    return {
        "id": str(change.id),
        "user_id": change.user_id,
        "kind": change.kind,
        "operation": change.operation,
        "task_id": str(change.task_id) if change.task_id else None,
        "conversation_id": str(change.conversation_id) if change.conversation_id else None,
        "before": json.loads(change.before) if change.before else None,
        "after": json.loads(change.after) if change.after else None,
        "created_at": change.created_at,
        "undone_at": change.undone_at,
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
        kind: str = "reminder",
    ) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        task = ScheduledTask(
            user_id=user_id,
            instruction=instruction.strip(),
            kind=kind,
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

    # Move an existing task to a new schedule, and optionally change what it
    # says. Re-arming from `now` is the whole point: the row's old slot may
    # already be in the past, and leaving it there would either fire
    # immediately or never.
    #
    # This exists because "change the tesla reminder to 5 minutes from now" had
    # no write path at all. The advice was to cancel and re-create, which is two
    # tool calls, and the selector makes one decision per turn - so the request
    # was not expressible and the model answered as though it had done it.
    async def reschedule_owned(
        self,
        user_id: str,
        task_id: str,
        cadence: Cadence,
        instruction: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        task = await self._owned(user_id, task_id)
        if task is None:
            return None
        task.cadence = cadence.cadence
        task.hour = cadence.hour
        task.minute = cadence.minute
        task.weekday = cadence.weekday
        task.on_date = cadence.on_date
        task.timezone = cadence.timezone
        if instruction and instruction.strip():
            task.instruction = instruction.strip()
        # A rescheduled task is armed by definition. Rescheduling a paused one
        # is how someone resumes it at a different time, and leaving it
        # disabled would silently discard the request.
        task.enabled = True
        task.next_run_at = next_run_at(cadence, now or datetime.now(UTC))
        await self.session.commit()
        await self.session.refresh(task)
        return _task_dict(task)

    # Remove a task outright; its runs go with it by the foreign key.
    async def delete_owned(self, user_id: str, task_id: str) -> bool:
        task = await self._owned(user_id, task_id)
        if task is None:
            return False
        await self.session.delete(task)
        await self.session.commit()
        return True

    # Write down one change and what it replaced. Snapshots are the task dicts
    # this repository hands out (datetimes as ISO text), or a Scout schedule
    # dict; None before means "did not exist", None after means "removed".
    async def record_change(
        self,
        user_id: str,
        kind: str,
        operation: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        change = ScheduledTaskChange(
            user_id=user_id,
            kind=kind,
            operation=operation,
            task_id=uuid.UUID(task_id) if task_id else None,
            conversation_id=_uuid_or_none(conversation_id),
            before=json.dumps(before, default=str) if before is not None else None,
            after=json.dumps(after, default=str) if after is not None else None,
        )
        self.session.add(change)
        await self.session.commit()
        await self.session.refresh(change)
        return _change_dict(change)

    # The most recent change of this person's that has not been undone, or
    # None. Undo itself is recorded as an operation but is never undoable:
    # "undo" twice walks back two changes, not one and its reversal. With a
    # conversation given, only changes made in that conversation count: an
    # "undo" never reaches into another thread's reminders (deploy #16).
    async def latest_undoable(
        self, user_id: str, conversation_id: str | None = None
    ) -> dict[str, Any] | None:
        conditions = [
            ScheduledTaskChange.user_id == user_id,
            ScheduledTaskChange.undone_at.is_(None),
            ScheduledTaskChange.operation != "undo",
        ]
        scoped = _uuid_or_none(conversation_id)
        if scoped is not None:
            conditions.append(ScheduledTaskChange.conversation_id == scoped)
        result = await self.session.execute(
            select(ScheduledTaskChange)
            .where(*conditions)
            .order_by(ScheduledTaskChange.created_at.desc())
            .limit(1)
        )
        change = result.scalar_one_or_none()
        return _change_dict(change) if change else None

    async def mark_undone(self, user_id: str, change_id: str) -> bool:
        result = await self.session.execute(
            select(ScheduledTaskChange).where(
                ScheduledTaskChange.id == uuid.UUID(change_id),
                ScheduledTaskChange.user_id == user_id,
            )
        )
        change = result.scalar_one_or_none()
        if change is None:
            return False
        change.undone_at = datetime.now(UTC)
        await self.session.commit()
        return True

    # Put a cancelled task back from its snapshot, under its old id so its
    # conversation and run history still belong to it. The next run is
    # computed afresh: the snapshot's may be in the past.
    async def restore(
        self, user_id: str, snapshot: dict[str, Any], now: datetime | None = None
    ) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        cadence = Cadence(
            cadence=str(snapshot["cadence"]),
            hour=int(snapshot["hour"]),
            minute=int(snapshot.get("minute") or 0),
            weekday=int(snapshot.get("weekday") or 0),
            timezone=str(snapshot["timezone"]),
            on_date=(
                date.fromisoformat(str(snapshot["on_date"]))
                if snapshot.get("on_date")
                else None
            ),
        )
        task = ScheduledTask(
            id=uuid.UUID(str(snapshot["id"])) if snapshot.get("id") else uuid.uuid4(),
            user_id=user_id,
            instruction=str(snapshot["instruction"]),
            kind=str(snapshot.get("kind") or "reminder"),
            cadence=cadence.cadence,
            hour=cadence.hour,
            minute=cadence.minute,
            weekday=cadence.weekday,
            on_date=cadence.on_date,
            timezone=cadence.timezone,
            channel=str(snapshot.get("channel") or "web"),
            conversation_id=(
                uuid.UUID(str(snapshot["conversation_id"]))
                if snapshot.get("conversation_id")
                else uuid.uuid4()
            ),
            next_run_at=next_run_at(cadence, moment),
            enabled=bool(snapshot.get("enabled", True)),
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return _task_dict(task)

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
        self, now: datetime | None = None, stale_after_seconds: float | None = None
    ) -> list[dict[str, Any]]:
        moment = now or datetime.now(UTC)
        stale_after = (
            settings.SCHEDULED_TASK_STALE_SECONDS
            if stale_after_seconds is None
            else stale_after_seconds
        )
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
            # A slot the worker slept through is not worth firing late: a 7am
            # briefing delivered at 11pm because the machine was down all day
            # is worse than nothing, and the person cannot tell it from a bug.
            # The slot is skipped; the task itself has already moved on.
            if slot is not None and (moment - slot).total_seconds() > stale_after:
                logger.info(
                    "scheduled_task_slot_stale",
                    extra={"task": str(task.id), "slot": slot.isoformat()},
                )
                continue
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
    #
    # A run whose delivery already happened is never re-claimed, whatever its
    # lease says: `finish` is the only thing that closes a run, so a worker
    # killed between sending the bubbles and closing the row would otherwise
    # have the next worker send them all over again.
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
        worker_id: str | None = None,
        max_attempts: int = 3,
    ) -> str:
        run = await self.session.get(ScheduledTaskRun, uuid.UUID(str(run_id)))
        if run is None:
            return "missing"
        # A worker whose lease lapsed must not close a run another worker has
        # since taken over, or the live attempt is marked finished under it.
        if worker_id is not None and run.worker_id not in (None, worker_id):
            return "not_mine"
        moment = datetime.now(UTC)
        # A failure that has attempts left goes back on the queue rather than
        # dying silently: a model timeout at 7am used to end the task for good,
        # and for a one-time reminder that meant it simply never arrived.
        if status == "failed" and run.attempt_count < max_attempts:
            run.status = "queued"
            run.error_code = error_code
            run.worker_id = None
            run.lease_expires_at = None
            await self.session.commit()
            return "requeued"
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
        return status
