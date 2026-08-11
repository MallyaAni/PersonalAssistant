"""Remember which bubble was which, and what came back.

The only positive signal Scout has. Everything else it knows is negative or
neutral: a dismissal says "I already know this", novelty says "you have seen
this", and not reacting says nothing at all. A tapback on a bubble says the one
thing none of those can — *that one*.

Two operations, and they are deliberately far apart in time. Delivery records
what it sent, one row per bubble, while it still knows which find each message
was about. Much later, a poller reads reactions off the Mac and writes them back
by GUID. Nothing joins them but Apple's message identifier, which is the only
thing both ends can see.

Recording is best-effort on purpose. A digest that failed to deliver because its
feedback row would not write is a bad trade, so every failure here is swallowed
by the caller and costs one bubble's opinion.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.discovery_feedback import DiscoverySentFind

# The two tapbacks that mean anything here. Messages has six; loved, laughed,
# emphasised and questioned are all ambiguous about whether someone wants more
# of something, and guessing at them would put noise into the only clean signal
# in the loop.
LIKED = "liked"
DISLIKED = "disliked"

# How far back the poller looks. A tapback arrives within minutes or not at all,
# and a week is long enough that a phone left face-down over a weekend still
# reports. Beyond it the row stays, unreacted, which is its own datum.
FEEDBACK_HORIZON_DAYS = 7


class SentFindRepository:
    """Persist what was sent, and the reactions that come back to it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Record one bubble. Returns nothing: the caller is delivering a digest and
    # must not care whether the bookkeeping worked.
    async def record_sent(
        self,
        user_id: str,
        item_digest: str | None,
        label: str | None,
        locality: str | None,
        message_guid: str | None,
        run_id: str | None = None,
        subscriber_id: str | uuid.UUID | None = None,
        body: str | None = None,
    ) -> None:
        # Without a GUID there is nothing a tapback could ever join to, so the
        # row would only ever be a record that something was sent. Kept anyway:
        # "sent and never reacted to" is exactly as informative as a reaction,
        # and only counts if the unreacted ones are also on file.
        self.session.add(
            DiscoverySentFind(
                user_id=user_id,
                run_id=uuid.UUID(run_id) if run_id else None,
                subscriber_id=_as_uuid(subscriber_id),
                item_digest=item_digest,
                label=label,
                locality=locality,
                message_guid=message_guid,
                body_prefix=body_prefix(body),
            )
        )
        await self.session.flush()

    # Which bubbles are still worth asking the Mac about, as (id, body) pairs.
    #
    # Keyed by row rather than by anything Apple assigned, because the identifier
    # is exactly what could not be relied on.
    async def awaiting_reaction(
        self, horizon_days: int = FEEDBACK_HORIZON_DAYS, limit: int = 200
    ) -> tuple[tuple[uuid.UUID, str], ...]:
        cutoff = datetime.now(UTC) - timedelta(days=horizon_days)
        rows = await self.session.execute(
            select(DiscoverySentFind.id, DiscoverySentFind.body_prefix)
            .where(
                DiscoverySentFind.body_prefix.is_not(None),
                DiscoverySentFind.reacted_at.is_(None),
                DiscoverySentFind.sent_at >= cutoff,
            )
            .order_by(DiscoverySentFind.sent_at.desc())
            .limit(limit)
        )
        return tuple((row_id, body) for row_id, body in rows.all() if body)

    # Write one reaction back against a bubble this recorded sending. Ignores a
    # row it does not know, which is what keeps a bridge — or a mistake in a
    # query on it — from inventing opinions about finds never offered.
    async def record_reaction(
        self, row_id: uuid.UUID | str, reaction: str, at: datetime | None = None
    ) -> bool:
        if reaction not in (LIKED, DISLIKED):
            return False
        row = await self.session.scalar(
            select(DiscoverySentFind).where(DiscoverySentFind.id == _as_uuid(row_id))
        )
        if row is None:
            return False
        row.reaction = reaction
        row.reacted_at = at or datetime.now(UTC)
        await self.session.flush()
        return True

    # Everything one user has reacted to, newest first. The read a ranking
    # change would train against, and the read the panel would show.
    async def reactions_for(
        self, user_id: str, limit: int = 200
    ) -> tuple[DiscoverySentFind, ...]:
        rows = await self.session.execute(
            select(DiscoverySentFind)
            .where(
                DiscoverySentFind.user_id == user_id,
                DiscoverySentFind.reaction.is_not(None),
            )
            .order_by(DiscoverySentFind.reacted_at.desc())
            .limit(limit)
        )
        return tuple(rows.scalars().all())


# How much of a bubble is enough to recognise it again.
#
# Long enough that two finds in one digest cannot collide, short enough to
# survive whatever Messages does to a body on the way in — recent macOS keeps
# most of them inside a binary blob, and only a contiguous run is reliably
# findable there. Whitespace is collapsed on both sides of the comparison
# because the stored text carries the newline before a link and the blob may
# not.
BODY_PREFIX_CHARS = 80


# The opening of a message, normalised for comparison.
def body_prefix(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.split())[:BODY_PREFIX_CHARS] or None


# A subscriber id as the column wants it, whatever the caller had.
#
# The delivery layer carries subscriber ids as strings, the column is a UUID, and
# an unparseable one records the bubble without an owner rather than losing the
# row: knowing a find was sent and not reacted to is worth keeping either way.
def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
