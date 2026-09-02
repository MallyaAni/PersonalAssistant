"""Retire documents whose dates are past.

The digest step records the last date a document is about (an itinerary's
final day). A grace period after it, this pass marks the document archived:
kept, reachable when nothing current answers or when the person pinned it,
but no longer competing with this week's documents. Nothing is deleted on a
date; "forget that document" stays the person's own act. Dated facts saved
from the document carry their own expiry and leave through memory's purge.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from backend.config.settings import settings

logger = logging.getLogger(__name__)


# One pass over every user's documents; returns how many were archived.
async def archive_due_documents(grace_days: int | None = None) -> int:
    from backend.core.dependencies import get_agent_memory_manager, get_embedding_provider
    from backend.database.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        manager = get_agent_memory_manager(session, get_embedding_provider())
        archived = await manager.knowledge.archive_past(
            settings.KNOWLEDGE_ARCHIVE_GRACE_DAYS if grace_days is None else grace_days
        )
    if archived:
        logger.info("document_retention_archived", extra={"count": archived})
    return archived


# Run archive_due_documents for the app's lifetime, like the parse queue: a
# failed pass is logged and the next one still happens.
class DocumentArchiver:
    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def _loop(self) -> None:
        while True:
            try:
                await archive_due_documents()
            except Exception:
                logger.warning("Document retention pass failed", exc_info=True)
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None and self._interval > 0:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
