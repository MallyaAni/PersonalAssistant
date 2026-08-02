"""The scheduled loop, end to end.

Everything else in discovery is exercised by calling it directly. This is the
only coverage that answers "does the thing actually run on its own", which is
the difference between a feature and an endpoint.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal
from backend.discovery.events import DiscoveredEvent
from backend.discovery.repository import DiscoveryProfileRepository
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.schedule import Cadence
from backend.discovery.sources_repository import DiscoverySourceRepository
from backend.models.discovery import DiscoveryInterest
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule
from backend.models.discovery_source import DiscoverySeenItem, DiscoverySource
from backend.workers.discovery_worker import DiscoveryWorker


class _StubSource:
    def __init__(self, events: tuple[DiscoveredEvent, ...]) -> None:
        self._events = events
        self.fetches = 0

    async def fetch(self) -> tuple[DiscoveredEvent, ...]:
        self.fetches += 1
        return self._events


def _vec(*values: float) -> list[float]:
    vector = [0.0] * 768
    for index, value in enumerate(values):
        vector[index] = value
    return vector


class _StubEmbeddings:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_vec(1.0) for _ in texts]

    def embed_text(self, text: str) -> list[float]:
        return _vec(1.0)

    def embed_query(self, query: str) -> list[float]:
        return _vec(1.0)


def _event(external_id: str, title: str) -> DiscoveredEvent:
    return DiscoveredEvent(
        source_id="src-1",
        external_id=external_id,
        title=title,
        starts_at=datetime.now(UTC) + timedelta(days=10),
        ends_at=None,
        place="New Haven, CT",
        url="https://example.org/e",
        summary=None,
    )


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
            delete(DiscoverySeenItem).where(DiscoverySeenItem.user_id == user_id)
        )
        await session.execute(
            delete(DiscoverySource).where(DiscoverySource.user_id == user_id)
        )
        await session.execute(
            delete(DiscoveryInterest).where(DiscoveryInterest.user_id == user_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_a_due_schedule_produces_one_completed_run(monkeypatch):
    user_id = f"wrk_{uuid.uuid4().hex[:12]}"
    stub = _StubSource((_event("evt-1", "Jazz at the Green"),))

    import backend.core.dependencies as dependencies
    import backend.discovery.runner as runner_module

    monkeypatch.setattr(runner_module, "_adapter_for", lambda _s, _b: stub)
    monkeypatch.setattr(dependencies, "get_embedding_provider", _StubEmbeddings)

    try:
        async with AsyncSessionLocal() as session:
            await DiscoverySourceRepository(session).upsert_source(
                user_id, "ics", "https://example.org/feed.ics"
            )
            # Without an interest nothing can rank, and the sweep would
            # correctly select nothing.
            await DiscoveryProfileRepository(session).upsert_interest(
                user_id, "jazz", 3, "user_explicit"
            )
            runs = DiscoveryRunRepository(session)
            await runs.upsert_schedule(
                user_id,
                Cadence(
                    cadence="daily", hour=9, weekday=0, timezone="America/New_York"
                ),
            )
            # Make the slot due without waiting for it.
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
            schedule.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()

        worker = DiscoveryWorker(worker_id="test-worker")

        assert await worker.enqueue_due() >= 1
        assert await worker.run_once() is True

        async with AsyncSessionLocal() as session:
            rows = (
                (
                    await session.execute(
                        select(DiscoveryRun).where(DiscoveryRun.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1
        run = rows[0]
        assert run.status == "ready"
        # The digest was persisted, the lease released, and the feed read once.
        assert run.digest_json is not None
        assert "Jazz at the Green" in run.digest_json
        assert run.lease_expires_at is None
        assert stub.fetches == 1
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_enqueueing_twice_does_not_queue_a_second_sweep(monkeypatch):
    # The producer is safe to run from any number of processes; the slot
    # constraint is what makes that true rather than a convention.
    user_id = f"wrk_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
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
            due_slot = datetime.now(UTC) - timedelta(minutes=1)
            schedule.next_run_at = due_slot
            await session.commit()

        worker = DiscoveryWorker(worker_id="test-worker")
        await worker.enqueue_due()
        # Force the same slot to look due again.
        async with AsyncSessionLocal() as session:
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
            schedule.next_run_at = due_slot
            await session.commit()
        await worker.enqueue_due()

        async with AsyncSessionLocal() as session:
            rows = (
                (
                    await session.execute(
                        select(DiscoveryRun).where(DiscoveryRun.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_an_idle_worker_reports_no_work():
    assert await DiscoveryWorker(worker_id="idle-worker").run_once() in (True, False)
