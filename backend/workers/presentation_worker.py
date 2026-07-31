import asyncio
import socket
import uuid
from contextlib import suppress
from typing import Any

from backend.config.settings import settings
from backend.core.dependencies import (
    get_background_presentation_service,
)
from backend.core.logging_config import get_logger
from backend.database.session import AsyncSessionLocal
from backend.presentations.planner import DeckDraft
from backend.services.presentation_job_repository import (
    SQLAlchemyPresentationJobRepository,
)

logger = get_logger(__name__)


class PresentationJobCancelledError(RuntimeError):
    """Signals cooperative cancellation at a safe presentation checkpoint."""


class PresentationJobWorker:
    """Claim durable jobs and execute the focused presentation LangGraph."""

    # Give each worker process a stable lease identity.
    def __init__(self, worker_id: str | None = None) -> None:
        self.worker_id = worker_id or (
            f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"
        )

    # Claim and execute at most one job so the loop remains testable.
    async def run_once(self) -> bool:
        async with AsyncSessionLocal() as session:
            jobs = SQLAlchemyPresentationJobRepository(session)
            job = await jobs.claim_next(
                self.worker_id,
                settings.PRESENTATION_JOB_LEASE_SECONDS,
            )
        if job is None:
            return False
        if job["status"] != "running":
            logger.info(
                "presentation_job_reconciled",
                extra={"job_id": str(job["id"]), "status": str(job["status"])},
            )
            return True
        await self._execute(job)
        return True

    # Run one leased job while periodically extending its crash-recovery lease.
    async def _execute(self, job: dict[str, Any]) -> None:
        stop_heartbeat = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(str(job["id"]), stop_heartbeat))
        try:
            async with AsyncSessionLocal() as session:
                jobs = SQLAlchemyPresentationJobRepository(session)
                service = get_background_presentation_service(session)

                # Persist each graph draft and honor cancellation between slides.
                async def checkpoint(draft: DeckDraft) -> None:
                    saved = await jobs.save_draft(
                        str(job["id"]),
                        self.worker_id,
                        draft.specification,
                        draft.expected_slide_count,
                    )
                    if not saved:
                        raise PresentationJobCancelledError()

                await service.execute_pending_create(
                    str(job["user_id"]),
                    str(job["presentation_id"]),
                    str(job["revision_id"]),
                    str(job["prompt"]),
                    checkpoint,
                )
                await jobs.mark_ready(str(job["id"]), self.worker_id)
            logger.info(
                "presentation_job_ready",
                extra={
                    "job_id": str(job["id"]),
                    "presentation_id": str(job["presentation_id"]),
                },
            )
        except PresentationJobCancelledError:
            async with AsyncSessionLocal() as session:
                await SQLAlchemyPresentationJobRepository(session).mark_cancelled(
                    str(job["id"]),
                    self.worker_id,
                )
            logger.info(
                "presentation_job_cancelled",
                extra={"job_id": str(job["id"])},
            )
        except Exception:
            async with AsyncSessionLocal() as session:
                await SQLAlchemyPresentationJobRepository(session).mark_failed(
                    str(job["id"]),
                    self.worker_id,
                    "generation_failed",
                )
            logger.exception(
                "presentation_job_failed",
                extra={"job_id": str(job["id"])},
            )
        finally:
            stop_heartbeat.set()
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    # Renew the PostgreSQL lease until the job reaches a terminal state.
    async def _heartbeat(self, job_id: str, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=settings.PRESENTATION_JOB_HEARTBEAT_SECONDS,
                )
            except TimeoutError:
                async with AsyncSessionLocal() as session:
                    renewed = await SQLAlchemyPresentationJobRepository(
                        session
                    ).renew_lease(
                        job_id,
                        self.worker_id,
                        settings.PRESENTATION_JOB_LEASE_SECONDS,
                    )
                if not renewed:
                    return


# Poll for durable work without keeping a database transaction open while idle.
async def run() -> None:
    worker = PresentationJobWorker()
    logger.info(
        "presentation_worker_started",
        extra={"worker_id": worker.worker_id},
    )
    while True:
        handled = await worker.run_once()
        if not handled:
            await asyncio.sleep(settings.PRESENTATION_JOB_POLL_SECONDS)


# Start the presentation worker as a standalone Compose process.
def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
