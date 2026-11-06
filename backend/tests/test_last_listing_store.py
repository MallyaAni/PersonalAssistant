"""The last listing survives the turn that rendered it, as typed records.

The follow-up that sends links resolves "the salsa night" against this store;
if the typed records were not here, the links would have to be rebuilt from
whatever the model remembered of the words - the failure the fence exists to
stop. So the test is a round-trip: what is saved is exactly what comes back,
in the fields the link builder needs.
"""

import json
from datetime import UTC, datetime, time

import pytest

from backend.core.event_extraction import ListedEvent
from backend.services.last_listing_store import (
    load_last_listing,
    load_last_listing_for_member,
    save_last_listing,
)

pytestmark = pytest.mark.asyncio

EVENT = ListedEvent(
    name="Sunday Sessions", venue="The Lawn", area="Batu Bolong", artist="DJ Dea",
    what="Deep house on the grass.", when_text="every Sunday from 4pm", recurring=True,
    starts_at=datetime(2026, 8, 30, 16, 0, tzinfo=UTC), start_time=time(16, 0),
    price_text="free before 6pm", source_url="https://www.thelawncanggu.com/whats-on",
    source_title="The Lawn",
)

RENDERED = "Tomorrow, Sun 30 Aug\n\n• Sunday Sessions\n  The Lawn, Batu Bolong"


class FakeRedis:
    """The tiny slice of Redis the store uses, with a captured key and TTL."""

    def __init__(self):
        self.data = {}
        self.keys = []

    async def set(self, key, value, ex=None):
        self.data[key] = value
        self.keys.append((key, ex))

    async def get(self, key):
        return self.data.get(key)

    async def mget(self, keys):
        return [self.data.get(key) for key in keys]

    async def aclose(self):
        self.closed = True


# Save one listing, then stamp when it was shown, so "newest" is decided by
# the test rather than by how fast two saves ran.
async def _save_at(redis, user_id, rendered, saved_at):
    await save_last_listing(user_id, rendered, [EVENT], redis=redis)
    key = f"anios:last_listing:{user_id}"
    payload = json.loads(redis.data[key])
    if saved_at is None:
        payload.pop("saved_at", None)
    else:
        payload["saved_at"] = saved_at
    redis.data[key] = json.dumps(payload)


async def test_saved_records_come_back_with_every_field():
    redis = FakeRedis()
    await save_last_listing(
        "u-1", RENDERED, [EVENT],
        calendar_base_url="https://deep-matter.com/api/v1/discovery",
        redis=redis,
    )
    assert redis.keys == [("anios:last_listing:u-1", 72 * 3600)]
    store = await load_last_listing("u-1", redis=redis)
    assert store is not None
    assert store["rendered"] == RENDERED
    assert store["calendar_base_url"] == "https://deep-matter.com/api/v1/discovery"
    # The moment it was shown, so a direct message can tell this listing from
    # one a room showed later.
    assert datetime.fromisoformat(store["saved_at"]).tzinfo is not None
    back = store["events"][0]
    assert back.name == "Sunday Sessions"
    assert back.venue == "The Lawn"
    assert back.starts_at == EVENT.starts_at
    assert back.start_time == EVENT.start_time
    assert back.source_url == EVENT.source_url
    assert back.near is True


async def test_no_listing_on_record_is_none():
    redis = FakeRedis()
    assert await load_last_listing("nobody", redis=redis) is None


async def test_saving_without_a_user_or_events_saves_nothing():
    redis = FakeRedis()
    await save_last_listing("", RENDERED, [EVENT], redis=redis)
    await save_last_listing("u-2", RENDERED, [], redis=redis)
    assert not redis.data


async def test_a_newer_listing_replaces_the_older_one():
    redis = FakeRedis()
    await save_last_listing("u-1", "first", [EVENT], redis=redis)
    second = ListedEvent(
        name="Sunset Session", venue="Potato Head", area="Seminyak", artist="",
        what="Sunset by the pool.", when_text="Saturday 5 September 2026",
        recurring=False,
        starts_at=datetime(2026, 9, 5, 18, 0, tzinfo=UTC), start_time=time(18, 0),
        price_text="", source_url="https://potatohead.co/events",
        source_title="Potato Head",
    )
    await save_last_listing("u-1", "second", [second], redis=redis)
    store = await load_last_listing("u-1", redis=redis)
    assert store["rendered"] == "second"
    assert store["events"][0].name == "Sunset Session"


async def test_corrupt_records_are_treated_as_no_listing():
    redis = FakeRedis()
    redis.data["anios:last_listing:u-1"] = "not json"
    assert await load_last_listing("u-1", redis=redis) is None
    redis.data["anios:last_listing:u-1"] = '{"events": []}'
    assert await load_last_listing("u-1", redis=redis) is None


async def test_a_direct_message_finds_the_listing_a_room_showed():
    # A listing asked for in a room belongs to the room account. Without
    # looking across the member's rooms, "send me the links" in a direct
    # message would find nothing.
    redis = FakeRedis()
    await _save_at(redis, "u-1", "own listing", "2026-09-04T10:00:00+00:00")
    await _save_at(redis, "group:chess", "room listing", "2026-09-04T11:00:00+00:00")
    store = await load_last_listing_for_member("u-1", ["group:chess"], redis=redis)
    assert store is not None
    assert store["rendered"] == "room listing"


async def test_the_members_own_listing_wins_when_it_is_newer():
    redis = FakeRedis()
    await _save_at(redis, "u-1", "own listing", "2026-09-04T12:00:00+00:00")
    await _save_at(redis, "group:chess", "room listing", "2026-09-04T11:00:00+00:00")
    store = await load_last_listing_for_member("u-1", ["group:chess"], redis=redis)
    assert store["rendered"] == "own listing"


async def test_an_undated_listing_never_beats_a_dated_one():
    # Records written before `saved_at` existed must not win a comparison
    # they cannot enter; the dated listing is the one they most likely mean.
    redis = FakeRedis()
    await _save_at(redis, "u-1", "old listing", None)
    await _save_at(redis, "group:chess", "room listing", "2026-09-04T11:00:00+00:00")
    store = await load_last_listing_for_member("u-1", ["group:chess"], redis=redis)
    assert store["rendered"] == "room listing"
    assert store["saved_at"] == "2026-09-04T11:00:00+00:00"


async def test_with_no_dated_listing_the_members_own_comes_first():
    redis = FakeRedis()
    await _save_at(redis, "u-1", "own listing", None)
    await _save_at(redis, "group:chess", "room listing", None)
    store = await load_last_listing_for_member("u-1", ["group:chess"], redis=redis)
    assert store["rendered"] == "own listing"
    assert store["saved_at"] is None


async def test_a_corrupt_room_record_does_not_hide_the_members_listing():
    redis = FakeRedis()
    await _save_at(redis, "u-1", "own listing", "2026-09-04T10:00:00+00:00")
    redis.data["anios:last_listing:group:chess"] = "not json"
    store = await load_last_listing_for_member("u-1", ["group:chess"], redis=redis)
    assert store["rendered"] == "own listing"
