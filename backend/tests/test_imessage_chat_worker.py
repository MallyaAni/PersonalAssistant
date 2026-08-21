"""iMessage in, /chat through, iMessage out - and nothing for strangers.

The worker is transport: the conversation itself is the same /chat path the
browser uses, so what can be wrong here is the plumbing. These pin it: a
mapped sender's text is answered to the bridge's reply_to handle, a sender
no subscription vouches for is dropped without a conversation ever being
attempted, dedup admits each guid once, the cursor advances even when
everything was filtered, and a failed turn sends the fixed apology rather
than nothing or a stack trace.
"""

import json
import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.workers.imessage_chat import _FAILURE_REPLY, IMessageChatWorker


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

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


def _worker(bridge: _Bridge, monkeypatch, accounts: dict, replies: dict):
    worker = IMessageChatWorker(bridge, base_url="http://test", redis=_Redis())

    async def account_for(sender: str):
        return accounts.get(sender)

    conversed: list[tuple[str, str]] = []

    async def converse(user_id: str, text: str):
        conversed.append((user_id, text))
        return replies.get(text, _FAILURE_REPLY)

    monkeypatch.setattr(worker, "_account_for", account_for)
    monkeypatch.setattr(worker, "_converse", converse)
    return worker, conversed


def _message(guid: str, sender: str, text: str) -> dict:
    return {
        "guid": guid,
        "sender": sender,
        "reply_to": f"+1{sender}",
        "text": text,
        "sent_at": "2026-08-21T22:00:00Z",
    }


@pytest.mark.asyncio
async def test_a_mapped_sender_is_answered_at_the_reply_to_handle(monkeypatch):
    bridge = _Bridge(
        {"messages": [_message("g1", "7372025933", "what's on tonight?")], "cursor": 9}
    )
    worker, conversed = _worker(
        bridge,
        monkeypatch,
        accounts={"7372025933": "ani.mallya"},
        replies={"what's on tonight?": "Two things, actually."},
    )

    answered = await worker.tick()

    assert answered == 1
    assert conversed == [("ani.mallya", "what's on tonight?")]
    assert bridge.sent == [{"to": "+17372025933", "body": "Two things, actually."}]
    assert worker.redis.store["imessage:chat:cursor"] == "9"


@pytest.mark.asyncio
async def test_a_stranger_never_reaches_the_conversation(monkeypatch):
    bridge = _Bridge(
        {"messages": [_message("g2", "5550001111", "hello?")], "cursor": 12}
    )
    worker, conversed = _worker(bridge, monkeypatch, accounts={}, replies={})

    answered = await worker.tick()

    assert answered == 0
    assert conversed == []
    assert bridge.sent == []
    # The cursor still advances: a stranger must not stall the poll.
    assert worker.redis.store["imessage:chat:cursor"] == "12"


@pytest.mark.asyncio
async def test_a_replayed_guid_is_answered_once(monkeypatch):
    message = _message("g3", "7372025933", "ping")
    bridge = _Bridge({"messages": [message, message], "cursor": 15})
    worker, conversed = _worker(
        bridge,
        monkeypatch,
        accounts={"7372025933": "ani.mallya"},
        replies={"ping": "pong"},
    )

    answered = await worker.tick()

    assert answered == 1
    assert len(conversed) == 1
    assert len(bridge.sent) == 1


@pytest.mark.asyncio
async def test_a_failed_turn_sends_the_fixed_apology(monkeypatch):
    bridge = _Bridge(
        {"messages": [_message("g4", "7372025933", "unanswerable")], "cursor": 20}
    )
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"}, replies={}
    )

    answered = await worker.tick()

    assert answered == 1
    assert bridge.sent == [{"to": "+17372025933", "body": _FAILURE_REPLY}]


@pytest.mark.asyncio
async def test_an_unreachable_bridge_is_a_quiet_tick(monkeypatch):
    async def refuse(tool: str, arguments: dict) -> object:
        raise RuntimeError("bridge down")

    worker = IMessageChatWorker(refuse, base_url="http://test", redis=_Redis())

    assert await worker.tick() == 0
