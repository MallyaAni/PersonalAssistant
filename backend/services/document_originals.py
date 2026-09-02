"""Keep the Word file someone shared, so it can be edited in place later.

Reading a document keeps only its text (page-aware chunks in the knowledge
store). A Word file is also kept whole, as an artifact of kind `document`
whose metadata names the knowledge document it is the original of, so
"update the itinerary file" can rewrite that file with its own styles. A PDF
is not kept: it is a print, and nothing can edit it faithfully.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.core.interfaces import BinaryArtifactRepository, BinaryArtifactStore
from backend.services.document_editor import is_docx
from backend.services.document_writer import DOCUMENT_FORMATS, DOCX

logger = logging.getLogger(__name__)


# Store the shared Word file beside its knowledge document; returns the
# artifact, or None when the bytes are not a Word file or keeping it failed
# (the share itself never fails on this).
async def keep_original(
    repository: BinaryArtifactRepository,
    store: BinaryArtifactStore,
    user_id: str,
    conversation_id: str | None,
    trace_id: str | None,
    document_id: str,
    filename: str,
    content: bytes,
) -> dict[str, Any] | None:
    if not is_docx(content):
        return None
    try:
        pending = await repository.create_binary_pending(
            user_id,
            conversation_id or str(uuid.uuid4()),
            trace_id or str(uuid.uuid4()),
            "document",
            "upload",
            None,
            filename[:160],
        )
        stored = await store.write(user_id, str(pending["id"]), DOCX, content)
        return await repository.mark_binary_ready(
            str(pending["id"]),
            user_id,
            stored,
            DOCUMENT_FORMATS[DOCX],
            0,
            0,
            {"format": DOCX, "title": filename, "original_of": document_id, "original": True},
        )
    except Exception:
        logger.warning("Could not keep the Word original of %s", filename, exc_info=True)
        return None


# The kept Word file for a knowledge document: (artifact, bytes), or None.
async def original_bytes(
    repository: BinaryArtifactRepository, store: BinaryArtifactStore, user_id: str, document_id: str
) -> tuple[dict[str, Any], bytes] | None:
    artifact = await repository.original_for_document(user_id, document_id)
    if not artifact or not artifact.get("_storage_key"):
        return None
    content = await store.read(str(artifact["_storage_key"]))
    artifact.pop("_storage_key", None)
    return artifact, content
