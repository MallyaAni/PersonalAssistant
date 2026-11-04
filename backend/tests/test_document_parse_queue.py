"""The durable parse queue: a document kept while the parser is away lands as
knowledge once the parser answers, a bad file is marked failed with the
parser's own sentence, and an unreachable parser stops the pass early.

Runs against the real database (rows are created and cleaned up); skipped
where it is unreachable.
"""
import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import ProgrammingError

from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.models.agent_memory import DocumentParseJob
from backend.models.artifact import VisualArtifact
from backend.services.artifact_repository import SQLAlchemyArtifactRepository
from backend.services.document_parse_queue import enqueue_document, process_pending
from backend.services.document_parser import ParsedDocument, ParseError, ParseUnavailable
from backend.services.document_writer import render_docx
from backend.tasks.repository import ScheduledTaskRepository

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

pytestmark = pytest.mark.asyncio


async def _up():
    return True


async def _down():
    return False


async def _session():
    from backend.database.session import AsyncSessionLocal
    return AsyncSessionLocal()


# The pre-deploy gate runs the unit suite against the live database BEFORE
# deploy.sh applies migrations, so on the deploy that ships this table the
# table does not exist yet. A skip there is the environment saying "not
# migrated here"; the post-deploy run proves the behaviour for real. Awaited
# at the top of each test rather than an async fixture, which pytest-asyncio
# does not await under this suite's configuration.
async def _require_table() -> None:
    try:
        async with await _session() as session:
            await session.execute(text("select 1 from document_parse_jobs limit 1"))
    except ProgrammingError:
        pytest.skip("document_parse_jobs is not migrated in this database yet")
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")


async def _cleanup(user_id: str) -> None:
    from backend.core.dependencies import get_agent_memory_manager, get_embedding_provider
    async with await _session() as session:
        rows = (await session.execute(select(DocumentParseJob).where(DocumentParseJob.user_id == user_id))).scalars().all()
        manager = get_agent_memory_manager(session, get_embedding_provider())
        for row in rows:
            if row.document_id:
                await manager.knowledge.delete(user_id, str(row.document_id))
        await session.execute(delete(DocumentParseJob).where(DocumentParseJob.user_id == user_id))
        # A queued Word file leaves an artifact row and its binary behind.
        await session.execute(delete(VisualArtifact).where(VisualArtifact.user_id == user_id))
        await session.commit()


async def _status(job_id: str) -> DocumentParseJob:
    async with await _session() as session:
        return (await session.execute(select(DocumentParseJob).where(DocumentParseJob.id == uuid.UUID(job_id)))).scalar_one()


async def test_a_queued_document_lands_when_the_parser_answers():
    await _require_table()
    user_id = f"queue-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            job = await enqueue_document(session, user_id, "notes.pdf", "application/pdf", b"%PDF-1.7 x", "", None)

        async def parser(filename, content):
            return ParsedDocument(markdown="The settling tank was cleaned each spring.", pages=1, media_type="application/pdf")

        landed = await process_pending(parse=parser, reachable=_up)
        assert landed >= 1
        row = await _status(job["id"])
        assert row.status == "done" and row.document_id is not None and row.content == b""
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)


async def test_an_unreadable_file_is_failed_with_the_parsers_sentence():
    await _require_table()
    user_id = f"queue-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            job = await enqueue_document(session, user_id, "bad.pdf", "application/pdf", b"%PDF-1.7 x", "", None)

        async def parser(filename, content):
            raise ParseError('I could not get any readable text out of "bad.pdf".')

        await process_pending(parse=parser, reachable=_up)
        row = await _status(job["id"])
        assert row.status == "failed" and "readable text" in (row.last_error or "")
        # A failed job is never read again, so its plaintext copy is dropped.
        assert row.content == b""
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)


async def test_an_absent_parser_leaves_every_job_untouched():
    await _require_table()
    user_id = f"queue-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            job = await enqueue_document(session, user_id, "later.pdf", "application/pdf", b"%PDF-1.7 x", "", None)

        async def parser(filename, content):
            raise AssertionError("must not parse while the parser is down")

        assert await process_pending(parse=parser, reachable=_down) == 0
        row = await _status(job["id"])
        assert row.status == "pending" and row.attempts == 0
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)


async def test_a_reachable_parser_that_keeps_failing_fails_the_job_after_three_tries():
    await _require_table()
    user_id = f"queue-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            job = await enqueue_document(session, user_id, "later.pdf", "application/pdf", b"%PDF-1.7 x", "", None)

        async def parser(filename, content):
            raise ParseUnavailable("The document parser is not reachable right now.")

        for _ in range(3):
            await process_pending(parse=parser, reachable=_up)
        row = await _status(job["id"])
        assert row.status == "failed" and row.attempts == 3 and "not reachable" in (row.last_error or "")
        assert row.content == b""
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)


async def test_a_queued_word_file_keeps_its_original_bytes(tmp_path, monkeypatch):
    """The queue clears the row's plaintext copy when the document lands, but
    the Word original is written from the bytes read before the clear. Reading
    them after the clear wrote an empty file, so "edit that file" later fell
    back to creating a new document."""
    await _require_table()
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "ARTIFACT_STORAGE_ROOT", str(tmp_path))
    user_id = f"queue-{uuid.uuid4().hex[:8]}"
    original = render_docx("Choral Tour", "# Choral Tour\n\n- Day 1: arrive")
    try:
        async with await _session() as session:
            job = await enqueue_document(session, user_id, "Choral Tour.docx", DOCX, original, "", None)

        async def parser(filename, content):
            assert content == original, "the parser must see the file, not an empty row"
            return ParsedDocument(markdown="# Choral Tour", pages=1, media_type=DOCX)

        landed = await process_pending(parse=parser, reachable=_up)
        assert landed >= 1
        row = await _status(job["id"])
        assert row.status == "done" and row.content == b"" and row.document_id is not None
        async with await _session() as session:
            artifact = await SQLAlchemyArtifactRepository(session).original_for_document(
                user_id, str(row.document_id)
            )
        assert artifact is not None
        assert artifact["metadata"]["original_of"] == str(row.document_id)
        content = await LocalBinaryArtifactStore(tmp_path).read(str(artifact["_storage_key"]))
        assert content == original
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)


async def test_one_unwritable_document_does_not_stop_the_pass(monkeypatch):
    """Ingest can fail for one file (a full disk, a transient database error).
    Before the guard that exception escaped the pass and the same oldest job
    was selected every tick, so nothing behind it ever landed."""
    await _require_table()
    import backend.services.document_parse_queue as queue

    class _UnwritableKnowledge:
        async def ingest(self, *args, **kwargs):
            raise RuntimeError("the knowledge store is unavailable")

    class _Manager:
        knowledge = _UnwritableKnowledge()

    monkeypatch.setattr(queue, "get_agent_memory_manager", lambda *args, **kwargs: _Manager())
    user_id = f"queue-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            first = await enqueue_document(session, user_id, "first.pdf", "application/pdf", b"%PDF-1.7 one", "", None)
            second = await enqueue_document(session, user_id, "second.pdf", "application/pdf", b"%PDF-1.7 two", "", None)

        async def parser(filename, content):
            return ParsedDocument(markdown="Readable text.", pages=1, media_type="application/pdf")

        assert await process_pending(parse=parser, reachable=_up) == 0
        # The second job was attempted in the same pass, so the first did not
        # block the queue behind it.
        assert (await _status(first["id"])).attempts == 1
        assert (await _status(second["id"])).attempts == 1

        for _ in range(2):
            await process_pending(parse=parser, reachable=_up)
        for job_id in (first["id"], second["id"]):
            row = await _status(job_id)
            assert row.status == "failed" and row.attempts == 3
            assert row.last_error == "the document could not be stored"
            assert row.content == b""
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)


async def test_a_failed_change_log_write_still_marks_the_document_done(monkeypatch):
    """The document is stored before the undo receipt is written. A connection
    drop between them must not make the queue ingest the same file again."""
    await _require_table()
    user_id = f"queue-{uuid.uuid4().hex[:8]}"
    try:
        async with await _session() as session:
            job = await enqueue_document(session, user_id, "notes.pdf", "application/pdf", b"%PDF-1.7 x", "", None)

        async def parser(filename, content):
            return ParsedDocument(markdown="The settling tank was cleaned each spring.", pages=1, media_type="application/pdf")

        async def unwritable(*args, **kwargs):
            raise RuntimeError("the change log is unavailable")

        monkeypatch.setattr(ScheduledTaskRepository, "record_change", unwritable)
        landed = await process_pending(parse=parser, reachable=_up)
        assert landed >= 1
        row = await _status(job["id"])
        assert row.status == "done" and row.document_id is not None and row.content == b""
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)
