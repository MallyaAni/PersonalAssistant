import asyncio
import socket
import uuid
from contextlib import suppress
from typing import Any

from backend.config.settings import settings
from backend.core.dependencies import (
    get_background_presentation_service,
    get_discovery_channels,
)
from backend.core.logging_config import get_logger, setup_logging
from backend.database.session import AsyncSessionLocal
from backend.discovery.subscribers import enrolled_address
from backend.presentations.planner import DeckDraft
from backend.services.presentation_job_repository import (
    SQLAlchemyPresentationJobRepository,
)
from backend.services.presentation_repository import (
    SQLAlchemyPresentationRepository,
)
from backend.services.repository import SQLAlchemyConversationRepository

logger = get_logger(__name__)


# What the person is told when a deck reaches a terminal state. One sentence,
# used for both the conversation turn and the channel message, so the two
# records of the same event cannot drift apart.
def _result_sentence(status: str, title: str) -> str:
    if status == "ready":
        return f'Your presentation "{title}" is ready.'
    if status == "cancelled":
        return f'The presentation "{title}" was cancelled.'
    return f'I couldn\'t finish the presentation "{title}".'


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
            # A worker that died between recording a terminal state and
            # telling the conversation leaves notified_at null. The claim is
            # idempotent, so a job that was already told is left alone.
            if job["status"] in {"ready", "failed", "cancelled"}:
                await self._notify_terminal(job, str(job["status"]))
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
            await self._notify_terminal(job, "ready")
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
            await self._notify_terminal(job, "cancelled")
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
            await self._notify_terminal(job, "failed")
            logger.exception(
                "presentation_job_failed",
                extra={"job_id": str(job["id"])},
            )
        finally:
            stop_heartbeat.set()
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    # Tell the conversation that asked for the deck, and the channel it came
    # from, that the job is over. Never raises: a notification is a courtesy,
    # and a failure here must not turn a ready deck into a failed job.
    async def _notify_terminal(self, job: dict[str, Any], status: str) -> None:
        try:
            await self._write_and_send_result(job, status)
        except Exception:
            logger.warning(
                "presentation_job_notification_failed",
                extra={"job_id": str(job.get("id")), "status": status},
                exc_info=True,
            )

    async def _write_and_send_result(
        self, job: dict[str, Any], status: str
    ) -> None:
        async with AsyncSessionLocal() as session:
            jobs = SQLAlchemyPresentationJobRepository(session)
            # Claim before writing or sending: at-most-once is the whole
            # point, and the claim survives a crash after this line.
            if not await jobs.claim_notification(str(job["id"])):
                return
            presentation = await SQLAlchemyPresentationRepository(
                session
            ).get_owned(str(job["user_id"]), str(job["presentation_id"]))
            title = str((presentation or {}).get("title") or "your presentation")
            text = _result_sentence(status, title)
            conversation_id = (presentation or {}).get("conversation_id")
            if conversation_id:
                try:
                    await SQLAlchemyConversationRepository(session).save_turn(
                        str(conversation_id),
                        {
                            "user_id": str(job["user_id"]),
                            "query": "",
                            "response": text,
                            "metadata": {
                                "kind": "presentation_result",
                                "assistant_only": True,
                                "presentation_id": str(job["presentation_id"]),
                                "status": status,
                            },
                        },
                    )
                except Exception:
                    logger.warning(
                        "Could not write the deck result into its conversation",
                        exc_info=True,
                    )
                    with suppress(Exception):
                        await session.rollback()
            channel = str(job.get("channel") or "")
            if channel not in ("imessage", "imessage_group"):
                return
            address = await enrolled_address(str(job["user_id"]), channel)
            if not address:
                logger.info(
                    "presentation_job_notification_skipped",
                    extra={
                        "job_id": str(job["id"]),
                        "reason": f"no {channel} address enrolled",
                    },
                )
                return
            result = await get_discovery_channels()[channel].send(address, text)
            if getattr(result, "delivered", False):
                logger.info(
                    "presentation_job_notified",
                    extra={"job_id": str(job["id"]), "channel": channel},
                )
            else:
                logger.warning(
                    "presentation_job_notification_refused",
                    extra={
                        "job_id": str(job["id"]),
                        "channel": channel,
                        "error": str(getattr(result, "error_code", "") or "refused"),
                    },
                )

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
    # Same reason as the discovery worker: `setup_logging` lives in `main.py`,
    # which this process never imports, so without this every line it logs is
    # dropped by a root logger that has no handlers.
    setup_logging("DEBUG" if settings.DEBUG else "INFO")
    asyncio.run(run())


if __name__ == "__main__":
    main()
