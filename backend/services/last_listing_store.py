"""The last events listing, per user, so a later turn can act on it.

The listing a search produces is rendered once and then gone - the typed
events live in a per-turn ContextVar. When the person follows up with "send
me the links for the salsa night", the links have to be built from those same
typed records, not from whatever the model remembers of the words. This keeps
the latest listing, per user, long enough for the follow-up: 72 hours, or
until the next listing replaces it.

A Redis failure is a dead link request, not a dead turn: both callers catch
it and degrade to the prose path.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, time

from redis.asyncio import Redis

from backend.config.settings import settings
from backend.core.event_extraction import ListedEvent

_KEY = "anios:last_listing:{user_id}"
_TTL_SECONDS = 72 * 3600


def _client() -> Redis:
    # Created per call, the way the rest of the application reaches Redis;
    # a request happens at most once or twice a turn.
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


# The typed event as JSON, so the follow-up can rebuild it rather than parse
# the rendered words. Times are stored as ISO strings and read back exactly.
def _serialize(event: ListedEvent) -> dict:
    return {
        "name": event.name,
        "venue": event.venue,
        "area": event.area,
        "artist": event.artist,
        "what": event.what,
        "when_text": event.when_text,
        "recurring": event.recurring,
        "starts_at": event.starts_at.isoformat() if event.starts_at else None,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "price_text": event.price_text,
        "source_url": event.source_url,
        "source_title": event.source_title,
        "near": event.near,
    }


def _deserialize(record: dict) -> ListedEvent:
    values = dict(record)
    if values.get("starts_at"):
        values["starts_at"] = datetime.fromisoformat(values["starts_at"])
    else:
        values["starts_at"] = None
    if values.get("start_time"):
        values["start_time"] = time.fromisoformat(values["start_time"])
    else:
        values["start_time"] = None
    return ListedEvent(**values)


# Remember the listing just shown to this person. `rendered` is the words they
# saw, kept so the follow-up can resolve "that one" and "the second one"
# against what was actually in front of them.
async def save_last_listing(
    user_id: str,
    rendered: str,
    events: list[ListedEvent],
    calendar_base_url: str | None = None,
    redis: Redis | None = None,
) -> None:
    if not user_id or not events:
        return
    client = redis or _client()
    payload = json.dumps(
        {
            "rendered": rendered,
            "calendar_base_url": calendar_base_url or "",
            # When this listing was shown. A direct message can see several
            # listings - the person's own and each of their rooms' - and the
            # one they are most likely to mean is the newest.
            "saved_at": datetime.now(UTC).isoformat(),
            "events": [_serialize(event) for event in events],
        }
    )
    try:
        await client.set(_KEY.format(user_id=user_id), payload, ex=_TTL_SECONDS)
    finally:
        if redis is None:
            await client.aclose()


# One stored payload as the dict callers act on, or None when it is absent or
# unreadable. Corrupt records are treated as no listing rather than guessed at.
def _payload(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        stored = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(stored, dict):
        return None
    events = stored.get("events") or []
    if not isinstance(events, list) or not events:
        return None
    return {
        "rendered": str(stored.get("rendered") or ""),
        "calendar_base_url": str(stored.get("calendar_base_url") or ""),
        "saved_at": str(stored.get("saved_at") or "") or None,
        "events": [
            _deserialize(record) for record in events if isinstance(record, dict)
        ],
    }


# When a stored payload was shown, or the epoch for a payload written before
# `saved_at` existed: an undated listing must never beat a dated one.
def _saved_at(payload: dict) -> datetime:
    raw = str(payload.get("saved_at") or "")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# The most recent listing for this person, or None when there is none on
# record (never shown one, or the record aged out).
async def load_last_listing(
    user_id: str, redis: Redis | None = None
) -> dict | None:
    if not user_id:
        return None
    client = redis or _client()
    try:
        raw = await client.get(_KEY.format(user_id=user_id))
    finally:
        if redis is None:
            await client.aclose()
    return _payload(raw)


# The newest listing visible to a member: their own, or one shown in any room
# they belong to. A listing asked for in a group is the group account's, so
# without this a member's "send me the links" in a direct message could not
# find it. One MGET, not one round trip per room.
async def load_last_listing_for_member(
    member_user_id: str,
    group_user_ids: Iterable[str],
    redis: Redis | None = None,
) -> dict | None:
    if not member_user_id:
        return None
    keys = [_KEY.format(user_id=member_user_id)]
    keys.extend(
        _KEY.format(user_id=group)
        for group in group_user_ids
        if group and group != member_user_id
    )
    client = redis or _client()
    try:
        raws = await client.mget(keys)
    finally:
        if redis is None:
            await client.aclose()
    newest: dict | None = None
    newest_at: datetime | None = None
    for raw in raws:
        payload = _payload(raw)
        if payload is None:
            continue
        shown_at = _saved_at(payload)
        if newest is None or newest_at is None or shown_at > newest_at:
            newest, newest_at = payload, shown_at
    return newest
