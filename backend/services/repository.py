import uuid
from typing import Any

from sqlalchemy import delete, func, select
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

    # Summarise every conversation this account owns, most recent first.
    #
    # The first query of a conversation stands in as its title: it is what the
    # person actually typed, so it is the thing they will recognise in a list.
    # Titles are stored sealed like the rest of the turn, so they are decrypted
    # through the model rather than read out of the column directly.
    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        # One row per conversation: its first turn (the title) and its last
        # (how recently it mattered).
        grouped = (
            select(
                Conversation.conversation_id.label("conversation_id"),
                func.min(Conversation.created_at).label("started_at"),
                func.max(Conversation.created_at).label("last_at"),
                func.count(Conversation.id).label("turns"),
            )
            .where(Conversation.user_id == user_id)
            .group_by(Conversation.conversation_id)
            .order_by(func.max(Conversation.created_at).desc())
            .limit(limit)
            .subquery()
        )
        rows = (await self.session.execute(select(grouped))).all()

        listed: list[dict[str, Any]] = []
        for row in rows:
            first = await self.session.scalar(
                select(Conversation)
                .where(
                    Conversation.conversation_id == row.conversation_id,
                    Conversation.user_id == user_id,
                )
                .order_by(Conversation.created_at.asc(), Conversation.id.asc())
                .limit(1)
            )
            listed.append(
                {
                    "conversation_id": str(row.conversation_id),
                    "title": (first.query if first is not None else "") or "",
                    "turns": int(row.turns),
                    "started_at": row.started_at.isoformat(),
                    "last_at": row.last_at.isoformat(),
                }
            )
        return listed

    # Remove one conversation this account owns, and report what went.
    #
    # Scoped by user as well as id: an id alone would let anyone who learns one
    # delete somebody else's conversation.
    async def delete_conversation(self, user_id: str, conversation_id: str) -> int:
        result = await self.session.execute(
            delete(Conversation).where(
                Conversation.conversation_id == uuid.UUID(conversation_id),
                Conversation.user_id == user_id,
            )
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

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
