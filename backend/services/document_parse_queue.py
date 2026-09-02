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
"""
import asyncio
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select

from backend.config.settings import settings
from backend.core.dependencies import get_agent_memory_manager, get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.models.agent_memory import DocumentParseJob
from backend.services.document_parser import ParseError, ParseUnavailable, parse_document
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


# One pass over the pending jobs, oldest first. Returns how many landed.
async def process_pending(parse=parse_document, limit: int = 20, reachable=parser_reachable) -> int:
    landed = 0
    if not await reachable():
        return 0
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DocumentParseJob)
                .where(DocumentParseJob.status == "pending")
                .order_by(DocumentParseJob.created_at)
                .limit(limit)
            )
        ).scalars().all()
        if not rows:
            return 0
        manager = get_agent_memory_manager(session, get_embedding_provider())
        changes = ScheduledTaskRepository(session)
        for job in rows:
            job.attempts += 1
            job.updated_at = datetime.now(UTC)
            try:
                parsed = await parse(job.filename, job.content)
            except ParseUnavailable as exc:
                # The parser answered its health check moments ago, so this is
                # the file (a timeout on a huge scan, a crash mid-parse), not
                # an absent parser: a few tries, then it is failed with the
                # sentence the person can be told.
                job.last_error = str(exc)
                if job.attempts >= REACHABLE_ATTEMPTS:
                    job.status = "failed"
                await session.commit()
                continue
            except ParseError as exc:
                job.status = "failed"
                job.last_error = str(exc)
                await session.commit()
                continue
            body = parsed.markdown if not job.note.strip() else f"{job.note.strip()}\n\n{parsed.markdown}"
            stored = await manager.knowledge.ingest(
                job.user_id,
                job.filename,
                body,
                f"upload://{job.filename}",
                "uploaded_document",
                str(job.source_conversation_id) if job.source_conversation_id else None,
                None,
            )
            await changes.record_change(
                job.user_id,
                "memory",
                "save",
                None,
                {"kind": "knowledge_document", "id": stored["id"], "title": job.filename, "undoable": True},
                conversation_id=str(job.source_conversation_id) if job.source_conversation_id else None,
            )
            job.status = "done"
            job.document_id = uuid.UUID(stored["id"])
            job.last_error = None
            # The bytes did their job; keep the row as a record, not the file.
            job.content = b""
            await session.commit()
            landed += 1
            # The Word original is kept beside the landed document, as the
            # inline share keeps it (document_originals.py).
            try:
                from backend.artifacts.storage import LocalBinaryArtifactStore
                from backend.services.artifact_repository import SQLAlchemyArtifactRepository
                from backend.services.document_originals import keep_original

                await keep_original(
                    SQLAlchemyArtifactRepository(session), LocalBinaryArtifactStore(settings.ARTIFACT_STORAGE_ROOT),
                    job.user_id, str(job.source_conversation_id) if job.source_conversation_id else None, None,
                    stored["id"], job.filename, job.content,
                )
            except Exception:
                logger.warning("Could not keep the Word original from the queue", exc_info=True)
            logger.info("document_parse_queue_landed", extra={"user": job.user_id, "title": job.filename})
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
