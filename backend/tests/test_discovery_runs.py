import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.schedule import Cadence, next_run_at
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule

_ZONE = "America/New_York"


def _weekly(hour: int = 9, weekday: int = 4) -> Cadence:
    return Cadence(cadence="weekly", hour=hour, weekday=weekday, timezone=_ZONE)


def _daily(hour: int = 9) -> Cadence:
    return Cadence(cadence="daily", hour=hour, weekday=0, timezone=_ZONE)


def test_cadence_rejects_values_outside_its_domain():
    with pytest.raises(ValueError, match="Unsupported cadence"):
        Cadence(cadence="hourly", hour=9, weekday=0, timezone=_ZONE)
    with pytest.raises(ValueError, match="Hour must be"):
        Cadence(cadence="daily", hour=24, weekday=0, timezone=_ZONE)
    with pytest.raises(ValueError, match="Weekday must be"):
        Cadence(cadence="weekly", hour=9, weekday=7, timezone=_ZONE)
    with pytest.raises(ValueError, match="Unknown timezone"):
        next_run_at(
            Cadence(cadence="daily", hour=9, weekday=0, timezone="Mars/Olympus"),
            datetime.now(UTC),
        )


# The next slot must be strictly in the future, or completing a run at exactly
# its slot time would immediately re-arm the same slot and spin.
def test_next_run_is_strictly_future():
    cadence = _daily(hour=9)
    at_slot = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)  # 09:00 America/New_York

    upcoming = next_run_at(cadence, at_slot)

    assert upcoming > at_slot
    assert (upcoming - at_slot) == timedelta(days=1)


def test_weekly_cadence_lands_on_the_requested_weekday():
    # Monday 2026-08-03; ask for Friday (weekday 4).
    monday = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    upcoming = next_run_at(_weekly(hour=9, weekday=4), monday)

    assert upcoming.astimezone(upcoming.tzinfo).weekday() == 4
    assert upcoming > monday


# A daylight-saving transition must move the wall-clock hour, not preserve the
# old UTC offset, or a 9am sweep silently becomes an 8am or 10am one.
def test_daily_cadence_keeps_the_local_hour_across_a_dst_shift():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(_ZONE)
    before = datetime(2026, 11, 1, 2, 0, tzinfo=zone)  # US DST ends 2026-11-01

    upcoming = next_run_at(_daily(hour=9), before)

    assert upcoming.astimezone(zone).hour == 9


@pytest.mark.asyncio
async def test_schedule_round_trips_and_arms_a_future_slot():
    user_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            saved = await repo.upsert_schedule(user_id, _weekly())

            assert saved["cadence"] == "weekly"
            assert saved["next_run_at"] > datetime.now(UTC)
            assert (await repo.get_schedule(user_id))["hour"] == 9

            await repo.upsert_schedule(user_id, _daily(hour=7))
            assert (await repo.get_schedule(user_id))["cadence"] == "daily"
    finally:
        await _cleanup(user_id)


# Producing due runs must be repeatable. A restarted or duplicated producer
# cannot queue the same sweep twice, or the user sees the digest twice.
@pytest.mark.asyncio
async def test_due_slot_produces_exactly_one_run_however_often_it_is_polled():
    user_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            await repo.upsert_schedule(user_id, _daily(hour=9))
            await _force_due(session, user_id)

            first = await repo.enqueue_due_runs()
            second = await repo.enqueue_due_runs()
            third = await repo.enqueue_due_runs()

            mine = [run for run in first if run["user_id"] == user_id]
            assert len(mine) == 1
            assert not [run for run in second if run["user_id"] == user_id]
            assert not [run for run in third if run["user_id"] == user_id]
            assert len(await repo.list_runs(user_id)) == 1
    finally:
        await _cleanup(user_id)


# Two workers polling at once must not both take the same run.
@pytest.mark.asyncio
async def test_concurrent_workers_cannot_claim_the_same_run():
    user_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            await repo.upsert_schedule(user_id, _daily())
            await _force_due(session, user_id)
            await repo.enqueue_due_runs()

        async def claim(worker: str) -> dict | None:
            async with AsyncSessionLocal() as session:
                return await DiscoveryRunRepository(session).claim_next(worker, 60)

        claimed = await asyncio.gather(claim("worker-a"), claim("worker-b"))
        mine = [run for run in claimed if run is not None and run["user_id"] == user_id]

        assert len(mine) == 1
        assert mine[0]["attempt_count"] == 1
    finally:
        await _cleanup(user_id)


# An abandoned run becomes claimable again once its lease lapses, and the second
# attempt inherits the digest the first one already persisted.
@pytest.mark.asyncio
async def test_expired_lease_is_reclaimable_and_resumes_prior_work():
    user_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            await repo.upsert_schedule(user_id, _daily())
            await _force_due(session, user_id)
            await repo.enqueue_due_runs()

            first = await repo.claim_next("worker-a", lease_seconds=60)
            assert first is not None
            await repo.save_digest(
                first["id"], "worker-a", '{"items": [1, 2]}', 2, requests_spent=3
            )

            # The worker dies without finishing; the lease lapses.
            await _expire_lease(session, first["id"])

            second = await repo.claim_next("worker-b", lease_seconds=60)
            assert second is not None
            assert second["id"] == first["id"]
            assert second["attempt_count"] == 2
            # Work already done is not lost, so it is not redone.
            assert second["digest_json"] == '{"items": [1, 2]}'
    finally:
        await _cleanup(user_id)


# The whole point of the milestone: a resumed run must not deliver twice.
@pytest.mark.asyncio
async def test_delivery_is_recorded_exactly_once():
    user_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            await repo.upsert_schedule(user_id, _daily())
            await _force_due(session, user_id)
            await repo.enqueue_due_runs()

            claimed = await repo.claim_next("worker-a", lease_seconds=60)
            assert claimed is not None
            assert await repo.mark_delivered(claimed["id"], "worker-a") is True
            # A crash after delivery, then a resumed attempt.
            assert await repo.mark_delivered(claimed["id"], "worker-a") is False

            await _expire_lease(session, claimed["id"])
            resumed = await repo.claim_next("worker-b", lease_seconds=60)
            assert resumed is not None
            assert await repo.mark_delivered(resumed["id"], "worker-b") is False
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_lease_renewal_requires_the_owning_worker():
    user_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            await repo.upsert_schedule(user_id, _daily())
            await _force_due(session, user_id)
            await repo.enqueue_due_runs()
            claimed = await repo.claim_next("worker-a", lease_seconds=60)
            assert claimed is not None

            assert await repo.renew_lease(claimed["id"], "worker-a", 60) is True
            assert await repo.renew_lease(claimed["id"], "worker-b", 60) is False
    finally:
        await _cleanup(user_id)


# A cancelled run must never be picked up, even while it is still queued.
@pytest.mark.asyncio
async def test_cancellation_removes_a_run_from_the_claimable_set():
    user_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            await repo.upsert_schedule(user_id, _daily())
            await _force_due(session, user_id)
            queued = await repo.enqueue_due_runs()
            run_id = [run for run in queued if run["user_id"] == user_id][0]["id"]

            assert await repo.request_cancel(user_id, run_id) is True
            assert await repo.cancellation_requested(run_id) is True

            claimed = await repo.claim_next("worker-a", lease_seconds=60)
            assert claimed is None or claimed["id"] != run_id
    finally:
        await _cleanup(user_id)


# One user's identifier must never cancel another user's run.
@pytest.mark.asyncio
async def test_cancel_and_read_are_scoped_to_the_owning_user():
    owner = f"run_{uuid.uuid4().hex[:12]}"
    attacker = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            await repo.upsert_schedule(owner, _daily())
            await _force_due(session, owner)
            queued = await repo.enqueue_due_runs()
            run_id = [run for run in queued if run["user_id"] == owner][0]["id"]

            assert await repo.request_cancel(attacker, run_id) is False
            assert await repo.get_owned(attacker, run_id) is None
            assert await repo.get_owned(owner, run_id) is not None
    finally:
        await _cleanup(owner, attacker)


@pytest.mark.asyncio
async def test_terminal_states_are_recorded_with_the_lease_released():
    user_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoveryRunRepository(session)
            await repo.upsert_schedule(user_id, _daily())
            await _force_due(session, user_id)
            await repo.enqueue_due_runs()
            claimed = await repo.claim_next("worker-a", lease_seconds=60)
            assert claimed is not None

            await repo.mark_failed(claimed["id"], "worker-a", "source_unreachable")
            finished = await repo.get_owned(user_id, claimed["id"])

            assert finished is not None
            assert finished["status"] == "failed"
            assert finished["error_code"] == "source_unreachable"
            assert finished["completed_at"] is not None
            # A finished run is no longer claimable by anyone.
            assert await repo.claim_next("worker-b", lease_seconds=60) is None
    finally:
        await _cleanup(user_id)


# Force the schedule to be due without waiting for real time to pass.
async def _force_due(session, user_id: str) -> None:
    from sqlalchemy import update

    await session.execute(
        update(DiscoverySchedule)
        .where(DiscoverySchedule.user_id == user_id)
        .values(next_run_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await session.commit()


async def _expire_lease(session, run_id: str) -> None:
    from sqlalchemy import update

    await session.execute(
        update(DiscoveryRun)
        .where(DiscoveryRun.id == uuid.UUID(run_id))
        .values(lease_expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await session.commit()


async def _cleanup(*user_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DiscoveryRun).where(DiscoveryRun.user_id.in_(list(user_ids)))
        )
        await session.execute(
            delete(DiscoverySchedule).where(
                DiscoverySchedule.user_id.in_(list(user_ids))
            )
        )
        await session.commit()


# A sweep can sit at a quarter past. The slot was built from the hour alone, so
# every schedule fired at :00 regardless of what anyone wanted.
def test_a_slot_can_carry_minutes():
    cadence = Cadence(cadence="daily", hour=9, minute=15, weekday=0, timezone=_ZONE)

    upcoming = next_run_at(cadence, datetime(2026, 8, 3, 12, 0, tzinfo=UTC))

    local = upcoming.astimezone(ZoneInfo(_ZONE))
    assert (local.hour, local.minute) == (9, 15)


# A schedule written before minutes existed reads as 0, which is exactly where
# it used to fire, so the migration changes nobody's timing.
def test_an_existing_schedule_keeps_firing_on_the_hour():
    cadence = Cadence(cadence="weekly", hour=9, weekday=4, timezone=_ZONE)

    upcoming = next_run_at(cadence, datetime(2026, 8, 3, 12, 0, tzinfo=UTC))

    local = upcoming.astimezone(ZoneInfo(_ZONE))
    assert (local.hour, local.minute) == (9, 0)


# The minute is validated like every other field rather than trusted.
def test_an_impossible_minute_is_refused():
    with pytest.raises(ValueError, match="Minute"):
        Cadence(cadence="daily", hour=9, minute=60, weekday=0, timezone=_ZONE)
    with pytest.raises(ValueError, match="Minute"):
        Cadence(cadence="daily", hour=9, minute=-1, weekday=0, timezone=_ZONE)


# The slot stays strictly future, so a run completing exactly on its own slot
# cannot re-arm the same one and spin. Minutes must not weaken that.
def test_a_quarter_past_slot_is_still_strictly_future():
    zone = ZoneInfo(_ZONE)
    cadence = Cadence(cadence="daily", hour=9, minute=45, weekday=0, timezone=_ZONE)
    exactly_on_slot = datetime(2026, 8, 3, 9, 45, tzinfo=zone)

    upcoming = next_run_at(cadence, exactly_on_slot)

    assert upcoming > exactly_on_slot
    assert upcoming.astimezone(zone).date() == exactly_on_slot.date() + timedelta(
        days=1
    )


# Advancing a schedule must keep the minute it was set to. The stored row kept
# the right value, so a schedule rebuilt at :00 only showed up as a sweep that
# had silently moved half an hour earlier.
@pytest.mark.asyncio
async def test_advancing_a_schedule_keeps_its_minute():
    user_id = f"sched_{uuid.uuid4().hex[:8]}"
    zone = ZoneInfo(_ZONE)
    try:
        async with AsyncSessionLocal() as session:
            runs = DiscoveryRunRepository(session)
            await runs.upsert_schedule(
                user_id,
                Cadence(cadence="daily", hour=9, minute=45, weekday=0, timezone=_ZONE),
                now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
            )
            # Due now, so the producer advances it to the following slot.
            await runs.enqueue_due_runs(now=datetime(2026, 8, 6, 20, 0, tzinfo=UTC))
            saved = await runs.get_schedule(user_id)

        assert saved is not None
        assert saved["minute"] == 45
        assert saved["next_run_at"].astimezone(zone).minute == 45
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoveryRun).where(DiscoveryRun.user_id == user_id)
            )
            await session.execute(
                delete(DiscoverySchedule).where(DiscoverySchedule.user_id == user_id)
            )
            await session.commit()
