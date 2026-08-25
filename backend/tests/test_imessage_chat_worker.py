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

    async def converse(user_id: str, text: str, active_image=None, **_):
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

    async def slow(user_id, text, active_image=None, **_):
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
    bridge = _Bridge({"messages": [_message("g6", "7372025933", "hi")], "cursor": 31})
    worker, _ = _worker(
        bridge,
        monkeypatch,
        accounts={"7372025933": "ani.mallya"},
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

    async def slow(user_id, text, active_image=None, **_):
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

    reply = "\n\n".join(f"Paragraph {index} " + "words " * 110 for index in range(3))

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

    async def converse(user_id, text, active_image=None, **_):
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


# iCloud lazy-downloads attachments, so not_found for an id we just read
# from a listing is retryable; any other refusal is final and retries would
# only hammer a bridge that already said no.
@pytest.mark.asyncio
async def test_a_lazy_download_is_waited_out(monkeypatch):
    import backend.workers.imessage_chat as module

    monkeypatch.setattr(module, "_FETCH_RETRY_SECONDS", 0.01)
    worker = IMessageChatWorker(lambda *a: None, base_url="http://test", redis=_Redis())
    outcomes = ["not_found", "not_found", ("image/jpeg", "a.jpeg", "Zm9v")]

    async def once(attachment_id):
        return outcomes.pop(0)

    monkeypatch.setattr(worker, "_read_attachment_once", once)

    fetched = await worker._fetch_inbound_attachment("att-9")

    assert fetched == ("image/jpeg", "a.jpeg", "Zm9v")


@pytest.mark.asyncio
async def test_a_final_refusal_is_never_retried(monkeypatch):
    worker = IMessageChatWorker(lambda *a: None, base_url="http://test", redis=_Redis())
    calls: list[str] = []

    async def once(attachment_id):
        calls.append(attachment_id)
        return None

    monkeypatch.setattr(worker, "_read_attachment_once", once)

    assert await worker._fetch_inbound_attachment("att-10") is None
    assert calls == ["att-10"]


# The bridge's 5MB cap bounds what a compromised backend could pump through
# the Mac and is never negotiated with: an image that fits passes through
# byte-identical, one that does not is flattened to JPEG under the cap.
def test_an_oversized_image_is_reencoded_under_the_cap(monkeypatch):
    import io

    from PIL import Image

    import backend.workers.imessage_chat as module

    buffer = io.BytesIO()
    Image.new("RGBA", (64, 64), (200, 30, 30, 255)).save(buffer, format="PNG")
    png = buffer.getvalue()

    kept, kept_type = module._shrink_for_send(png, "image/png")
    assert (kept, kept_type) == (png, "image/png")

    monkeypatch.setattr(module, "_MAX_OUTBOUND_IMAGE_BYTES", 10)
    shrunk, shrunk_type = module._shrink_for_send(png, "image/png")
    assert shrunk_type == "image/jpeg"
    assert shrunk[:3] == b"\xff\xd8\xff", "must be a real JPEG"


# A worker killed mid-turn replays the message on restart: seen is marked
# after the delivery attempt, never at read time - a deploy landing during
# a generation burned a real request twice in one day.
@pytest.mark.asyncio
async def test_a_message_is_not_burned_until_delivery_was_attempted(monkeypatch):
    bridge = _Bridge(
        {"messages": [_message("g11", "7372025933", "draw something")], "cursor": 60}
    )
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"}, replies={}
    )

    async def killed(work, reply_to, *_):
        raise SystemExit("deploy landed mid-turn")

    monkeypatch.setattr(worker, "_with_ack", killed)

    with pytest.raises(SystemExit):
        await worker.tick()

    assert "imessage:chat:seen:g11" not in worker.redis.store, (
        "an unanswered message must stay replayable"
    )


# A camera original can be 48MP against the vision pipeline's 20MP limit,
# and the pipeline rejects rather than resizes - a real photo question
# bounced with "dimensions outside the accepted limit". The worker fits
# the image first; one already inside the limit passes through untouched.
def test_a_camera_original_is_fit_for_vision(monkeypatch):
    import io

    from PIL import Image

    import backend.workers.imessage_chat as module
    from backend.config.settings import settings

    buffer = io.BytesIO()
    Image.new("RGB", (300, 200), (10, 120, 200)).save(buffer, format="JPEG")
    small = buffer.getvalue()

    kept, kept_type = module._fit_for_vision(small)
    assert kept == small

    monkeypatch.setattr(settings, "IMAGE_MAX_PIXELS", 10_000)
    shrunk, shrunk_type = module._fit_for_vision(small)
    assert shrunk_type == "image/jpeg"
    with Image.open(io.BytesIO(shrunk)) as fitted:
        assert fitted.size[0] * fitted.size[1] <= 10_000


# A generated picture becomes the thread's picture-in-view, exactly as the
# web UI marks it active after display - without it, "what is happening in
# the background?" about a fresh image was answered with the agent roster.
@pytest.mark.asyncio
async def test_a_generated_image_becomes_the_threads_picture(monkeypatch):
    from backend.workers.imessage_chat import TurnImage

    bridge = _Bridge(
        {"messages": [_message("g12", "7372025933", "draw a bird")], "cursor": 70}
    )
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"}, replies={}
    )

    async def converse(user_id, text, active_image=None, **_):
        return TurnResult(
            "Here you go.",
            (TurnImage("art-7", "image/png", data_base64="Zm9v"),),
        )

    monkeypatch.setattr(worker, "_converse", converse)

    await worker.tick()

    assert worker.redis.store["imessage:chat:image:ani.mallya"] == "art-7", (
        "the generated picture must be in view for the follow-up question"
    )


# Reply-to targeting: a native reply to one of our image bubbles pins that
# image as the turn's target, overriding recency; an unknown or absent
# reply guid changes nothing. The ledger is written from the bridge's send
# answer when it carries a guid, and never from a plain "sent".
@pytest.mark.asyncio
async def test_a_reply_to_an_image_bubble_pins_that_image(monkeypatch):
    bridge = _Bridge(
        {
            "messages": [
                {
                    **_message("g13", "7372025933", "what's in the background?"),
                    "reply_to_guid": "ABCDEF01-2345-6789-ABCD-EF0123456789",
                }
            ],
            "cursor": 80,
        }
    )
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"}, replies={}
    )
    await worker._remember_bubble("ABCDEF01-2345-6789-ABCD-EF0123456789", "art-old")
    pinned: list[str | None] = []

    async def converse(user_id, text, active_image=None, **_):
        pinned.append(active_image)
        return TurnResult("It's a garden.")

    monkeypatch.setattr(worker, "_converse", converse)

    await worker.tick()

    assert pinned == ["art-old"]
    # Replying to it brings it back into view for the turns that follow.
    assert worker.redis.store["imessage:chat:image:ani.mallya"] == "art-old"


@pytest.mark.asyncio
async def test_a_plain_message_pins_nothing(monkeypatch):
    bridge = _Bridge(
        {"messages": [_message("g14", "7372025933", "hello")], "cursor": 81}
    )
    worker, _ = _worker(
        bridge, monkeypatch, accounts={"7372025933": "ani.mallya"}, replies={}
    )
    pinned: list[str | None] = []

    async def converse(user_id, text, active_image=None, **_):
        pinned.append(active_image)
        return TurnResult("hi!")

    monkeypatch.setattr(worker, "_converse", converse)

    await worker.tick()

    assert pinned == [None]


def test_the_poll_cadence_is_fast_only_just_after_activity():
    from backend.workers.imessage_chat import _poll_delay

    # Just answered → fast; well past the window → idle. This is what turns a
    # 5s average pickup into ~1.5s during a live back-and-forth without polling
    # the bridge hard when nobody is talking.
    assert _poll_delay(0.0, fast=1.5, slow=5.0, window=45.0) == 1.5
    assert _poll_delay(44.0, fast=1.5, slow=5.0, window=45.0) == 1.5
    assert _poll_delay(45.0, fast=1.5, slow=5.0, window=45.0) == 5.0
    assert _poll_delay(float("inf"), fast=1.5, slow=5.0, window=45.0) == 5.0


def test_the_bubble_ledger_only_stores_real_guids():
    from backend.workers.imessage_chat import _message_guid

    # A sentinel answer is not a guid and must not become a ledger key.
    assert _message_guid("sent with attachment") is None
    assert _message_guid("sent") is None
    # A real answer comes back as the identifier the ledger keys on.
    handle = "iMessage;-;ABCDEF01-2345-6789-ABCD-EF0123456789"
    assert _message_guid(handle) == handle


def test_a_reply_resolves_the_bubble_it_was_written_under():
    # The write form (send-answer, service-prefixed) and the read form (a
    # native reply's originator, association-prefixed) must reduce to one key,
    # or a reply silently never finds the picture it answers.
    from backend.workers.imessage_chat import _bare_guid

    guid = "ABCDEF01-2345-6789-ABCD-EF0123456789"
    assert _bare_guid(f"iMessage;-;{guid}") == guid
    assert _bare_guid(f"p:0/{guid}") == guid
    assert _bare_guid(guid) == guid
    assert _bare_guid("") == ""


# A diagram is SVG and the bridge's attachment allowlist rightly refuses
# it; the send path rasterizes it to PNG so the one artifact whose whole
# point is legible text is not the one a phone cannot see.
def test_a_diagram_svg_is_rasterized_for_the_bubble():
    import backend.workers.imessage_chat as module

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">'
        '<rect width="120" height="60" fill="white"/>'
        '<text x="10" y="35" font-size="20">Sprint</text></svg>'
    )

    content, media_type = module._shrink_for_send(svg.encode("utf-8"), "image/svg+xml")

    assert media_type == "image/png"
    assert content[:4] == b"\x89PNG"


# A picture in view expires on its own clock, and reading it does not
# renew it: an eight-hour-old photo rode into a conversation about
# something else and a bare "yes" was answered as if it confirmed that
# photo's question. Only an image event restarts the window.
@pytest.mark.asyncio
async def test_reading_the_picture_in_view_does_not_renew_it(monkeypatch):
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
    await worker._remember_image("ani.mallya", "art-1")
    key = "imessage:chat:image:ani.mallya"
    assert 0 < redis.ttls[key] <= 24 * 3600

    redis.ttls[key] = 1
    assert await worker._stored_image("ani.mallya") == "art-1"
    assert redis.ttls[key] == 1, "a read must not keep a stale picture alive"


# A medium reply is one bubble: 546 characters arrived as two near-equal
# halves that each read like a complete answer, and the person asked why
# it answered twice. Only a genuinely long reply is portioned.
def test_a_medium_reply_stays_one_bubble():
    from backend.workers.imessage_chat import bubbles

    reply = (
        ("Nice, that is the right cable. " * 9)
        + "\n\n"
        + ("And one more thing to check. " * 9)
    )
    assert 400 < len(reply) < 800
    assert len(bubbles(reply)) == 1


# Messages carries every photo of a burst on one row. Each is answered in
# order and numbered, the last becomes the picture in view, and one photo
# that has not finished downloading does not cost the others their answer.
@pytest.mark.asyncio
async def test_a_burst_of_photos_is_answered_photo_by_photo(monkeypatch):
    worker = IMessageChatWorker(lambda *a: None, base_url="http://test", redis=_Redis())
    remembered: list[str] = []

    async def stored_conversation(user_id):
        return "conv-1"

    async def remember_image(user_id, artifact_id):
        remembered.append(artifact_id)

    async def remember_conversation(user_id, conversation):
        return None

    async def analyze(user_id, caption, attachment, conversation):
        if attachment["attachment_id"] == "att-2":
            return "That photo hasn't finished downloading on my end yet - send it again in a minute?", ""
        return f"seen {attachment['attachment_id']}", f"art-{attachment['attachment_id']}"

    monkeypatch.setattr(worker, "_stored_conversation", stored_conversation)
    monkeypatch.setattr(worker, "_remember_image", remember_image)
    monkeypatch.setattr(worker, "_remember_conversation", remember_conversation)
    monkeypatch.setattr(worker, "_analyze_photo", analyze)

    turn = await worker._photo_turn(
        "ani.mallya",
        "",
        [{"attachment_id": "att-1"}, {"attachment_id": "att-2"}, {"attachment_id": "att-3"}],
    )

    assert turn.reply.split("\n\n") == [
        "Picture 1: seen att-1",
        "Picture 2: That photo hasn't finished downloading on my end yet - send it again in a minute?",
        "Picture 3: seen att-3",
    ]
    assert remembered == ["art-att-3"], "the last photo that arrived is the picture in view"


@pytest.mark.asyncio
async def test_a_single_photo_is_answered_without_numbering(monkeypatch):
    worker = IMessageChatWorker(lambda *a: None, base_url="http://test", redis=_Redis())

    async def stored_conversation(user_id):
        return "conv-1"

    async def analyze(user_id, caption, attachment, conversation):
        return "a sunny trail", ""

    monkeypatch.setattr(worker, "_stored_conversation", stored_conversation)
    monkeypatch.setattr(worker, "_analyze_photo", analyze)

    turn = await worker._photo_turn("ani.mallya", "what is this?", [{"attachment_id": "att-1"}])

    assert turn.reply == "a sunny trail"


# Only so many photos per message are looked at; the rest are named rather
# than silently dropped.
@pytest.mark.asyncio
async def test_photos_past_the_cap_are_named_not_dropped(monkeypatch):
    import backend.workers.imessage_chat as module

    monkeypatch.setattr(module, "_MAX_PHOTOS_PER_MESSAGE", 2)
    worker = IMessageChatWorker(lambda *a: None, base_url="http://test", redis=_Redis())

    async def stored_conversation(user_id):
        return "conv-1"

    async def analyze(user_id, caption, attachment, conversation):
        return f"seen {attachment['attachment_id']}", ""

    monkeypatch.setattr(worker, "_stored_conversation", stored_conversation)
    monkeypatch.setattr(worker, "_analyze_photo", analyze)

    turn = await worker._photo_turn(
        "ani.mallya", "", [{"attachment_id": f"att-{n}"} for n in range(1, 4)]
    )

    assert turn.reply.endswith(
        "I looked at the first 2 - send the rest separately if you want those described too."
    )
