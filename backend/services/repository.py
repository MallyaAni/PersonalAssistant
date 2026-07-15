from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select
from backend.core.interfaces import ConversationRepository
from backend.models.conversation import Conversation

class SQLAlchemyConversationRepository(ConversationRepository):
    def __init__(self, session: Session):
        self.session = session

    async def get_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        result = self.session.execute(stmt)
        db_records = result.scalars().all()
        return [rec.to_dict() for rec in db_records]

    async def save_turn(self, conversation_id: str, turn: Dict[str, Any]) -> None:
        # For now, we treat the last query/response as a single record per session 
        # unless we add more complex Turn logic later.
        new_conv = Conversation(
            user_id=turn["user_id"],
            query=turn["query"],
            response=turn["response"],
            metadata=turn.get("metadata", {})
        )
        self.session.add(new_conv)
        self.session.commit()