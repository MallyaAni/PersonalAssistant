"""A group knows its members' non-sensitive memory automatically - by
relevance, not only recency - and starts its Scout from what they share.

Against the real database, memory service (real embeddings) and routing
model. The operator's stated use (2026-08-28): schedules on common interests
and shared cooking recipes, without anyone having to "refresh" anything.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, text

from backend.core import dependencies as d
from backend.database.session import AsyncSessionLocal
from backend.discovery.repository import DiscoveryProfileRepository
from backend.groups.repository import ConversationGroupRepository
from backend.groups.shared_interests import SHARED_PROVENANCE, refresh_shared_interests
from backend.memory.share_screen import forget_verdicts
from backend.memory.tastes import TasteProjection
from backend.models.auth import UserAccount
from backend.services.auth_service import AuthService
from backend.tests.test_conversation_groups import _chat
from backend.tests.test_conversation_groups import _cleanup as _cleanup_group

pytestmark = pytest.mark.asyncio


async def _account(user_id: str, name: str) -> None:
    async with AsyncSessionLocal() as db:
        await AuthService(db).create_account_with_hash(user_id=user_id, username=user_id, password_hash="$2b$12$" + "x" * 53)
        await db.commit()
        from backend.memory.repository import MemoryRepository

        await MemoryRepository(db).upsert_user_profile(user_id, name, {})
        await db.commit()


async def _remove(*user_ids: str) -> None:
    async with AsyncSessionLocal() as db:
        for uid in user_ids:
            for table in ("semantic_memory", "discovery_interests", "discovery_localities", "user_profiles", "user_sessions"):
                try:
                    await db.execute(text(f"delete from {table} where user_id = :u"), {"u": uid})
                except Exception:
                    await db.rollback()
            await db.execute(delete(UserAccount).where(UserAccount.user_id == uid))
        await db.commit()


async def test_a_recipe_told_long_ago_is_found_for_a_recipe_question(structured_llm):
    uid = f"gm_{uuid.uuid4().hex[:8]}"
    await _account(uid, "Jen")
    forget_verdicts()
    try:
        async with AsyncSessionLocal() as db:
            memory = d.get_memory_service(db, d.get_embedding_provider())
            # The recipe first, then nine unrelated everyday things: it is the
            # oldest memory, past the "recent 8" window on its own.
            await memory.save_semantic_memory(uid, "My chili recipe: two chipotles, a spoon of cumin, and a bottle of dark beer, simmered two hours.", {"source": "test"})
            for filler in (
                "I drive a red Mini Cooper", "My dog is called Biscuit", "I prefer window seats on planes",
                "I usually run on Sunday mornings", "My favourite colour is green", "I take my coffee black",
                "I like board games on rainy days", "I keep a small herb garden", "I read mostly non-fiction",
            ):
                await memory.save_semantic_memory(uid, filler, {"source": "test"})
            projection = TasteProjection(memory, d.get_discovery_profile_service(db), structured_llm)
            (taste,) = await projection.for_members((uid,), query="Scout, what was Jen's chili recipe again?")
        assert any("chipotle" in fact.casefold() for fact in taste.facts), taste.facts
        assert taste.name == "Jen"
    finally:
        forget_verdicts()
        await _remove(uid)


async def test_interests_two_members_share_seed_the_groups_scout():
    a, b = f"gm_{uuid.uuid4().hex[:8]}", f"gm_{uuid.uuid4().hex[:8]}"
    chat = _chat()
    await _account(a, "Ani")
    await _account(b, "Jen")
    try:
        async with AsyncSessionLocal() as db:
            repo = DiscoveryProfileRepository(db)
            await repo.upsert_interest(a, "Thai food", 3, "user_explicit")
            await repo.upsert_interest(a, "hiking", 2, "user_explicit")
            await repo.upsert_interest(b, "thai food", 2, "user_explicit")
            await repo.upsert_interest(b, "horses", 3, "user_explicit")
            await db.commit()
            group = await ConversationGroupRepository(db).provision(chat, "Crew", (a, b))
            shared = await refresh_shared_interests(db, group.user_id, (a, b))
            assert [s.casefold() for s in shared] == ["thai food"]
            profile = await repo.get_profile(group.user_id)
            mine = [(i.label.casefold(), i.provenance) for i in profile.interests]
            assert ("thai food", SHARED_PROVENANCE) in mine and len(mine) == 1
            # Jen drops thai food: the group's copy goes with it.
            jen = await repo.get_profile(b)
            for interest in jen.interests:
                if interest.label.casefold() == "thai food":
                    await repo.delete_interest(b, interest.id)
            await db.commit()
            assert await refresh_shared_interests(db, group.user_id, (a, b)) == ()
            assert [i.label for i in (await repo.get_profile(group.user_id)).interests] == []
    finally:
        await _cleanup_group(chat)
        await _remove(a, b)
