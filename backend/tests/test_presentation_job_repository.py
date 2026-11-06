"""A presentation job whose worker died after a cancel request is finalized
cancelled by the next claim, not left running forever.

`request_cancel` only sets the flag on a running job, and `claim_next`
excluded flagged rows, so a worker that died before `mark_cancelled` left the
job running with an expired lease that nobody could reclaim. Runs against the
real database; skipped where the tables are not migrated.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import ProgrammingError

from backend.models.presentation import Presentation, PresentationJob
from backend.services.presentation_job_repository import SQLAlchemyPresentationJobRepository

pytestmark = pytest.mark.asyncio


async def _session():
    from backend.database.session import AsyncSessionLocal
    return AsyncSessionLocal()


async def _require_tables() -> None:
    try:
        async with await _session() as session:
            await session.execute(text("select 1 from presentation_jobs limit 1"))
    except ProgrammingError:
        pytest.skip("presentation_jobs is not migrated in this database yet")
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")


async def _cleanup(user_id: str) -> None:
    async with await _session() as session:
        await session.execute(delete(Presentation).where(Presentation.user_id == user_id))
        await session.commit()


async def _job(job_id: str) -> PresentationJob:
    async with await _session() as session:
        return (
            await session.execute(
                select(PresentationJob).where(PresentationJob.id == uuid.UUID(job_id))
            )
        ).scalar_one()


async def test_a_cancelled_running_job_whose_worker_died_is_finalized():
    await _require_tables()
    user_id = f"deck-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            repository = SQLAlchemyPresentationJobRepository(session)
            queued = await repository.enqueue(
                user_id,
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "Make a deck",
                "test",
                None,
                3,
            )
            claimed = await repository.claim_next("worker-1", 60)
            assert claimed is not None and claimed["status"] == "running"

            assert await repository.request_cancel(user_id, queued["id"]) is True
            # The worker died before it could record the cancellation, and its
            # lease has run out.
            await session.execute(
                update(PresentationJob)
                .where(PresentationJob.id == uuid.UUID(queued["id"]))
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=5))
            )
            await session.commit()

            # The claim finishes the abandoned job and takes no new work.
            assert await repository.claim_next("worker-2", 60) is None

        row = await _job(queued["id"])
        assert row.status == "cancelled"
        assert row.error_code == "cancelled"
        assert row.worker_id is None and row.lease_expires_at is None
        assert row.completed_at is not None
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)


async def test_a_job_keeps_the_channel_it_was_queued_from():
    """The worker delivers the finished deck where the request came from; the
    channel has to survive the queue row to make that possible."""
    await _require_tables()
    user_id = f"deck-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            repository = SQLAlchemyPresentationJobRepository(session)
            queued = await repository.enqueue(
                user_id,
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "Make a deck",
                "test",
                None,
                3,
                "imessage",
            )
        assert queued["channel"] == "imessage"
        row = await _job(queued["id"])
        assert row.channel == "imessage" and row.notified_at is None
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)


async def test_a_terminal_job_can_be_notified_only_once():
    """The conditional update is the lock: a worker that dies after marking a
    deck ready and is retried later must not send the message again."""
    await _require_tables()
    user_id = f"deck-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            repository = SQLAlchemyPresentationJobRepository(session)
            queued = await repository.enqueue(
                user_id,
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "Make a deck",
                "test",
                None,
                3,
            )
            claimed = await repository.claim_next("worker-1", 60)
            assert claimed is not None
            await repository.mark_ready(queued["id"], "worker-1")

            assert await repository.claim_notification(queued["id"]) is True
            assert await repository.claim_notification(queued["id"]) is False

        row = await _job(queued["id"])
        assert row.notified_at is not None
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)
