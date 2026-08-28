"""Group chats in the iMessage worker: the membership wall, provisioning,
the room-aware turn, delivery into the chat, and bursts judged by meaning.

The bridge only forwards what was addressed to the account; everything
here starts from that and establishes the room.
"""

import json
from dataclasses import dataclass

import pytest

from backend.config.settings import settings
from backend.workers.imessage_chat import (
    _FAILURE_REPLY,
    _PENDING_INDEX_KEY,
    _PENDING_KEY,
    IMessageChatWorker,
    TurnResult,
)

ROOM_GUID = "iMessage;+;chat778899001122"


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

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key: str):
        self.store.pop(key, None)

    async def expire(self, key: str, seconds: int):
        return True

    async def sadd(self, key: str, member: str):
        self.sets.setdefault(key, set()).add(member)

    async def srem(self, key: str, member: str):
        self.sets.get(key, set()).discard(member)

    async def smembers(self, key: str):
        return set(self.sets.get(key, set()))


@dataclass(frozen=True)
class _Group:
    user_id: str
    chat_address: str
    chat_digest: str
    display_name: str
    enabled: bool
    members: tuple[str, ...]


def _room_message(guid: str, sender: str, text: str, participants=("5550100", "5550101"), addressed_by="name") -> dict:
    return {
        "guid": guid,
        "sender": sender,
        "reply_to": ROOM_GUID,
        "text": text,
        "sent_at": "2026-08-28T20:00:00Z",
        "chat_guid": ROOM_GUID,
        "chat_identifier": "chat778899001122",
        "chat_name": "Lunch crew",
        "participants": list(participants),
        "addressed_by": addressed_by,
    }


def _worker(bridge, monkeypatch, accounts: dict, replies: dict, *, group=None, readiness=None):
    worker = IMessageChatWorker(bridge, base_url="http://test", redis=_Redis())

    async def account_for(sender: str):
        return accounts.get(sender)

    conversed: list[dict] = []

    async def converse(user_id: str, text: str, active_image=None, status=None, room=None):
        conversed.append({"user_id": user_id, "text": text, "room": room})
        return TurnResult(replies.get(text, _FAILURE_REPLY))

    provisioned: list[tuple] = []

    async def group_for(chat_guid, chat_name, members):
        provisioned.append((chat_guid, chat_name, members))
        return group

    verdicts = list(readiness or [])

    async def readiness_call(user_id, reply_to, fragments, in_group):
        if verdicts:
            return verdicts.pop(0)
        return {"complete": True, "needs_reply": True}

    monkeypatch.setattr(worker, "_account_for", account_for)
    monkeypatch.setattr(worker, "_converse", converse)
    monkeypatch.setattr(worker, "_group_for", group_for)
    monkeypatch.setattr(worker, "_readiness", readiness_call)
    monkeypatch.setattr(settings, "IMESSAGE_CHAT_ACK_SECONDS", 30.0)
    return worker, conversed, provisioned


ACCOUNTS = {"5550100": "u-ani", "5550101": "u-jen"}
GROUP = _Group("group:abc", ROOM_GUID, "d", "Lunch crew", True, ("u-ani", "u-jen"))


@pytest.mark.asyncio
async def test_an_addressed_room_message_runs_as_the_group_and_answers_the_room(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550101", "Scout, thai or pizza?")], "cursor": 5})
    worker, conversed, provisioned = _worker(bridge, monkeypatch, ACCOUNTS, {"Scout, thai or pizza?": "Thai, Jen - Ani's been craving it."}, group=GROUP)
    assert await worker.tick() == 1
    assert provisioned == [(ROOM_GUID, "Lunch crew", ("u-ani", "u-jen"))]
    (turn,) = conversed
    assert turn["user_id"] == "group:abc"
    assert turn["room"] == {
        "chat_name": "Lunch crew",
        "speaker_user_id": "u-jen",
        "members": ["u-ani", "u-jen"],
        "addressed_by": "name",
    }
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Thai, Jen - Ani's been craving it."}]


@pytest.mark.asyncio
async def test_a_room_with_a_stranger_is_answered_nowhere_and_the_operator_is_told_once(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_ALERT_PHONE", "+15550000")
    messages = [
        _room_message("g1", "5550100", "Scout, hi", participants=("5550100", "5550101", "5550199")),
        _room_message("g2", "5550100", "Scout, hello?", participants=("5550100", "5550101", "5550199")),
    ]
    bridge = _Bridge({"messages": messages, "cursor": 5})
    worker, conversed, provisioned = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    assert await worker.tick() == 0
    assert conversed == [] and provisioned == []
    (alert,) = bridge.sent
    assert alert["to"] == "+15550000"
    assert "Lunch crew" in alert["body"] and "one person" in alert["body"]
    assert "5550199" not in alert["body"]
    # Both rows are finished, never replayed.
    assert await worker._already_seen("g1") and await worker._already_seen("g2")


@pytest.mark.asyncio
async def test_no_operator_phone_means_no_alert_and_still_silence(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_ALERT_PHONE", "")
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "Scout, hi", participants=("5550100", "5550199"))], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    assert await worker.tick() == 0
    assert bridge.sent == [] and conversed == []


@pytest.mark.asyncio
async def test_a_room_whose_speaker_is_unknown_is_ignored(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550199", "Scout, hi")], "cursor": 5})
    worker, conversed, provisioned = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    assert await worker.tick() == 0
    assert conversed == [] and provisioned == [] and bridge.sent == []


@pytest.mark.asyncio
async def test_a_disabled_group_stays_quiet(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "Scout, hi")], "cursor": 5})
    quiet = _Group("group:abc", ROOM_GUID, "d", "Lunch crew", False, ("u-ani", "u-jen"))
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=quiet)
    assert await worker.tick() == 0
    assert conversed == [] and bridge.sent == []
    assert await worker._already_seen("g1")


@pytest.mark.asyncio
async def test_a_group_the_database_cannot_give_is_answered_later_not_wrongly(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "Scout, hi")], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=None)
    assert await worker.tick() == 0
    assert conversed == [] and bridge.sent == []


@pytest.mark.asyncio
async def test_an_unfinished_fragment_waits_and_the_finished_burst_is_answered_once(monkeypatch):
    first = _Bridge({"messages": [_room_message("g1", "5550100", "Scout ok so")], "cursor": 5})
    worker, conversed, _ = _worker(
        first, monkeypatch, ACCOUNTS, {"Scout ok so\nfind us a thai place near dupont?": "Try Little Serow."},
        group=GROUP, readiness=[{"complete": False, "needs_reply": True}, {"complete": True, "needs_reply": True}],
    )
    assert await worker.tick() == 0
    assert conversed == [] and first.sent == []
    assert json.loads(worker.redis.store[_PENDING_KEY.format(to=ROOM_GUID)])["fragments"][0]["text"] == "Scout ok so"
    worker.invoke_tool.payload = {"messages": [_room_message("g2", "5550100", "find us a thai place near dupont?", addressed_by="reply")], "cursor": 6}
    assert await worker.tick() == 1
    (turn,) = conversed
    assert turn["text"] == "Scout ok so\nfind us a thai place near dupont?"
    assert first.sent == [{"to": ROOM_GUID, "body": "Try Little Serow."}]
    assert _PENDING_KEY.format(to=ROOM_GUID) not in worker.redis.store
    assert ROOM_GUID not in worker.redis.sets.get(_PENDING_INDEX_KEY, set())


@pytest.mark.asyncio
async def test_a_closing_thanks_gets_no_reply(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "thanks Scout!", addressed_by="reply")], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP, readiness=[{"complete": True, "needs_reply": False}])
    assert await worker.tick() == 0
    assert conversed == [] and bridge.sent == []
    assert await worker._already_seen("g1")


@pytest.mark.asyncio
async def test_a_fragment_past_the_cap_is_answered_on_arrival(monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "IMESSAGE_CHAT_BURST_CAP_SECONDS", 0.05)
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "Scout so")], "cursor": 5})
    worker, conversed, _ = _worker(
        bridge, monkeypatch, ACCOUNTS, {"Scout so\nnever mind, thai?": "Thai it is."}, group=GROUP,
        readiness=[{"complete": False, "needs_reply": True}, {"complete": False, "needs_reply": True}],
    )
    assert await worker.tick() == 0
    await asyncio.sleep(0.06)
    # Still judged unfinished, but the oldest fragment is older than the cap:
    # answered now rather than kept any longer.
    worker.invoke_tool.payload = {"messages": [_room_message("g2", "5550100", "never mind, thai?", addressed_by="reply")], "cursor": 6}
    assert await worker.tick() == 1
    assert conversed[0]["text"] == "Scout so\nnever mind, thai?"
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Thai it is."}]


@pytest.mark.asyncio
async def test_a_burst_left_pending_is_flushed_by_a_later_poll(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "Scout so")], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {"Scout so": "Yes?"}, group=GROUP, readiness=[{"complete": False, "needs_reply": True}])
    assert await worker.tick() == 0
    monkeypatch.setattr(settings, "IMESSAGE_CHAT_BURST_CAP_SECONDS", 0.0)
    worker.invoke_tool.payload = {"messages": [], "cursor": 6}
    assert await worker.tick() == 1
    assert conversed[0]["text"] == "Scout so" and conversed[0]["user_id"] == "group:abc"
    assert conversed[0]["room"]["chat_name"] == "Lunch crew"
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Yes?"}]


@pytest.mark.asyncio
async def test_a_direct_message_is_judged_too_and_a_bare_ok_is_left_alone(monkeypatch):
    direct = {"guid": "d1", "sender": "5550100", "reply_to": "+15550100", "text": "ok", "sent_at": "2026-08-28T20:00:00Z"}
    bridge = _Bridge({"messages": [direct], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, readiness=[{"complete": True, "needs_reply": False}])
    assert await worker.tick() == 0
    assert conversed == [] and bridge.sent == []


@pytest.mark.asyncio
async def test_with_the_judgement_off_every_message_is_answered_as_before(monkeypatch):
    monkeypatch.setattr(settings, "IMESSAGE_CHAT_READINESS_ENABLED", False)
    direct = {"guid": "d1", "sender": "5550100", "reply_to": "+15550100", "text": "ok", "sent_at": "2026-08-28T20:00:00Z"}
    bridge = _Bridge({"messages": [direct], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {"ok": "👍"}, readiness=[{"complete": True, "needs_reply": False}])
    assert await worker.tick() == 1
    assert conversed[0]["text"] == "ok" and conversed[0]["room"] is None
    assert bridge.sent == [{"to": "+15550100", "body": "👍"}]


@pytest.mark.asyncio
async def test_the_readiness_call_fails_open_to_answering(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "Scout, thai?")], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {"Scout, thai?": "Sure."}, group=GROUP)
    monkeypatch.setattr(worker, "base_url", "http://127.0.0.1:9")  # nothing listens

    async def real_readiness(user_id, reply_to, fragments, in_group):
        return await IMessageChatWorker._readiness(worker, user_id, reply_to, fragments, in_group)

    monkeypatch.setattr(worker, "_readiness", real_readiness)
    assert await worker.tick() == 1
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Sure."}]


@pytest.mark.asyncio
async def test_the_last_bubble_is_remembered_per_address_for_the_judgement(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "Scout, thai?")], "cursor": 5})
    worker, _, _ = _worker(bridge, monkeypatch, ACCOUNTS, {"Scout, thai?": "**Thai** it is"}, group=GROUP)
    await worker.tick()
    assert worker.redis.store["imessage:chat:last_reply:" + ROOM_GUID] == "Thai it is"


@pytest.mark.asyncio
async def test_a_room_photo_is_a_vision_turn_for_the_group(monkeypatch):
    message = _room_message("g1", "5550100", "Scout what is this", addressed_by="name")
    message["attachments"] = [{"attachment_id": "a1", "media_type": "image/jpeg"}]
    bridge = _Bridge({"messages": [message], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    seen: list[tuple] = []

    async def photo_turn(user_id, caption, attachments):
        seen.append((user_id, caption, len(attachments)))
        return TurnResult("A bowl of pho.")

    monkeypatch.setattr(worker, "_photo_turn", photo_turn)
    assert await worker.tick() == 1
    assert seen == [("group:abc", "Scout what is this", 1)]
    assert conversed == []
    assert bridge.sent == [{"to": ROOM_GUID, "body": "A bowl of pho."}]
