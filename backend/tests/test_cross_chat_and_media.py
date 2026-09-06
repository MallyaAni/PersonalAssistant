"""A direct message can continue what the person just did in a room, and a
file nothing here reads is named rather than dropped.

Both are the 2026-09-04/05 shapes: "try again" in the one-to-one chat after
a picture asked for in the group was searched as events, twice; and a video
or voice note on any message vanished without a word. Pinned without a
model: the merge that gives the router the room turns, marked as the room's;
the gate that leaves a room's own turn alone; and the bridge's words for a
file it cannot open, to a person and to a room.
"""

from __future__ import annotations

import json

import pytest

from backend.services.cross_chat import merged_for_routing
from backend.services.transcript import speaker_label, transcript_lines
from backend.workers.imessage_chat import (
    IMessageChatWorker,
    TurnResult,
    _media_kind,
    _unsupported_media_reply,
)

pytestmark = pytest.mark.asyncio

_DIRECT = [
    {"query": "what are the most fun events happening in the area this week?", "response": "Sat 5 Sep - Africa Fest...", "metadata": {"channel": "imessage"}, "created_at": "2026-09-04T12:01:00+00:00"},
]
_ROOM = [
    {"query": "Can you please generate a picture that shows a castle in chess?", "response": "Here's the image you asked for.", "metadata": {"channel": "imessage_group", "group": {"speaker_name": "Jenos"}, "cross_chat": {"chat_name": "Groupie"}}, "created_at": "2026-09-04T21:10:00+00:00"},
]


def test_room_turns_are_merged_by_time_and_marked_as_the_rooms():
    merged = merged_for_routing(_DIRECT, _ROOM)
    assert [t["created_at"] for t in merged] == ["2026-09-04T12:01:00+00:00", "2026-09-04T21:10:00+00:00"]
    assert speaker_label(merged[1]) == "Jenos (in the group chat 'Groupie')"
    assert speaker_label(merged[0]) == "User"
    lines = transcript_lines(merged)
    assert any("(in the group chat 'Groupie')" in line and "castle in chess" in line for line in lines)


def test_the_merge_is_bounded_and_empty_rooms_change_nothing():
    many = [{"query": f"q{i}", "response": "r", "metadata": {}, "created_at": f"2026-09-04T{i:02d}:00:00+00:00"} for i in range(20)]
    assert merged_for_routing(many, _ROOM, limit=5)[-1] is _ROOM[0]
    assert len(merged_for_routing(many, _ROOM, limit=5)) == 5
    assert merged_for_routing(_DIRECT, []) == _DIRECT


async def test_a_direct_message_is_routed_with_the_rooms_turns_and_a_rooms_own_is_not(monkeypatch):
    from backend.services import conversation_service as module
    from backend.services.conversation_service import ConversationService

    service = ConversationService.__new__(ConversationService)

    async def reader(user_id):
        return list(_ROOM)

    service.room_turns_reader = reader  # type: ignore[attr-defined]
    module._turn_channel.set("imessage")
    merged = await service._history_for_routing("ani", list(_DIRECT))
    assert len(merged) == 2 and "cross_chat" in merged[1]["metadata"]
    module._turn_channel.set("imessage_group")
    assert await service._history_for_routing("ani", list(_DIRECT)) == _DIRECT

    async def broken(user_id):
        raise RuntimeError("database away")

    service.room_turns_reader = broken  # type: ignore[attr-defined]
    module._turn_channel.set("imessage")
    assert await service._history_for_routing("ani", list(_DIRECT)) == _DIRECT


def test_a_files_kind_is_read_from_its_type_and_the_line_names_it():
    assert _media_kind({"media_type": "video/quicktime"}) == "video"
    assert _media_kind({"media_type": "audio/m4a"}) == "voice note"
    assert _media_kind({"media_type": "application/zip"}) == "file"
    assert _unsupported_media_reply([{"media_type": "video/mp4"}]).startswith("I can't open a video yet.")
    assert "video and voice note" in _unsupported_media_reply([{"media_type": "video/mp4"}, {"media_type": "audio/m4a"}])


# --- the bridge, with the fixtures the worker tests use ---


class _Bridge:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.sent: list[dict] = []

    async def __call__(self, tool: str, arguments: dict) -> object:
        if tool == "read_messages":
            return json.dumps(self.payload)
        self.sent.append(dict(arguments))
        return json.dumps({"result": "sent"})


class _Redis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)

    async def expire(self, key, seconds):
        return True

    async def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    async def srem(self, key, member):
        self.sets.get(key, set()).discard(member)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))


def _worker(bridge, monkeypatch):
    worker = IMessageChatWorker(bridge, base_url="http://test", redis=_Redis())

    async def account_for(sender):
        return {"5550100": "u-ani"}.get(sender)

    conversed: list[str] = []

    async def converse(user_id, text, active_image=None, status=None, room=None, **_):
        conversed.append(text)
        return TurnResult("ok")

    monkeypatch.setattr(worker, "_account_for", account_for)
    monkeypatch.setattr(worker, "_converse", converse)
    return worker, conversed


async def test_a_direct_message_with_only_a_video_is_told_what_can_be_opened(monkeypatch):
    message = {"guid": "v1", "sender": "5550100", "reply_to": "+15550100", "text": "", "sent_at": "2026-09-06T10:00:00Z",
               "attachments": [{"attachment_id": "a1", "media_type": "video/quicktime", "name": "IMG_2001.MOV"}]}
    bridge = _Bridge({"messages": [message], "cursor": 5})
    worker, conversed = _worker(bridge, monkeypatch)
    assert await worker.tick() == 1
    assert conversed == []
    assert bridge.sent[0]["to"] == "+15550100" and bridge.sent[0]["body"].startswith("I can't open a video yet.")
    assert await worker._already_seen("v1")


async def test_a_video_with_a_caption_still_gets_the_caption_answered(monkeypatch):
    message = {"guid": "v2", "sender": "5550100", "reply_to": "+15550100", "text": "look at this", "sent_at": "2026-09-06T10:00:00Z",
               "attachments": [{"attachment_id": "a1", "media_type": "video/quicktime", "name": "IMG_2001.MOV"}]}
    bridge = _Bridge({"messages": [message], "cursor": 5})
    worker, conversed = _worker(bridge, monkeypatch)

    async def readiness(user_id, reply_to, fragments, in_group, addressed_by=""):
        return {"complete": True, "needs_reply": True}

    monkeypatch.setattr(worker, "_readiness", readiness)
    assert await worker.tick() == 1
    assert conversed == ["look at this"]
