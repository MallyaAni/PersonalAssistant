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

from backend.workers.imessage_chat import (
    _FAILURE_REPLY,
    IMessageChatWorker,
    TurnResult,
)


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
        return TurnResult(replies.get(text, _FAILURE_REPLY))

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


# The session boundary is a lull. The stored thread id carries a TTL and
# every use renews it, so an active exchange stays one conversation and the
# first text after a quiet day starts a new one - iMessage has no "new
# chat" button, so this is where that button lives.
@pytest.mark.asyncio
async def test_the_thread_id_expires_with_the_idle_window(monkeypatch):
    class _TtlRedis(_Redis):
        def __init__(self):
            super().__init__()
            self.ttls: dict[str, int] = {}

        async def set(self, key, value, ex=None, nx=False):
            if ex is not None:
                self.ttls[key] = ex
            return await super().set(key, value, nx=nx)

        async def expire(self, key, ttl):
            self.ttls[key] = ttl
            return True

    redis = _TtlRedis()

    async def ok(tool, arguments):
        return json.dumps({"result": "sent"})

    worker = IMessageChatWorker(ok, base_url="http://test", redis=redis)
    await worker._remember_conversation("ani.mallya", "conv-1")
    key = "imessage:chat:conversation:ani.mallya"
    assert redis.ttls[key] > 0, "a stored thread must expire after the lull"

    redis.ttls[key] = 1  # nearly lapsed; a new use must renew it
    assert await worker._stored_conversation("ani.mallya") == "conv-1"
    assert redis.ttls[key] > 1, "reading the thread must renew the window"


# The model writes markdown for the web UI; an iMessage bubble renders none
# of it, so asterisks and hashes reached a real phone as noise. The
# flattener keeps every word and every address and loses only the syntax.
def test_markdown_is_flattened_for_the_bubble():
    from backend.workers.imessage_chat import plain_text

    reply = (
        "## Tonight\n\n"
        "There are **two** good options:\n\n"
        "- *Line dancing* at [BOE Clarendon](https://example.org/boe) — 7pm\n"
        "- Jazz at the `Bluebird`\n\n"
        "---\n"
        "```\ndetails here\n```\n"
        "Have fun!"
    )

    flat = plain_text(reply)

    for syntax in ("**", "##", "`"):
        assert syntax not in flat, flat
    assert "---" not in flat
    assert "• Line dancing at BOE Clarendon (https://example.org/boe) — 7pm" in flat
    assert "• Jazz at the Bluebird" in flat
    assert "two good options" in flat
    assert flat.endswith("Have fun!")


def test_plain_words_pass_through_untouched():
    from backend.workers.imessage_chat import plain_text

    assert plain_text("See you at 7pm - it should be fun!") == (
        "See you at 7pm - it should be fun!"
    )


# The slow-turn acknowledgment: a quick reply stays one bubble, a slow one
# gets "on it" first and the answer second - and losing the ack send must
# never lose the answer.
@pytest.mark.asyncio
async def test_a_slow_turn_gets_an_ack_then_the_answer(monkeypatch):
    import asyncio

    from backend.config.settings import settings
    from backend.workers.imessage_chat import _ACK_REPLIES

    monkeypatch.setattr(settings, "IMESSAGE_CHAT_ACK_SECONDS", 0.05)
    bridge = _Bridge(
        {"messages": [_message("g5", "7372025933", "deep question")], "cursor": 30}
    )
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"}, replies={}
    )

    async def slow(user_id, text):
        await asyncio.sleep(0.2)
        return TurnResult("a considered answer")

    monkeypatch.setattr(worker, "_converse", slow)

    await worker.tick()

    assert bridge.sent[0]["body"] in _ACK_REPLIES
    assert bridge.sent[1]["body"] == "a considered answer"
    assert len(bridge.sent) == 2


@pytest.mark.asyncio
async def test_a_quick_turn_stays_one_bubble(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "IMESSAGE_CHAT_ACK_SECONDS", 5.0)
    bridge = _Bridge(
        {"messages": [_message("g6", "7372025933", "hi")], "cursor": 31}
    )
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"},
        replies={"hi": "hello!"},
    )

    await worker.tick()

    assert [b["body"] for b in bridge.sent] == ["hello!"]


@pytest.mark.asyncio
async def test_a_failed_ack_send_never_costs_the_answer(monkeypatch):
    import asyncio

    from backend.config.settings import settings
    from backend.workers.imessage_chat import IMessageChatWorker

    monkeypatch.setattr(settings, "IMESSAGE_CHAT_ACK_SECONDS", 0.05)
    calls: list[str] = []

    async def bridge(tool, arguments):
        if tool == "read_messages":
            return json.dumps(
                {"messages": [_message("g7", "7372025933", "q")], "cursor": 32}
            )
        calls.append(arguments["body"])
        if len(calls) == 1:
            raise RuntimeError("ack refused")
        return json.dumps({"result": "sent"})

    worker = IMessageChatWorker(bridge, base_url="http://test", redis=_Redis())

    async def account_for(sender):
        return "ani.mallya"

    async def slow(user_id, text):
        await asyncio.sleep(0.2)
        return TurnResult("the answer")

    monkeypatch.setattr(worker, "_account_for", account_for)
    monkeypatch.setattr(worker, "_converse", slow)

    answered = await worker.tick()

    assert answered == 1
    assert calls[-1] == "the answer"


# A long reply arrives the way a person texts a long thought: a few bubbles
# split at paragraph bounds, short answers stay one, and the cap merges the
# tail rather than dropping it.
def test_a_long_reply_splits_at_paragraphs():
    from backend.workers.imessage_chat import bubbles

    reply = "\n\n".join(
        f"Paragraph {index} " + "words " * 40 for index in range(3)
    )

    pieces = bubbles(reply)

    assert len(pieces) == 3
    assert pieces[0].startswith("Paragraph 0")
    assert pieces[2].startswith("Paragraph 2")


def test_a_short_reply_stays_one_bubble():
    from backend.workers.imessage_chat import bubbles

    assert bubbles("See you at 7!") == ["See you at 7!"]


def test_the_bubble_cap_merges_the_tail_rather_than_dropping_it():
    from backend.workers.imessage_chat import _MAX_BUBBLES, bubbles

    reply = "\n\n".join("Part " + "x" * 400 for _ in range(7))

    pieces = bubbles(reply)

    assert len(pieces) == _MAX_BUBBLES
    assert "".join(pieces).count("Part") == 7, "nothing may be dropped"


# A picture the turn produced arrives as a photo bubble after the words,
# through the send tool's attachment fields.
@pytest.mark.asyncio
async def test_a_generated_image_is_sent_as_an_attachment(monkeypatch):
    from backend.workers.imessage_chat import TurnImage

    bridge = _Bridge(
        {"messages": [_message("g9", "7372025933", "draw me a fox")], "cursor": 40}
    )
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"}, replies={}
    )

    async def converse(user_id, text):
        return TurnResult(
            "Here's the image you asked for.",
            (TurnImage("art-1", "image/png", data_base64="aWJyaWRnZQ=="),),
        )

    monkeypatch.setattr(worker, "_converse", converse)

    answered = await worker.tick()

    assert answered == 1
    assert bridge.sent[0]["body"] == "Here's the image you asked for."
    photo = bridge.sent[1]
    assert photo["attachment_base64"] == "aWJyaWRnZQ=="
    assert photo["attachment_media_type"] == "image/png"
    assert photo["attachment_name"].endswith(".png")


# The picture is the message: a captionless photo row is a valid turn that
# goes down the photo path, and a row with neither text nor attachments is
# the only emptiness that skips.
@pytest.mark.asyncio
async def test_a_captionless_photo_is_a_valid_message(monkeypatch):
    message = {
        "guid": "g10",
        "sender": "7372025933",
        "reply_to": "+17372025933",
        "text": "",
        "sent_at": "2026-08-22T00:30:00Z",
        "attachments": [
            {
                "attachment_id": "att-1",
                "media_type": "image/jpeg",
                "name": "IMG_1.heic",
                "bytes": 120000,
            }
        ],
    }
    bridge = _Bridge({"messages": [message], "cursor": 50})
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"}, replies={}
    )
    photo_turns: list[tuple[str, str]] = []

    async def photo_turn(user_id, caption, attachments):
        photo_turns.append((user_id, caption))
        return TurnResult("A sunny trail through the woods.")

    monkeypatch.setattr(worker, "_photo_turn", photo_turn)

    answered = await worker.tick()

    assert answered == 1
    assert photo_turns == [("ani.mallya", "")]
    assert bridge.sent == [
        {"to": "+17372025933", "body": "A sunny trail through the woods."}
    ]
