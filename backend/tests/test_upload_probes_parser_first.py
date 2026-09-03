"""An upload does not wait on a parser that is away.

While Docling's host is down a connection attempt hangs rather than being
refused, so handing the file straight to the parser made the sharer wait
about two minutes to hear "queued" (measured live 2026-09-02). The route now
asks the parser whether it is there first (an eight-second probe at worst)
and queues without ever calling it; plain text never involves the parser.

Runs against the real database (the queue row is created and cleaned up);
skipped where the queue table is not migrated.
"""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import ProgrammingError

from backend.core.auth import issue_user_token
from backend.main import app
from backend.models.agent_memory import DocumentParseJob

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_user_token(user_id)}"}


async def _table_present() -> bool:
    from backend.database.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("select 1 from document_parse_jobs limit 1"))
        return True
    except ProgrammingError:
        return False


async def _cleanup(user_id: str) -> None:
    from backend.database.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(delete(DocumentParseJob).where(DocumentParseJob.user_id == user_id))
        await session.commit()


def test_a_pdf_is_queued_in_one_probe_when_the_parser_is_away(monkeypatch):
    if not asyncio.run(_table_present()):
        pytest.skip("document_parse_jobs is not migrated in this database yet")
    import backend.services.document_parse_queue as queue
    import backend.services.document_parser as parser
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "DOCLING_BASE_URL", "http://parser.invalid:5001")

    async def away() -> bool:
        return False

    async def must_not_parse(filename: str, content: bytes):
        raise AssertionError("the parser was handed the file although the probe said it was away")

    monkeypatch.setattr(queue, "parser_reachable", away)
    monkeypatch.setattr(parser, "parse_document", must_not_parse)
    user_id = f"probe-first-{uuid.uuid4().hex[:8]}"
    try:
        with TestClient(app, headers=_bearer(user_id)) as client:
            response = client.post(
                f"/api/v1/memory/{user_id}/agent/knowledge/document",
                files={"document": ("Itinerary.pdf", PDF, "application/pdf")},
                data={"note": "", "source_conversation_id": str(uuid.uuid4())},
            )
        # The route answers 201 for a document it took in, queued or read.
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["queued"] is True and body["job_id"]
        assert "not reachable" in body["detail"]
    finally:
        asyncio.run(_cleanup(user_id))


def test_plain_text_is_read_without_asking_the_parser(monkeypatch):
    import backend.services.document_parse_queue as queue
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "DOCLING_BASE_URL", "http://parser.invalid:5001")

    async def never_asked() -> bool:
        raise AssertionError("a text file asked whether the parser was there")

    monkeypatch.setattr(queue, "parser_reachable", never_asked)
    user_id = f"probe-text-{uuid.uuid4().hex[:8]}"
    with TestClient(app, headers=_bearer(user_id)) as client:
        try:
            response = client.post(
                f"/api/v1/memory/{user_id}/agent/knowledge/document",
                files={"document": ("notes.txt", b"Day 1 evening: welcome dinner at the hotel.", "text/plain")},
                data={"note": "", "source_conversation_id": str(uuid.uuid4())},
            )
            assert response.status_code == 201, response.text
            assert response.json().get("queued") is not True
        finally:
            client.delete(f"/api/v1/memory/{user_id}/agent")


def test_an_upload_response_tells_the_client_to_reconnect(monkeypatch):
    # The facts pass runs after the response on the request's session and
    # holds the connection meanwhile; a client reusing it for its next request
    # saw it dropped (the live acceptance, 2026-09-02).
    import backend.services.document_parse_queue as queue
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "DOCLING_BASE_URL", "")
    user_id = f"reconnect-{uuid.uuid4().hex[:8]}"
    with TestClient(app, headers=_bearer(user_id)) as client:
        try:
            response = client.post(
                f"/api/v1/memory/{user_id}/agent/knowledge/document",
                files={"document": ("notes.txt", b"Day 1: welcome dinner.", "text/plain")},
                data={"note": "", "source_conversation_id": str(uuid.uuid4())},
            )
            assert response.status_code == 201, response.text
            assert response.headers.get("connection", "").lower() == "close"
        finally:
            client.delete(f"/api/v1/memory/{user_id}/agent")
