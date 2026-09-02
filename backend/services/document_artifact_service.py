"""Write a document and keep it as an artifact, the way a picture is kept.

The conversation asks for a pending row first (so the web can show a
placeholder and a failure has something to mark), then the file is rendered
and stored under the row's opaque key. A PDF asked for while Gotenberg is
away comes back as a Word file, and the caller is told which it got.
"""
from __future__ import annotations

from typing import Any

from backend.core.interfaces import BinaryArtifactRepository, BinaryArtifactStore
from backend.services.document_writer import (
    DOCX,
    PDF,
    WriterUnavailable,
    WrittenDocument,
    needs_renderer,
    renderer_reachable,
    write_document,
)

KIND = "document"


class DocumentArtifactService:
    def __init__(self, repository: BinaryArtifactRepository, store: BinaryArtifactStore) -> None:
        self.repository = repository
        self.store = store

    # Persist a pending record before rendering starts.
    async def begin(self, user_id: str, conversation_id: str, trace_id: str, title: str, fmt: str) -> dict[str, Any]:
        return await self.repository.create_binary_pending(
            user_id,
            conversation_id,
            trace_id,
            KIND,
            "gotenberg" if fmt == PDF else "docx-builder",
            None,
            title[:160],
        )

    # Render, store, and mark the record ready. Returns the artifact and the
    # format actually written - a PDF falls back to Word when the renderer is
    # away, so the reply can say so.
    async def complete(
        self, artifact_id: str, user_id: str, title: str, markdown: str, fmt: str
    ) -> tuple[dict[str, Any], WrittenDocument]:
        chosen = fmt
        if needs_renderer(fmt) and not await renderer_reachable():
            chosen = DOCX
        try:
            written = await write_document(title, markdown, chosen)
        except WriterUnavailable:
            if chosen == DOCX:
                raise
            chosen = DOCX
            written = await write_document(title, markdown, chosen)
        stored = await self.store.write(user_id, artifact_id, written.extension, written.content)
        artifact = await self.repository.mark_binary_ready(
            artifact_id,
            user_id,
            stored,
            written.media_type,
            0,
            0,
            {"format": written.format, "title": title, "asked_format": fmt},
        )
        return artifact, written

    # Record a sanitized failure state for a pending document.
    async def fail(self, artifact_id: str, user_id: str, error_code: str = "write_failed") -> dict[str, Any]:
        return await self.repository.mark_failed(artifact_id, user_id, error_code)
