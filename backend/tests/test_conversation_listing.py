"""Reaching past conversations without the browser that made them.

History was only reachable through a conversation id the browser happened to
keep, so a second device, a new profile, or a cleared cache left every stored
conversation unreachable — present in the database and invisible to the person
who wrote it. The account owns its history, so the server lists it.
"""

import os
import uuid

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from sqlalchemy import delete

from backend.database.session import AsyncSessionLocal
from backend.models.conversation import Conversation
from backend.services.repository import SQLAlchemyConversationRepository


async def _cleanup(*user_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        for user_id in user_ids:
            await session.execute(
                delete(Conversation).where(Conversation.user_id == user_id)
            )
        await session.commit()


@pytest.mark.asyncio
async def test_history_is_listed_from_the_server_not_the_browser():
    owner = f"conv{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SQLAlchemyConversationRepository(session)
            older, newer = str(uuid.uuid4()), str(uuid.uuid4())
            await repo.save_turn(
                older,
                {"user_id": owner, "query": "Where should I hike?", "response": "a"},
            )
            await repo.save_turn(
                older, {"user_id": owner, "query": "follow up", "response": "b"}
            )
            await repo.save_turn(
                newer, {"user_id": owner, "query": "Plan my week", "response": "c"}
            )

            listed = await repo.list_conversations(owner)

        assert len(listed) == 2
        # The first thing they typed is what they will recognise, and it comes
        # back readable rather than as the sealed value in the column.
        titles = {row["title"] for row in listed}
        assert titles == {"Where should I hike?", "Plan my week"}
        assert {row["turns"] for row in listed} == {1, 2}
        # Most recently active first, so the list opens on what they were doing.
        assert listed[0]["title"] == "Plan my week"
    finally:
        await _cleanup(owner)


@pytest.mark.asyncio
async def test_one_account_never_sees_anothers_conversations():
    mine, theirs = f"conv{uuid.uuid4().hex[:8]}", f"conv{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SQLAlchemyConversationRepository(session)
            await repo.save_turn(
                str(uuid.uuid4()),
                {"user_id": mine, "query": "mine", "response": "a"},
            )
            await repo.save_turn(
                str(uuid.uuid4()),
                {"user_id": theirs, "query": "not yours", "response": "b"},
            )

            listed = await repo.list_conversations(mine)

        assert [row["title"] for row in listed] == ["mine"]
    finally:
        await _cleanup(mine, theirs)
