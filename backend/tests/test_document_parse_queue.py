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

from backend.models.agent_memory import DocumentParseJob
from backend.services.document_parse_queue import enqueue_document, process_pending
from backend.services.document_parser import ParsedDocument, ParseError, ParseUnavailable

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
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    finally:
        await _cleanup(user_id)
