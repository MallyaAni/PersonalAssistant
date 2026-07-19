import os
import uuid

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal, SessionLocal
from backend.models.conversation import Conversation
from backend.services.repository import SQLAlchemyConversationRepository


@pytest.mark.asyncio
async def test_history_is_bounded_chronological_and_user_scoped():
    conversation_id = str(uuid.uuid4())
    user_id = f"history_{uuid.uuid4()}"
    other_user_id = f"history_{uuid.uuid4()}"

    try:
        async with AsyncSessionLocal() as session:
            repository = SQLAlchemyConversationRepository(session)
            await repository.save_turn(
                conversation_id,
                {"user_id": user_id, "query": "first", "response": "one"},
            )
            await repository.save_turn(
                conversation_id,
                {"user_id": other_user_id, "query": "private", "response": "secret"},
            )
            await repository.save_turn(
                conversation_id,
                {"user_id": user_id, "query": "second", "response": "two"},
            )
            await repository.save_turn(
                conversation_id,
                {"user_id": user_id, "query": "third", "response": "three"},
            )

            history = await repository.get_history(
                conversation_id,
                user_id,
                limit=2,
            )

            assert [(turn["query"], turn["response"]) for turn in history] == [
                ("second", "two"),
                ("third", "three"),
            ]
            assert await repository.count_turns(conversation_id, user_id) == 3
            assert await repository.count_turns(conversation_id, other_user_id) == 1
            assert (
                await repository.get_history(
                    conversation_id,
                    user_id,
                    limit=0,
                )
                == []
            )
    finally:
        with SessionLocal() as session:
            session.execute(
                delete(Conversation).where(
                    Conversation.conversation_id == uuid.UUID(conversation_id)
                )
            )
            session.commit()
