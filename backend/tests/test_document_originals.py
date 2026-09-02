"""A shared Word file is kept whole beside its knowledge document and can be
read back for an edit in place; a PDF is not kept; a repository that keeps no
originals answers None."""
import pytest

from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.services.document_originals import keep_original, original_bytes
from backend.services.document_writer import render_docx


class _Repository:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def create_binary_pending(self, user_id, conversation_id, trace_id, kind, provider, model, title, parent_artifact_id=None):
        row = {"id": f"art-{len(self.rows) + 1}", "kind": kind, "provider": provider, "title": title, "status": "pending", "user_id": user_id}
        self.rows[row["id"]] = row
        return row

    async def mark_binary_ready(self, artifact_id, user_id, stored, mime_type, width, height, metadata):
        row = self.rows[artifact_id]
        row.update({"status": "ready", "mime_type": mime_type, "metadata": metadata, "_storage_key": stored.storage_key, "byte_size": stored.byte_size})
        return dict(row)

    async def original_for_document(self, user_id, document_id):
        for row in self.rows.values():
            if row.get("status") == "ready" and row.get("metadata", {}).get("original_of") == document_id:
                return dict(row)
        return None


@pytest.mark.asyncio
async def test_a_word_file_is_kept_and_read_back(tmp_path):
    store = LocalBinaryArtifactStore(tmp_path)
    repository = _Repository()
    original = render_docx("Choral Tour", "# Choral Tour\n\n- Day 1: arrive")
    kept = await keep_original(repository, store, "ani", None, None, "doc-1", "Choral Tour.docx", original)  # type: ignore[arg-type]
    assert kept and kept["status"] == "ready" and kept["metadata"]["original_of"] == "doc-1" and kept["provider"] == "upload"
    found = await original_bytes(repository, store, "ani", "doc-1")  # type: ignore[arg-type]
    assert found is not None
    artifact, content = found
    assert content == original and "_storage_key" not in artifact and artifact["title"] == "Choral Tour.docx"


@pytest.mark.asyncio
async def test_a_pdf_is_not_kept_and_an_unknown_document_has_no_original(tmp_path):
    store = LocalBinaryArtifactStore(tmp_path)
    repository = _Repository()
    assert await keep_original(repository, store, "ani", None, None, "doc-2", "Itinerary.pdf", b"%PDF-1.4 print") is None  # type: ignore[arg-type]
    assert await original_bytes(repository, store, "ani", "doc-2") is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_repository_that_keeps_no_originals_answers_none():
    from backend.core.interfaces import OriginalDocumentRepository

    class Bare(OriginalDocumentRepository):
        pass

    assert await Bare().original_for_document("ani", "doc-1") is None
