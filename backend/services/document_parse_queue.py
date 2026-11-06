"""Parse documents that arrived while the parser was away.

Docling runs where a GPU is - the desktop, which is not always on. When an
upload finds it unreachable, the route keeps the document here instead of
refusing it, and this loop finishes the job when the parser is back: parse,
store as knowledge, record the change so "forget that" still works. The
person was told at upload time that it would be read shortly; from the next
turn after it lands, the reply answers from it.

Two failures are told apart. ParseUnavailable keeps the job pending and counts
an attempt; any other ParseError is the file itself and marks the job failed
with the parser's own sentence, so nothing retries forever.

A claim and a lease keep two processes running this loop from reading the same
file twice, and every terminal job leaves one line in the conversation that
uploaded it, so a queued file cannot fail silently.
"""
import asyncio
import logging
import os
import socket
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from backend.config.settings import settings
from backend.core.dependencies import get_agent_memory_manager, get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.models.agent_memory import DocumentParseJob
from backend.services.document_parser import ParseError, ParseUnavailable, parse_document
from backend.services.repository import SQLAlchemyConversationRepository
from backend.tasks.repository import ScheduledTaskRepository

logger = logging.getLogger(__name__)


# Keep one document for later. Called by the ingest route when the parser is
# unavailable; the row holds everything needed to finish without the caller.
async def enqueue_document(
    session,
    user_id: str,
    filename: str,
    media_type: str,
    content: bytes,
    note: str,
    source_conversation_id: str | None,
) -> dict:
    job = DocumentParseJob(
        user_id=user_id,
        filename=filename,
        media_type=media_type,
        content=content,
        note=note or "",
        source_conversation_id=uuid.UUID(source_conversation_id) if source_conversation_id else None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job.to_dict()


# One job's status, scoped to the person who uploaded it. The route turns a
# missing row into a 404, and a malformed id is simply not a job.
async def get_owned(session, user_id: str, job_id: str) -> dict | None:
    try:
        identifier = uuid.UUID(job_id)
    except ValueError:
        return None
    job = await session.scalar(
        select(DocumentParseJob).where(
            DocumentParseJob.id == identifier,
            DocumentParseJob.user_id == user_id,
        )
    )
    return job.to_dict() if job is not None else None


# Whether the parser answers at all. A pass that finds it down does not
# count against any job: an overnight desktop must not burn attempts.
async def parser_reachable() -> bool:
    base = settings.DOCLING_BASE_URL.rstrip("/")
    if not base:
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8) as client:
            return (await client.get(f"{base}/health")).status_code == 200
    except Exception:
        return False


# How many failed attempts a job gets while the parser IS reachable: a
# timeout or an error on a reachable parser is about the file, and three
# tries is enough to know.
REACHABLE_ATTEMPTS = 3

# How long a claimed job stays owned before another process may take it.
# There is no heartbeat here - the parse itself is the long part, and a large
# scan can take minutes. Long enough that a slow but healthy parse is never
# stolen, short enough that a crashed worker's file is read the same hour.
PARSE_LEASE_SECONDS = 30 * 60


# Enough to tell two processes apart while a row is held. The hostname
# matters when the desktop and the server both run a queue.
def _worker_id() -> str:
    return f"parse-{socket.gethostname()}-{os.getpid()}"[:200]


# Take the oldest job nobody else is reading, or whose reader's lease has
# expired. skip_locked is what makes the claim exclusive: a second process
# walks past a row this one is holding instead of waiting on it. `exclude`
# keeps one pass from retrying a job it just put back for the parser's
# absence, which would spend all three attempts in a single tick.
async def claim_next(
    session,
    worker_id: str,
    lease_seconds: float = PARSE_LEASE_SECONDS,
    exclude: set[uuid.UUID] | None = None,
) -> DocumentParseJob | None:
    now = datetime.now(UTC)
    query = select(DocumentParseJob).where(
        or_(
            DocumentParseJob.status == "pending",
            # A row left processing with no lease is orphaned by definition;
            # one with an expired lease belonged to a worker that is gone.
            (DocumentParseJob.status == "processing")
            & (
                (DocumentParseJob.lease_expires_at < now)
                | DocumentParseJob.lease_expires_at.is_(None)
            ),
        )
    )
    if exclude:
        query = query.where(DocumentParseJob.id.not_in(exclude))
    job = await session.scalar(
        query.order_by(DocumentParseJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        await session.rollback()
        return None
    job.status = "processing"
    job.worker_id = worker_id
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.updated_at = now
    await session.commit()
    await session.refresh(job)
    return job


# Tell the conversation that asked for the document how it ended. One turn,
# written only when the upload named a conversation. Never raises into the
# queue: the file is already stored or already failed, and a conversation
# write must not stop the next job.
async def _record_result(
    session,
    *,
    user_id: str,
    conversation_id: uuid.UUID | None,
    filename: str,
    job_id: uuid.UUID,
    status: str,
    response: str,
) -> None:
    if conversation_id is None:
        return
    try:
        await SQLAlchemyConversationRepository(session).save_turn(
            str(conversation_id),
            {
                "user_id": user_id,
                "query": f"📎 {filename}",
                "response": response,
                "metadata": {
                    "kind": "document_parse_result",
                    "job_id": str(job_id),
                    "status": status,
                },
            },
        )
    except Exception:
        logger.warning("Could not record the queued document result", exc_info=True)
        with suppress(Exception):
            await session.rollback()


# One pass over the queue, oldest first, one claimed job at a time. Returns
# how many landed.
async def process_pending(parse=parse_document, limit: int = 20, reachable=parser_reachable) -> int:
    landed = 0
    if not await reachable():
        return 0
    async with AsyncSessionLocal() as session:
        manager = get_agent_memory_manager(session, get_embedding_provider())
        changes = ScheduledTaskRepository(session)
        worker_id = _worker_id()
        # A job put back because the parser went away must not be claimed
        # again in this same pass.
        attempted: set[uuid.UUID] = set()
        while len(attempted) < limit:
            claimed = await claim_next(session, worker_id, exclude=attempted)
            if claimed is None:
                break
            job_id = claimed.id
            attempted.add(job_id)
            # A failure path rolls the session back, which expires every loaded
            # row. Reload by id so the next step never touches an expired
            # attribute.
            job = await session.get(DocumentParseJob, job_id)
            if job is None:
                continue
            # Held as locals so a rollback later in this job cannot expire
            # what the result line and the original's metadata need.
            user_id = job.user_id
            filename = job.filename
            conversation_id = job.source_conversation_id
            job.attempts += 1
            job.updated_at = datetime.now(UTC)
            # Hold the bytes in a local before the row's copy is cleared: the
            # Word original is written from them after the document lands.
            content = job.content
            try:
                parsed = await parse(job.filename, content)
            except ParseUnavailable as exc:
                # The parser answered its health check moments ago, so this is
                # the file (a timeout on a huge scan, a crash mid-parse), not
                # an absent parser: a few tries, then it is failed with the
                # sentence the person can be told.
                job.last_error = str(exc)
                job.worker_id = None
                job.lease_expires_at = None
                if job.attempts >= REACHABLE_ATTEMPTS:
                    job.status = "failed"
                    # A failed job will never read these bytes again.
                    job.content = b""
                else:
                    # Back in the queue for the next tick, not this one.
                    job.status = "pending"
                await session.commit()
                if job.status == "failed":
                    await _record_result(
                        session,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        filename=filename,
                        job_id=job_id,
                        status="failed",
                        response=f'I couldn\'t read "{filename}": {job.last_error}',
                    )
                continue
            except ParseError as exc:
                job.status = "failed"
                job.last_error = str(exc)
                job.content = b""
                job.worker_id = None
                job.lease_expires_at = None
                await session.commit()
                await _record_result(
                    session,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    filename=filename,
                    job_id=job_id,
                    status="failed",
                    response=f'I couldn\'t read "{filename}": {job.last_error}',
                )
                continue
            except Exception:
                # An unexpected parser failure is about this file too; count
                # it like the others so one job cannot block the queue.
                logger.warning("Queued document parse failed unexpectedly", exc_info=True)
                job.last_error = "the document could not be read"
                job.worker_id = None
                job.lease_expires_at = None
                if job.attempts >= REACHABLE_ATTEMPTS:
                    job.status = "failed"
                    job.content = b""
                else:
                    job.status = "pending"
                await session.commit()
                if job.status == "failed":
                    await _record_result(
                        session,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        filename=filename,
                        job_id=job_id,
                        status="failed",
                        response=f'I couldn\'t read "{filename}": {job.last_error}',
                    )
                continue
            body = parsed.markdown if not job.note.strip() else f"{job.note.strip()}\n\n{parsed.markdown}"
            try:
                stored = await manager.knowledge.ingest(
                    job.user_id,
                    job.filename,
                    body,
                    f"upload://{job.filename}",
                    "uploaded_document",
                    str(job.source_conversation_id) if job.source_conversation_id else None,
                    None,
                )
            except Exception:
                # The file parsed but could not be stored. Roll back whatever
                # the failed ingest left uncommitted, then count the attempt
                # on a clean session: the queue must not stop at this job.
                logger.warning("Could not store queued document %s", job.filename, exc_info=True)
                await session.rollback()
                job = await session.get(DocumentParseJob, job_id)
                if job is None:
                    continue
                job.attempts += 1
                job.updated_at = datetime.now(UTC)
                job.last_error = "the document could not be stored"
                job.worker_id = None
                job.lease_expires_at = None
                if job.attempts >= REACHABLE_ATTEMPTS:
                    job.status = "failed"
                    job.content = b""
                else:
                    job.status = "pending"
                await session.commit()
                if job.status == "failed":
                    await _record_result(
                        session,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        filename=filename,
                        job_id=job_id,
                        status="failed",
                        response=f'I couldn\'t read "{filename}": {job.last_error}',
                    )
                continue
            try:
                await changes.record_change(
                    job.user_id,
                    "memory",
                    "save",
                    None,
                    {"kind": "knowledge_document", "id": stored["id"], "title": job.filename, "undoable": True},
                    conversation_id=str(job.source_conversation_id) if job.source_conversation_id else None,
                )
            except Exception:
                # The document is stored; a missing undo receipt must not make
                # the queue ingest it again on the next pass.
                logger.warning("Could not record the queued document change", exc_info=True)
                await session.rollback()
                job = await session.get(DocumentParseJob, job_id)
                if job is None:
                    continue
            job.status = "done"
            job.document_id = uuid.UUID(stored["id"])
            job.last_error = None
            # The bytes did their job; keep the row as a record, not the file.
            job.content = b""
            job.worker_id = None
            job.lease_expires_at = None
            await session.commit()
            landed += 1
            # The Word original is kept beside the landed document, as the
            # inline share keeps it (document_originals.py). The bytes are the
            # copy read before the row was cleared.
            try:
                from backend.artifacts.storage import LocalBinaryArtifactStore
                from backend.services.artifact_repository import SQLAlchemyArtifactRepository
                from backend.services.document_originals import keep_original

                await keep_original(
                    SQLAlchemyArtifactRepository(session), LocalBinaryArtifactStore(settings.ARTIFACT_STORAGE_ROOT),
                    user_id, str(conversation_id) if conversation_id else None, None,
                    stored["id"], filename, content,
                )
            except Exception:
                logger.warning("Could not keep the Word original from the queue", exc_info=True)
            await _record_result(
                session,
                user_id=user_id,
                conversation_id=conversation_id,
                filename=filename,
                job_id=job_id,
                status="done",
                response=f'I\'ve read "{filename}" — you can ask me about it now.',
            )
            logger.info("document_parse_queue_landed", extra={"user": user_id, "title": filename})
    return landed


# Run process_pending for the app's lifetime, like the image-embedding
# reconciler: a failed pass is logged and the next one still happens.
class DocumentParseQueue:
    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def _loop(self) -> None:
        while True:
            try:
                await process_pending()
            except Exception:
                logger.warning("Document parse queue pass failed", exc_info=True)
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None and self._interval > 0 and settings.DOCLING_BASE_URL:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
