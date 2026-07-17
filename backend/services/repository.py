import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.interfaces import ConversationRepository
from backend.models.conversation import Conversation


class SQLAlchemyConversationRepository(ConversationRepository):
    def __init__(self, session: Session):
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
        result = self.session.execute(stmt)
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
        self.session.commit()
