"""Retention for document knowledge: a document whose last date is past by
more than the grace period is archived - kept, out of the default search,
still found when archived documents are asked for. Nothing is deleted.

Runs against the real database and the real embedder (rows are created and
cleaned up); skipped where the retention columns are not migrated yet - the
pre-deploy gate runs before deploy.sh applies migrations, and the post-deploy
run proves it for real.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

pytestmark = pytest.mark.asyncio


async def _session():
    from backend.database.session import AsyncSessionLocal

    return AsyncSessionLocal()


async def _require_columns() -> None:
    try:
        async with await _session() as session:
            await session.execute(text("select about_until, archived_at from knowledge_documents limit 1"))
    except ProgrammingError:
        pytest.skip("knowledge_documents retention columns are not migrated in this database yet")
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")


async def _manager(session):
    from backend.core.dependencies import get_agent_memory_manager, get_embedding_provider

    return get_agent_memory_manager(session, get_embedding_provider())


async def test_a_document_past_its_date_is_archived_and_leaves_the_default_search():
    await _require_columns()
    user_id = f"retention-{uuid.uuid4().hex[:8]}"
    async with await _session() as session:
        manager = await _manager(session)
        store = manager.knowledge
        old = await store.ingest(user_id, "Amalfi itinerary 2026", "Day 2: Pompeii excursion leaves at 8:30. We stay at the Grand Hotel of Salerno.", "upload://old.pdf", "uploaded_document")
        new = await store.ingest(user_id, "Lisbon itinerary 2027", "Day 1: arrive Lisbon, dinner in Alfama at 8pm. We stay at Hotel Avenida.", "upload://new.pdf", "uploaded_document")
        try:
            assert await store.set_about_until(user_id, old["id"], date(2026, 10, 15))
            assert await store.set_about_until(user_id, new["id"], date(2027, 5, 20))
            # Not yet: 20 days past a 30-day grace archives nothing.
            assert await store.archive_past(30, today=date(2026, 11, 4)) == 0
            # 40 days past: the old one goes, the future one stays.
            archived = await store.archive_past(30, today=date(2026, 11, 24))
            assert archived >= 1
            kept = await store.get(user_id, old["id"])
            assert kept and kept["status"] == "archived" and kept["archived_at"] and kept["about_until"] == "2026-10-15"
            assert (await store.get(user_id, new["id"]))["status"] == "active"
            # The default search reads active documents only.
            active = await store.search(user_id, "where do we stay?", 6)
            assert active and all(item["document"]["id"] == new["id"] for item in active), [i["document"]["title"] for i in active]
            # Asked for, the archived one is still there - nothing was deleted.
            past = await store.search(user_id, "which hotel in Salerno?", 6, statuses=("archived",))
            assert past and all(item["document"]["id"] == old["id"] for item in past)
            assert len(await store.get(user_id, old["id"])["chunks"]) >= 1
        finally:
            for doc in (old, new):
                await store.delete(user_id, doc["id"])


async def test_an_undated_document_never_archives():
    await _require_columns()
    user_id = f"retention-{uuid.uuid4().hex[:8]}"
    async with await _session() as session:
        store = (await _manager(session)).knowledge
        doc = await store.ingest(user_id, "Sourdough recipe", "Mix flour, water, starter and salt; bulk ferment five hours.", "upload://recipe.pdf", "uploaded_document")
        try:
            assert doc["about_until"] is None
            await store.archive_past(0, today=date(2030, 1, 1))
            assert (await store.get(user_id, doc["id"]))["status"] == "active"
        finally:
            await store.delete(user_id, doc["id"])
