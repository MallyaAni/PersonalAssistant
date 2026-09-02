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
        "assistant_name": "Scout",
    }


def _worker(bridge, monkeypatch, accounts: dict, replies: dict, *, group=None, readiness=None):
    worker = IMessageChatWorker(bridge, base_url="http://test", redis=_Redis())

    async def account_for(sender: str):
        return accounts.get(sender)

    conversed: list[dict] = []

    async def converse(user_id: str, text: str, active_image=None, status=None, room=None, **_):
        conversed.append({"user_id": user_id, "text": text, "room": room})
        return TurnResult(replies.get(text, _FAILURE_REPLY))

    provisioned: list[tuple] = []

    async def group_for(chat_guid, chat_name, members):
        provisioned.append((chat_guid, chat_name, members))
        return group

    verdicts = list(readiness or [])

    async def readiness_call(user_id, reply_to, fragments, in_group, addressed_by=""):
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
        "assistant_name": "Scout",
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
async def test_a_closing_thanks_addressed_by_name_gets_no_reply(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "thanks Scout!", addressed_by="name")], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP, readiness=[{"complete": True, "needs_reply": False}])
    assert await worker.tick() == 0
    assert conversed == [] and bridge.sent == []
    assert await worker._already_seen("g1")


@pytest.mark.asyncio
async def test_a_reply_to_the_assistants_bubble_is_always_answered(monkeypatch):
    # Live, 2026-08-28: "we are a groupie!!" as a reply to its bubble got
    # silence because the judge read it as a closing remark.
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "we are a groupie!!", addressed_by="reply")], "cursor": 5})
    worker, conversed, _ = _worker(
        bridge, monkeypatch, ACCOUNTS, {"we are a groupie!!": "Groupies forever 🎉"}, group=GROUP,
        readiness=[{"complete": True, "needs_reply": False}],
    )
    assert await worker.tick() == 1
    assert conversed[0]["text"] == "we are a groupie!!"
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Groupies forever 🎉"}]


# A tapback in a room runs as the group and retains the speaker/membership
# context from the Scout turn that produced the targeted bubble.
@pytest.mark.asyncio
async def test_a_positive_tapback_accepts_a_group_offer_in_the_room(monkeypatch):
    sent: list[dict] = []
    send_count = 0

    # Return one persistent heart on the first sent room bubble.
    async def bridge(tool: str, arguments: dict) -> object:
        nonlocal send_count
        if tool == "read_reactions_by_guid":
            return json.dumps(
                {
                    "reactions": [
                        {
                            "message_guid": arguments["message_guids"][0],
                            "reaction": "loved",
                            "sender": "5550100",
                        }
                    ]
                }
            )
        if tool == "read_messages":
            return json.dumps({"messages": [], "cursor": 51})
        sent.append(dict(arguments))
        send_count += 1
        return f"iMessage;-;22222222-2222-2222-2222-{send_count:012d}"

    worker, conversed, _ = _worker(
        bridge, monkeypatch, ACCOUNTS, {}, group=GROUP
    )
    room = {
        "chat_name": "Lunch crew",
        "speaker_user_id": "u-jen",
        "members": ["u-ani", "u-jen"],
        "addressed_by": "name",
        "assistant_name": "Scout",
    }

    # This exact bubble offered an action, so the semantic gate admits it.
    async def readiness(*args, **kwargs):
        return {
            "complete": True,
            "needs_reply": False,
            "accepts_offer": True,
            "available": True,
        }

    monkeypatch.setattr(worker, "_readiness", readiness)
    await worker._deliver(
        ROOM_GUID,
        TurnResult("Want me to find a table for Friday?"),
        user_id=GROUP.user_id,
        room=room,
    )

    assert await worker.tick() == 1
    assert conversed[0]["user_id"] == GROUP.user_id
    assert conversed[0]["room"] == {
        **room,
        "speaker_user_id": "u-ani",
        "addressed_by": "tapback",
    }
    assert conversed[0]["text"].startswith("Yes — do what you offered")
    assert sent[-1]["to"] == ROOM_GUID


# A reaction in a room has authority only when its sender maps to one of that
# room's approved accounts; missing or unknown identity never borrows another
# member's speaker context.
@pytest.mark.asyncio
async def test_an_unknown_group_reactor_cannot_accept_an_offer(monkeypatch):
    bridge = _Bridge({"messages": [], "cursor": 52})
    worker, _, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    room = {
        "chat_name": "Lunch crew",
        "speaker_user_id": "u-jen",
        "members": ["u-ani", "u-jen"],
    }
    record = {
        "user_id": GROUP.user_id,
        "reply_to": ROOM_GUID,
        "body": "Want me to find a table?",
        "room": room,
    }

    assert await worker._tapback_context({"sender": "5550199"}, record) is None
    assert await worker._tapback_context({}, record) is None


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

    async def real_readiness(user_id, reply_to, fragments, in_group, addressed_by=""):
        return await IMessageChatWorker._readiness(worker, user_id, reply_to, fragments, in_group, addressed_by)

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


# --- Nothing addressed to the assistant is lost to a restart ---

from backend.workers.imessage_chat import _PARKED_KEY, BackendUnavailable, _FAILURE_REPLY as _APOLOGY, _PARKED_NOTICE


def _flaky_worker(bridge, monkeypatch, accounts, replies, *, group=None, down: list):
    """A worker whose backend is down while `down[0]` is True."""
    worker, conversed, provisioned = _worker(bridge, monkeypatch, accounts, replies, group=group)

    async def converse(user_id, text, active_image=None, status=None, room=None, **_):
        if down[0]:
            raise BackendUnavailable("connection refused")
        conversed.append({"user_id": user_id, "text": text, "room": room})
        return TurnResult(replies.get(text, _APOLOGY))

    monkeypatch.setattr(worker, "_converse", converse)
    return worker, conversed


@pytest.mark.asyncio
async def test_a_message_that_finds_the_backend_down_is_parked_not_apologised_for(monkeypatch):
    down = [True]
    direct = {"guid": "d1", "sender": "5550100", "reply_to": "+15550100", "text": "what's the weather", "sent_at": "2026-08-28T20:00:00Z"}
    bridge = _Bridge({"messages": [direct], "cursor": 5})
    worker, conversed = _flaky_worker(bridge, monkeypatch, ACCOUNTS, {"what's the weather": "Sunny."}, down=down)
    assert await worker.tick() == 0
    assert bridge.sent == [] and conversed == []
    assert not await worker._already_seen("d1")
    parked = json.loads(worker.redis.store[_PARKED_KEY])
    assert [p["guid"] for p in parked] == ["d1"] and parked[0]["text"] == "what's the weather"
    # Still down on the next poll: parked again, nothing sent, one record.
    worker.invoke_tool.payload = {"messages": [], "cursor": 6}
    assert await worker.tick() == 0
    assert len(json.loads(worker.redis.store[_PARKED_KEY])) == 1
    assert json.loads(worker.redis.store[_PARKED_KEY])[0]["attempts"] == 2
    # Back: answered once, at the original address, and finished.
    down[0] = False
    assert await worker.tick() == 1
    assert bridge.sent == [{"to": "+15550100", "body": "Sunny."}]
    assert conversed[0]["text"] == "what's the weather"
    assert await worker._already_seen("d1")
    assert _PARKED_KEY not in worker.redis.store


@pytest.mark.asyncio
async def test_a_parked_turn_gets_one_notice_after_a_minute(monkeypatch):
    monkeypatch.setattr(settings, "IMESSAGE_CHAT_RETRY_NOTICE_SECONDS", 0.0)
    down = [True]
    direct = {"guid": "d1", "sender": "5550100", "reply_to": "+15550100", "text": "hi", "sent_at": "2026-08-28T20:00:00Z"}
    bridge = _Bridge({"messages": [direct], "cursor": 5})
    worker, _ = _flaky_worker(bridge, monkeypatch, ACCOUNTS, {}, down=down)
    await worker.tick()
    worker.invoke_tool.payload = {"messages": [], "cursor": 6}
    await worker.tick()
    await worker.tick()
    assert bridge.sent == [{"to": "+15550100", "body": _PARKED_NOTICE}]


@pytest.mark.asyncio
async def test_a_turn_parked_past_the_window_gets_the_apology_once(monkeypatch):
    monkeypatch.setattr(settings, "IMESSAGE_CHAT_RETRY_MINUTES", 0.0001)
    down = [True]
    direct = {"guid": "d1", "sender": "5550100", "reply_to": "+15550100", "text": "hi", "sent_at": "2026-08-28T20:00:00Z"}
    bridge = _Bridge({"messages": [direct], "cursor": 5})
    worker, _ = _flaky_worker(bridge, monkeypatch, ACCOUNTS, {}, down=down)
    await worker.tick()
    import asyncio

    await asyncio.sleep(0.02)
    worker.invoke_tool.payload = {"messages": [], "cursor": 6}
    await worker.tick()
    assert bridge.sent == [{"to": "+15550100", "body": _APOLOGY}]
    assert await worker._already_seen("d1")
    assert _PARKED_KEY not in worker.redis.store
    await worker.tick()
    assert len(bridge.sent) == 1


@pytest.mark.asyncio
async def test_a_room_whose_database_is_away_is_parked_whole_and_answered_later(monkeypatch):
    bridge = _Bridge({"messages": [_room_message("g1", "5550100", "Scout, thai?")], "cursor": 5})
    worker, conversed, provisioned = _worker(bridge, monkeypatch, ACCOUNTS, {"Scout, thai?": "Thai it is."}, group=None)
    assert await worker.tick() == 0
    assert not await worker._already_seen("g1")
    parked = json.loads(worker.redis.store[_PARKED_KEY])
    assert parked[0]["guid"] == "g1" and parked[0]["message"]["chat_identifier"] == "chat778899001122"

    async def group_for(chat_guid, chat_name, members):
        return GROUP

    monkeypatch.setattr(worker, "_group_for", group_for)
    worker.invoke_tool.payload = {"messages": [], "cursor": 6}
    assert await worker.tick() == 1
    assert conversed[0]["user_id"] == "group:abc" and conversed[0]["text"] == "Scout, thai?"
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Thai it is."}]
    assert await worker._already_seen("g1")


@pytest.mark.asyncio
async def test_a_group_turn_that_finds_the_backend_down_is_parked_with_its_room(monkeypatch):
    down = [True]
    bridge = _Bridge({"messages": [_room_message("g1", "5550101", "Scout, thai?")], "cursor": 5})
    worker, conversed = _flaky_worker(bridge, monkeypatch, ACCOUNTS, {"Scout, thai?": "Thai."}, group=GROUP, down=down)
    assert await worker.tick() == 0
    parked = json.loads(worker.redis.store[_PARKED_KEY])
    assert parked[0]["room"]["speaker_user_id"] == "u-jen" and parked[0]["user_id"] == "group:abc"
    down[0] = False
    worker.invoke_tool.payload = {"messages": [], "cursor": 6}
    assert await worker.tick() == 1
    assert conversed[0]["room"]["chat_name"] == "Lunch crew"
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Thai."}]


def test_only_a_missing_backend_counts_as_unavailable():
    import httpx

    from backend.workers.imessage_chat import _is_unavailable

    assert _is_unavailable(httpx.ConnectError("refused"))
    request = httpx.Request("POST", "http://backend:8000/api/v1/chat")
    assert _is_unavailable(httpx.HTTPStatusError("bad gateway", request=request, response=httpx.Response(502, request=request)))
    assert not _is_unavailable(httpx.HTTPStatusError("server error", request=request, response=httpx.Response(500, request=request)))
    assert not _is_unavailable(httpx.ReadTimeout("slow"))
    assert not _is_unavailable(RuntimeError("bug"))


@pytest.mark.asyncio
async def test_provisioning_a_room_seeds_its_scout_from_what_members_share(monkeypatch):
    import backend.groups.repository as repo_module
    import backend.groups.shared_interests as shared_module
    import backend.workers.imessage_chat as worker_module

    refreshed: list[tuple] = []

    class _Repo:
        def __init__(self, db):
            pass

        async def by_chat_digest(self, digest):
            return None

        async def provision(self, chat, name, members):
            return _Group("group:new", chat, "d", name, True, members)

        async def touch(self, user_id):
            pass

    async def refresh(db, group_user_id, members):
        refreshed.append((group_user_id, members))
        return ("thai food",)

    class _Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(repo_module, "ConversationGroupRepository", _Repo)
    monkeypatch.setattr(shared_module, "refresh_shared_interests", refresh)
    monkeypatch.setattr(worker_module, "AsyncSessionLocal", lambda: _Db())
    worker = IMessageChatWorker(_Bridge({"messages": [], "cursor": 0}), base_url="http://test", redis=_Redis())
    group = await IMessageChatWorker._group_for(worker, ROOM_GUID, "Lunch crew", ("u-ani", "u-jen"))
    assert group.user_id == "group:new"
    assert refreshed == [("group:new", ("u-ani", "u-jen"))]


@pytest.mark.asyncio
async def test_an_unaddressed_room_message_is_observed_not_answered(monkeypatch):
    # Operator's decision, 2026-08-28: the whole room is context; only what
    # addresses the assistant is answered.
    bridge = _Bridge({"messages": [_room_message("g1", "5550101", "we all settled on thai for friday", addressed_by="")], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    observed: list[tuple] = []

    async def observe(user_id, text, room):
        observed.append((user_id, text, room["speaker_user_id"], room["addressed_by"]))

    monkeypatch.setattr(worker, "_observe", observe)
    assert await worker.tick() == 0
    assert observed == [("group:abc", "we all settled on thai for friday", "u-jen", "")]
    assert conversed == [] and bridge.sent == []
    assert await worker._already_seen("g1")


@pytest.mark.asyncio
async def test_observing_posts_the_room_turn_under_the_groups_conversation(monkeypatch):
    import httpx

    bridge = _Bridge({"messages": [], "cursor": 0})
    worker = IMessageChatWorker(bridge, base_url="http://test", redis=_Redis())
    posted: list[dict] = []

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"conversation_id": "conv-1"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posted.append({"url": url, "json": json, "auth": bool(headers and headers.get("Authorization"))})
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    await worker._observe("group:abc", "lunch friday?", {"chat_name": "Lunch crew", "speaker_user_id": "u-ani", "members": ["u-ani"], "addressed_by": "", "assistant_name": ""})
    (call,) = posted
    assert call["url"].endswith("/api/v1/chat/observe") and call["auth"]
    assert call["json"]["user_id"] == "group:abc" and call["json"]["query"] == "lunch friday?"
    assert call["json"]["metadata"]["channel"] == "imessage_group"
    assert "conversation_id" not in call["json"]
    # The conversation the backend opened is the thread from now on.
    assert await worker._stored_conversation("group:abc") == "conv-1"


@pytest.mark.asyncio
async def test_an_address_nobody_vouched_for_never_reaches_the_mac(monkeypatch):
    """The second wall. The backend fences the reply as it is written; this
    proves a reply carrying an unvouched address is not deliverable even if
    that fence were off - the failure on 2026-08-29 put maps.app.goo.gl/xyz
    on a real phone."""
    from backend.core.links import allowed_urls as _allowed

    direct = {"guid": "d1", "sender": "5550100", "reply_to": "+15550100", "text": "what's on", "sent_at": "2026-08-29T20:00:00Z"}
    bridge = _Bridge({"messages": [direct], "cursor": 5})
    worker, _conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {})

    async def converse(user_id, text, active_image=None, status=None, room=None, **_):
        return TurnResult(
            "Two spots:\nLa Brisa — https://labrisabali.com/whats-on\n"
            "Map link: https://maps.app.goo.gl/xyz\n"
            "Map: https://maps.google.com/?q=La+Brisa+Canggu",
            (),
            _allowed([{"url": "https://labrisabali.com/whats-on"}]),
        )

    monkeypatch.setattr(worker, "_converse", converse)
    assert await worker.tick() == 1
    sent = " ".join(str(call.get("body") or "") for call in bridge.sent)
    assert "maps.app.goo.gl" not in sent, sent
    # The source's own link and a search template both survive.
    assert "labrisabali.com/whats-on" in sent
    assert "maps.google.com/?q=La+Brisa+Canggu" in sent
    assert "Map link:" not in sent


# A document shared in the room is read into the room's own knowledge: the
# group is the owner, and the confirmation goes to the room.
@pytest.mark.asyncio
async def test_a_room_pdf_is_a_document_turn_for_the_group(monkeypatch):
    message = _room_message("g1", "5550100", "Scout here's the itinerary", addressed_by="name")
    message["attachments"] = [{"attachment_id": "a1", "media_type": "application/pdf", "name": "Itinerary.pdf"}]
    bridge = _Bridge({"messages": [message], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    seen: list[tuple] = []
    photos: list[tuple] = []

    async def document_turn(user_id, caption, documents):
        seen.append((user_id, caption, len(documents)))
        return TurnResult("Got it - I've read Itinerary.pdf (2 pages).", (), document_id="doc-1")

    async def photo_turn(user_id, caption, attachments):
        photos.append((user_id, caption))
        return TurnResult("should not happen")

    monkeypatch.setattr(worker, "_document_turn", document_turn)
    monkeypatch.setattr(worker, "_photo_turn", photo_turn)
    assert await worker.tick() == 1
    # The room's copy, then the sharer's own - never the other member's.
    assert seen == [("group:abc", "Scout here's the itinerary", 1), ("u-ani", "Scout here's the itinerary", 1)]
    assert photos == []
    assert conversed == []
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Got it - I've read Itinerary.pdf (2 pages)."}]


# A document shared without naming the assistant is still read into the
# room's knowledge - it is context, like observed text - but draws no reply.
@pytest.mark.asyncio
async def test_an_unaddressed_room_pdf_is_read_silently(monkeypatch):
    message = _room_message("g1", "5550100", "here's the itinerary, what do you think?", addressed_by="")
    message["attachments"] = [{"attachment_id": "a1", "media_type": "application/pdf", "name": "Itinerary.pdf"}]
    bridge = _Bridge({"messages": [message], "cursor": 5})
    worker, conversed, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    seen: list[tuple] = []

    async def document_turn(user_id, caption, documents):
        seen.append((user_id, len(documents)))
        return TurnResult(
            "Got it - I've read Itinerary.pdf (2 pages).", (), document_id="doc-1", read_titles=("Itinerary.pdf",)
        )

    observed: list[tuple[str, str]] = []

    async def observe(user_id, text, room):
        observed.append((user_id, text))

    monkeypatch.setattr(worker, "_document_turn", document_turn)
    monkeypatch.setattr(worker, "_observe", observe)
    await worker.tick()
    assert seen == [("group:abc", 1), ("u-ani", 1)]
    assert conversed == []
    assert bridge.sent == []
    # The share is on the record by name - before the caption is observed as
    # ordinary room chatter - so "day 1" later means this file.
    assert observed[0] == ("group:abc", 'shared a document: "Itinerary.pdf"'), observed
    assert ("group:abc", "here's the itinerary, what do you think?") in observed, observed


# The sharer keeps their own copy: a document dropped in the room is read
# into the room's knowledge and into the sharer's, never into the other
# member's - the same rule a stated fact follows.
@pytest.mark.asyncio
async def test_a_room_document_is_also_the_sharers_own(monkeypatch):
    message = _room_message("g1", "5550100", "Scout here's the itinerary", addressed_by="name")
    message["attachments"] = [{"attachment_id": "a1", "media_type": "application/pdf", "name": "Itinerary.pdf"}]
    bridge = _Bridge({"messages": [message], "cursor": 5})
    worker, _, _ = _worker(bridge, monkeypatch, ACCOUNTS, {}, group=GROUP)
    owners: list[str] = []

    async def document_turn(user_id, caption, documents):
        owners.append(user_id)
        return TurnResult("Got it - I've read Itinerary.pdf (2 pages).", (), document_id="doc-1", read_titles=("Itinerary.pdf",))

    monkeypatch.setattr(worker, "_document_turn", document_turn)
    assert await worker.tick() == 1
    assert owners[0] == "group:abc"
    assert ACCOUNTS["5550100"] in owners[1:], owners
    assert len(owners) == 2, owners
    assert bridge.sent == [{"to": ROOM_GUID, "body": "Got it - I've read Itinerary.pdf (2 pages)."}]
