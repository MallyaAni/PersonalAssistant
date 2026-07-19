import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.interfaces import ConversationRepository
from backend.models.conversation import Conversation


class SQLAlchemyConversationRepository(ConversationRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        stmt = (
            select(Conversation)
            .where(
                Conversation.conversation_id == uuid.UUID(conversation_id),
                Conversation.user_id == user_id,
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        db_records = list(reversed(result.scalars().all()))
        return [rec.to_dict() for rec in db_records]

    async def save_turn(self, conversation_id: str, turn: dict[str, Any]) -> None:
        new_conv = Conversation(
            conversation_id=uuid.UUID(conversation_id),
            user_id=turn["user_id"],
            query=turn["query"],
            response=turn["response"],
            extra_data=turn.get("metadata", {}),
        )
        self.session.add(new_conv)
        await self.session.commit()

    # Count persisted turns for a user-owned conversation.
    async def count_turns(self, conversation_id: str, user_id: str) -> int:
        return (
            await self.session.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.conversation_id == uuid.UUID(conversation_id),
                    Conversation.user_id == user_id,
                )
            )
            or 0
        )
