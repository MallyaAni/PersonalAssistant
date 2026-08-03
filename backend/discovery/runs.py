"""Durable persistence for scheduled discovery sweeps.

Leasing follows the presentation-worker pattern rather than introducing a second
scheduler: claim the oldest queued or lease-expired row with `FOR UPDATE SKIP
LOCKED`, hold it with a renewable lease, and let an abandoned run become
claimable again when its lease lapses.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.schedule import Cadence, next_run_at
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule


class DiscoveryRunRepository:
    """Persist schedules and lease the runs they produce."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Create or update one user's cadence and re-arm their next slot.
    async def upsert_schedule(
        self,
        user_id: str,
        cadence: Cadence,
        enabled: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        schedule = await self._schedule_for(user_id)
        upcoming = next_run_at(cadence, moment)
        if schedule is None:
            schedule = DiscoverySchedule(
                user_id=user_id,
                cadence=cadence.cadence,
                hour=cadence.hour,
                weekday=cadence.weekday,
                timezone=cadence.timezone,
                enabled=enabled,
                next_run_at=upcoming,
            )
            self.session.add(schedule)
        else:
            schedule.cadence = cadence.cadence
            schedule.hour = cadence.hour
            schedule.weekday = cadence.weekday
            schedule.timezone = cadence.timezone
            schedule.enabled = enabled
            schedule.next_run_at = upcoming
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule.to_dict()

    async def get_schedule(self, user_id: str) -> dict[str, Any] | None:
        schedule = await self._schedule_for(user_id)
        return schedule.to_dict() if schedule else None

    async def delete_schedule(self, user_id: str) -> bool:
        schedule = await self._schedule_for(user_id)
        if schedule is None:
            return False
        await self.session.delete(schedule)
        await self.session.commit()
        return True

    # Queue a run for every schedule whose slot has arrived, then advance that
    # schedule. Safe to call repeatedly: the slot uniqueness constraint turns a
    # duplicate attempt into a no-op instead of a second sweep.
    async def enqueue_due_runs(
        self, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        moment = now or datetime.now(UTC)
        stmt = (
            select(DiscoverySchedule)
            .where(
                DiscoverySchedule.enabled.is_(True),
                DiscoverySchedule.next_run_at <= moment,
            )
            .with_for_update(skip_locked=True)
        )
        schedules = (await self.session.execute(stmt)).scalars().all()
        created: list[dict[str, Any]] = []
        for schedule in schedules:
            slot = schedule.next_run_at
            cadence = Cadence(
                cadence=schedule.cadence,
                hour=schedule.hour,
                weekday=schedule.weekday,
                timezone=schedule.timezone,
            )
            # Advance first so a failure to insert still moves the schedule on
            # rather than leaving it permanently due.
            schedule.next_run_at = next_run_at(cadence, moment)
            run = DiscoveryRun(
                schedule_id=schedule.id,
                user_id=schedule.user_id,
                status="queued",
                scheduled_for=slot,
            )
            self.session.add(run)
            try:
                await self.session.flush()
            except IntegrityError:
                # Another producer already claimed this slot.
                await self.session.rollback()
                continue
            created.append(run.to_dict())
        await self.session.commit()
        return created

    # Take the oldest claimable run: queued, or running with a lapsed lease.
    async def claim_next(
        self,
        worker_id: str,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        moment = now or datetime.now(UTC)
        run = cast(
            DiscoveryRun | None,
            await self.session.scalar(
                select(DiscoveryRun)
                .where(
                    or_(
                        DiscoveryRun.status == "queued",
                        (
                            (DiscoveryRun.status == "running")
                            & (DiscoveryRun.lease_expires_at < moment)
                        ),
                    ),
                    DiscoveryRun.cancel_requested.is_(False),
                )
                .order_by(DiscoveryRun.scheduled_for.asc())
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
        run.updated_at = moment
        await self.session.commit()
        await self.session.refresh(run)
        # A resumed run carries whatever the previous attempt already achieved,
        # so the caller can decline to redo delivered work.
        return {**run.to_dict(), "digest_json": run.digest_json}

    async def renew_lease(
        self, run_id: str, worker_id: str, lease_seconds: float
    ) -> bool:
        run = await self._owned(run_id, worker_id)
        if run is None or run.status != "running":
            await self.session.rollback()
            return False
        now = datetime.now(UTC)
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        run.updated_at = now
        await self.session.commit()
        return True

    # Persist the digest before anything tries to deliver it, so a crash between
    # the two leaves work to resume rather than work to redo.
    async def save_digest(
        self,
        run_id: str,
        worker_id: str,
        digest_json: str,
        candidate_count: int,
        requests_spent: int,
    ) -> bool:
        run = await self._owned(run_id, worker_id)
        if run is None:
            await self.session.rollback()
            return False
        run.digest_json = digest_json
        run.candidate_count = candidate_count
        run.requests_spent = requests_spent
        run.updated_at = datetime.now(UTC)
        await self.session.commit()
        return True

    # Record delivery exactly once. A second attempt returns False rather than
    # overwriting the original timestamp, which is what makes a resumed run
    # safe to re-enter.
    async def mark_delivered(self, run_id: str, worker_id: str) -> bool:
        run = await self._owned(run_id, worker_id)
        if run is None or run.delivered_at is not None:
            await self.session.rollback()
            return False
        run.delivered_at = datetime.now(UTC)
        await self.session.commit()
        return True

    async def mark_ready(self, run_id: str, worker_id: str) -> None:
        await self._finish(run_id, worker_id, "ready", None)

    async def mark_failed(self, run_id: str, worker_id: str, error_code: str) -> None:
        await self._finish(run_id, worker_id, "failed", error_code)

    async def mark_cancelled(self, run_id: str, worker_id: str) -> None:
        await self._finish(run_id, worker_id, "cancelled", "cancelled")

    # Read recent sweeps and what each one found.
    #
    # Every sweep already persists its digest; nothing could read it back, so a
    # scheduled run's recommendations existed only as a message that had not
    # been sent. That made the whole loop unobservable: the one place the
    # results could be seen was the delivery that does not work yet.
    async def recent_runs(
        self, user_id: str, limit: int = 10
    ) -> tuple[dict[str, Any], ...]:
        stmt = (
            select(DiscoveryRun)
            .where(DiscoveryRun.user_id == user_id)
            .order_by(DiscoveryRun.scheduled_for.desc())
            .limit(max(1, min(limit, 50)))
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return tuple(
            {
                "id": str(row.id),
                "status": row.status,
                "scheduled_for": row.scheduled_for,
                "completed_at": row.completed_at,
                "delivered_at": row.delivered_at,
                "error_code": row.error_code,
                "digest_json": row.digest_json,
            }
            for row in rows
        )

    async def request_cancel(self, user_id: str, run_id: str) -> bool:
        stmt = (
            select(DiscoveryRun)
            .where(
                DiscoveryRun.id == uuid.UUID(run_id),
                DiscoveryRun.user_id == user_id,
            )
            .with_for_update()
        )
        run = (await self.session.execute(stmt)).scalars().first()
        if run is None or run.status in {"ready", "failed", "cancelled"}:
            await self.session.rollback()
            return False
        run.cancel_requested = True
        run.updated_at = datetime.now(UTC)
        await self.session.commit()
        return True

    async def cancellation_requested(self, run_id: str) -> bool:
        run = await self.session.get(DiscoveryRun, uuid.UUID(run_id))
        return bool(run and run.cancel_requested)

    async def get_owned(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        run = await self.session.get(DiscoveryRun, uuid.UUID(run_id))
        if run is None or run.user_id != user_id:
            return None
        return run.to_dict()

    async def list_runs(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        stmt = (
            select(DiscoveryRun)
            .where(DiscoveryRun.user_id == user_id)
            .order_by(DiscoveryRun.scheduled_for.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [row.to_dict() for row in rows]

    async def _finish(
        self, run_id: str, worker_id: str, status: str, error_code: str | None
    ) -> None:
        run = await self._owned(run_id, worker_id)
        if run is None:
            await self.session.rollback()
            return
        now = datetime.now(UTC)
        run.status = status
        run.error_code = error_code
        run.worker_id = None
        run.lease_expires_at = None
        run.completed_at = now
        run.updated_at = now
        await self.session.commit()

    async def _owned(self, run_id: str, worker_id: str) -> DiscoveryRun | None:
        stmt = (
            select(DiscoveryRun)
            .where(
                DiscoveryRun.id == uuid.UUID(run_id),
                DiscoveryRun.worker_id == worker_id,
            )
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _schedule_for(self, user_id: str) -> DiscoverySchedule | None:
        stmt = select(DiscoverySchedule).where(DiscoverySchedule.user_id == user_id)
        return (await self.session.execute(stmt)).scalars().first()
