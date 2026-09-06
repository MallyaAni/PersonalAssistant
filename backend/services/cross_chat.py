"""What a person just did in their rooms, for a direct message that continues it.

Live, 2026-09-04 and 2026-09-05: the person asked a group for a chess
picture, then wrote "try again" in their one-to-one chat. That chat's own
history said nothing about a picture, so the router read "try again" against
its last direct topic and searched for events. Twice. The follow-up
resolver and the router decide what the newest message refers to from the
recent history they are shown; this gives them the person's own recent room
turns beside the direct ones, each marked as having happened in a group
chat, so "try again" can be read as the retry it was. The model still
decides; nothing here says what the message means.

Only for a direct message, only rooms the person belongs to, only the last
`RECENT_ROOM_MINUTES`, and only for routing: the reply's history is the
conversation the reply is in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

# How far back a room turn may be and still count as what the person is
# continuing. A retry follows its request by minutes, not by an afternoon.
RECENT_ROOM_MINUTES = 45
# How many turns the router is shown after the merge.
ROUTING_HISTORY_TURNS = 12


# The person's rooms' turns in the window, oldest first, each marked with
# the room it happened in. Empty on any failure: routing then reads the
# direct history alone, as it did before this existed.
async def recent_room_turns(user_id: str, now: datetime | None = None) -> list[dict[str, Any]]:
    try:
        from sqlalchemy import select

        from backend.database.session import AsyncSessionLocal
        from backend.groups.repository import ConversationGroupRepository
        from backend.models.conversation import Conversation

        moment = now or datetime.now(UTC)
        since = (moment - timedelta(minutes=RECENT_ROOM_MINUTES)).replace(tzinfo=None)
        async with AsyncSessionLocal() as db:
            groups = await ConversationGroupRepository(db).groups_for_member(user_id)
            if not groups:
                return []
            names = {group.user_id: str(getattr(group, "display_name", "") or "") for group in groups}
            rows = (
                await db.execute(
                    select(Conversation)
                    .where(Conversation.user_id.in_(list(names)), Conversation.created_at >= since)
                    .order_by(Conversation.created_at.asc())
                )
            ).scalars().all()
        turns = []
        for row in rows:
            turn = row.to_dict()
            if not str(turn.get("query") or "").strip():
                continue
            metadata = dict(turn.get("metadata") or {})
            metadata["cross_chat"] = {"chat_name": names.get(str(row.user_id), "") or "the group chat"}
            turn["metadata"] = metadata
            turns.append(turn)
        return turns
    except Exception:
        return []


# The direct history with the room turns merged in by time, bounded to the
# most recent turns; the marker on each room turn says where it happened.
def merged_for_routing(history: list[dict[str, Any]], room_turns: list[dict[str, Any]], limit: int = ROUTING_HISTORY_TURNS) -> list[dict[str, Any]]:
    if not room_turns:
        return list(history)

    def when(turn: dict[str, Any]) -> str:
        return str(turn.get("created_at") or "")

    merged = sorted([*history, *room_turns], key=when)
    return merged[-limit:] if limit and len(merged) > limit else merged
