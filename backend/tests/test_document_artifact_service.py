"""A written document lands in the real artifact store: the service renders,
writes the bytes under the artifact's key with the extension the store must
admit, and marks the row ready with the format actually produced. The first
live "put that in a PDF" failed at exactly this seam ("Unsupported artifact
extension") after every unit around it had passed."""
import hashlib
from typing import Any

import pytest

from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.services.document_artifact_service import DocumentArtifactService

BODY = "# Saturday\n\n- 10:30 late breakfast\n- a walk by the water\n\nDinner at 7."


class _Repository:
    def __init__(self) -> None:
        self.pending: list[tuple] = []
        self.ready: list[dict[str, Any]] = []

    async def create_binary_pending(self, user_id, conversation_id, trace_id, kind, provider, model, title, parent_artifact_id=None):
        self.pending.append((kind, provider, title))
        return {"id": "11111111-1111-1111-1111-111111111111", "kind": kind, "status": "pending", "title": title}

    async def mark_binary_ready(self, artifact_id, user_id, stored, mime_type, width, height, metadata):
        row = {"id": artifact_id, "kind": "document", "status": "ready", "mime_type": mime_type,
               "byte_size": stored.byte_size, "sha256": stored.sha256, "metadata": metadata, "_storage_key": stored.storage_key}
        self.ready.append(row)
        return row

    async def mark_failed(self, artifact_id, user_id, error_code):
        return {"id": artifact_id, "status": "failed", "error_code": error_code}


@pytest.mark.asyncio
async def test_a_word_file_is_stored_under_the_artifact_key_and_marked_ready(tmp_path):
    store = LocalBinaryArtifactStore(tmp_path)
    repository = _Repository()
    service = DocumentArtifactService(repository, store)  # type: ignore[arg-type]

    pending = await service.begin("ani", "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333", "Saturday plan", "docx")
    artifact, written = await service.complete(pending["id"], "ani", "Saturday plan", BODY, "docx")

    assert repository.pending == [("document", "docx-builder", "Saturday plan")]
    assert written.format == "docx" and artifact["mime_type"].endswith("wordprocessingml.document")
    content = await store.read(artifact["_storage_key"])
    assert content == written.content and content.startswith(b"PK\x03\x04")
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    assert artifact["metadata"] == {"format": "docx", "title": "Saturday plan", "asked_format": "docx"}


@pytest.mark.asyncio
async def test_a_pdf_asked_for_without_a_renderer_is_stored_as_word_and_says_so(monkeypatch, tmp_path):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "GOTENBERG_BASE_URL", "")
    store = LocalBinaryArtifactStore(tmp_path)
    repository = _Repository()
    service = DocumentArtifactService(repository, store)  # type: ignore[arg-type]

    pending = await service.begin("ani", "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333", "Saturday plan", "pdf")
    artifact, written = await service.complete(pending["id"], "ani", "Saturday plan", BODY, "pdf")

    assert repository.pending[0][1] == "gotenberg"
    assert written.format == "docx", "the Word file stands in when the renderer is away"
    assert artifact["metadata"]["asked_format"] == "pdf" and artifact["metadata"]["format"] == "docx"
    assert (await store.read(artifact["_storage_key"])).startswith(b"PK\x03\x04")
