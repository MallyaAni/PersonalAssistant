"""What the experience reviewer reads: a person's turns, and what was saved
from them.

A turn is read with everything the application recorded about it - the
words, the reply, the channel, the room, and the trace of what the turn had
in hand (which route ran, whether a picture was in view, whether a reminder
was firing, what memory was saved). The trace is what lets the review say
*why* something went wrong rather than only that it did: a person referring
to a picture while the turn's record shows none is a dropped attachment, not
a model that misread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.conversation import Conversation
from backend.models.memory import SemanticMemory

# How many turns one review reads at most; a person's busiest day is far
# below this and a runaway room should not cost the whole budget.
MAX_TURNS = 120
# The window around a turn's timestamp in which a memory written for that
# person is taken to have come from it. The turn's own row lands when the
# reply is done; the classifier runs inside the turn and writes its rows
# before that - two and a half minutes before, on a slow evening (the bird
# exchange, 2026-09-05: memories at 22:12, the turn's row at 22:14). So the
# window opens well before the turn and closes shortly after.
SAVED_WINDOW_BEFORE_SECONDS = 420
SAVED_WINDOW_AFTER_SECONDS = 180


@dataclass(frozen=True, slots=True)
class Turn:
    """One exchange as the reviewer sees it."""

    number: int
    id: str
    when: datetime | None
    owner: str  # the person, or the room's user id
    speaker: str  # who spoke, for a room; the person otherwise
    channel: str
    said: str
    replied: str
    addressed: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)

    # What the turn had in hand, compactly, for the judge and for the
    # cross-check: never the model's guess, always the record.
    def record(self) -> dict[str, Any]:
        trace = self.trace or {}
        return {
            "route": (trace.get("route") or {}).get("label", ""),
            "followup": trace.get("followup") or {},
            "picture_in_view": bool(trace.get("image_matches") or trace.get("active_image") or self.metadata.get("artifact_ids")),
            "reminder_firing": bool(self.metadata.get("scheduled_task")),
            "saved": list(trace.get("proposals_saved") or []),
            "steps": trace.get("steps") or {},
            "search": trace.get("search", ""),
        }


@dataclass(frozen=True, slots=True)
class Saved:
    """One memory row written near a turn."""

    id: str
    owner: str
    content: str
    purpose: str
    when: datetime | None


# The rooms a person belongs to, by their user ids; empty when the store
# cannot say. Read through the groups repository so the rule of membership
# is the one the worker uses.
async def rooms_of(session: AsyncSession, user_id: str) -> tuple[str, ...]:
    try:
        from backend.groups.repository import ConversationGroupRepository

        groups = await ConversationGroupRepository(session).groups_for_member(user_id)
        return tuple(group.user_id for group in groups)
    except Exception:
        return ()


# Every turn since `since` under the person and their rooms, oldest first,
# numbered. A room turn is kept whether or not this person spoke it: the
# room is the context the assistant answered in.
async def turns_since(session: AsyncSession, user_id: str, since: datetime, rooms: tuple[str, ...] = ()) -> list[Turn]:
    owners = [user_id, *rooms]
    rows = (
        await session.execute(
            select(Conversation)
            .where(Conversation.user_id.in_(owners), Conversation.created_at >= since.replace(tzinfo=None))
            .order_by(Conversation.created_at.asc())
            .limit(MAX_TURNS)
        )
    ).scalars().all()
    turns: list[Turn] = []
    for number, row in enumerate(rows, start=1):
        metadata = dict(row.extra_data or {})
        trace = metadata.get("trace") if isinstance(metadata.get("trace"), dict) else {}
        group = metadata.get("group") if isinstance(metadata.get("group"), dict) else {}
        speaker = str(group.get("speaker_user_id") or (user_id if row.user_id == user_id else ""))
        addressed = bool(group.get("addressed_by")) if group else bool(str(row.response or "").strip()) or not group
        turns.append(
            Turn(
                number=number,
                id=str(row.id),
                when=row.created_at,
                owner=str(row.user_id),
                speaker=speaker,
                channel=str(metadata.get("channel") or "web"),
                said=str(row.query or ""),
                replied=str(row.response or ""),
                addressed=addressed,
                metadata={k: v for k, v in metadata.items() if k != "trace"},
                trace=dict(trace),
            )
        )
    return turns


# The window in which a memory counts as saved from this turn, naive UTC as
# the columns are; None for a turn with no timestamp.
def saved_window(turn: Turn) -> tuple[datetime, datetime] | None:
    if turn.when is None:
        return None
    at = turn.when.replace(tzinfo=None)
    return at - timedelta(seconds=SAVED_WINDOW_BEFORE_SECONDS), at + timedelta(seconds=SAVED_WINDOW_AFTER_SECONDS)


# The semantic memories written for the person or their rooms in the window
# around a turn: what that turn taught the assistant.
async def saved_after(session: AsyncSession, turn: Turn, owners: tuple[str, ...]) -> list[Saved]:
    window = saved_window(turn)
    if window is None:
        return []
    start, end = window
    rows = (
        await session.execute(
            select(SemanticMemory)
            .where(
                SemanticMemory.user_id.in_(list(owners)),
                SemanticMemory.created_at >= start,
                SemanticMemory.created_at <= end,
            )
            .order_by(SemanticMemory.created_at.asc())
        )
    ).scalars().all()
    return [
        Saved(str(row.id), str(row.user_id), str(row.content or ""), str(row.purpose or ""), row.created_at)
        for row in rows
    ]


# The turns as the judge is shown them: numbered, dated, with the record.
def render_turns(turns: list[Turn]) -> str:
    lines: list[str] = []
    for turn in turns:
        when = turn.when.strftime("%a %d %b %H:%M") if turn.when else "?"
        who = turn.speaker or turn.owner
        room = f" in room {turn.owner}" if turn.owner != turn.speaker and turn.owner.startswith("group:") else ""
        addressed = "" if turn.addressed else " (not addressed to the assistant)"
        lines.append(f"[{turn.number}] {when} {who}{room}{addressed}")
        lines.append(f"  said: {' '.join(turn.said.split())[:600]}")
        if turn.replied.strip():
            lines.append(f"  reply: {' '.join(turn.replied.split())[:600]}")
        else:
            lines.append("  reply: (none)")
        lines.append(f"  record: {turn.record()}")
    return "\n".join(lines)
