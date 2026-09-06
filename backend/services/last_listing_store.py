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
from datetime import datetime, time

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
            "events": [_serialize(event) for event in events],
        }
    )
    try:
        await client.set(_KEY.format(user_id=user_id), payload, ex=_TTL_SECONDS)
    finally:
        if redis is None:
            await client.aclose()


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
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    events = payload.get("events") or []
    if not isinstance(events, list) or not events:
        return None
    return {
        "rendered": str(payload.get("rendered") or ""),
        "calendar_base_url": str(payload.get("calendar_base_url") or ""),
        "events": [
            _deserialize(record) for record in events if isinstance(record, dict)
        ],
    }
