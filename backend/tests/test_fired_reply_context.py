"""A reply to a fired reminder is read as an answer to it.

A task fires on its own conversation, deliberately never the person's live
one, so the live history holds nothing the person could be answering: "it
went great" arrived with no question in front of it. Delivery records the
bubble it sent and when; the turn uses that as the question only when it is
newer than anything in the live thread. A native long-press reply keeps
precedence, because it names the message exactly.
"""

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.services.conversation_service import _answering
from backend.workers.imessage_chat import (
    _LAST_REPLY_AT_KEY,
    _LAST_REPLY_KEY,
    IMessageChatWorker,
)


class _Redis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex=None, nx=False):
        self.store[key] = value
        return True


def _history(response: str, created_at: str) -> list[dict]:
    return [{"query": "earlier", "response": response, "created_at": created_at}]


# The fired reminder is newer than the thread's last turn, so it is the
# question: the thread moved on before the reminder fired.
def test_a_fired_reminder_newer_than_the_thread_is_the_question():
    metadata = {
        "previous_reply": "How did the interview go?",
        "previous_reply_at": "2026-11-04T18:00:00+00:00",
    }
    history = _history("Sure, here is a recipe.", "2026-11-04T12:00:00+00:00")
    assert _answering(metadata, history) == "How did the interview go?"


# The thread answered something after the delivery, so its own last response
# is the subject and the old reminder is stale.
def test_a_thread_turn_after_the_delivery_wins():
    metadata = {
        "previous_reply": "How did the interview go?",
        "previous_reply_at": "2026-11-04T18:00:00+00:00",
    }
    history = _history("Here is the diagram.", "2026-11-04T19:00:00+00:00")
    assert _answering(metadata, history) == "Here is the diagram."


# Nothing delivered and no native reply: the thread's own last response is
# all there is, exactly as before.
def test_without_a_delivery_the_threads_last_response_is_used():
    history = _history("Hello!", "2026-11-04T12:00:00+00:00")
    assert _answering({}, history) == "Hello!"


# An empty thread has no last response, so the delivered bubble is the only
# candidate.
def test_an_empty_thread_uses_the_delivered_bubble():
    metadata = {
        "previous_reply": "Time to stretch.",
        "previous_reply_at": "2026-11-04T18:00:00+00:00",
    }
    assert _answering(metadata, []) == "Time to stretch."


# A native long-press reply names the message precisely and beats both.
def test_a_native_reply_beats_the_delivered_bubble():
    metadata = {
        "replying_to": "The aqueduct diagram failed.",
        "previous_reply": "Time to stretch.",
        "previous_reply_at": "2026-11-04T18:00:00+00:00",
    }
    history = _history("Hello!", "2026-11-04T12:00:00+00:00")
    assert _answering(metadata, history) == "The aqueduct diagram failed."


# Delivery writes both keys together, and the worker reads the pair.
@pytest.mark.asyncio
async def test_the_last_delivery_reads_the_bubble_and_its_time():
    redis = _Redis()
    worker = IMessageChatWorker(lambda *_: None, base_url="http://test", redis=redis)
    redis.store[_LAST_REPLY_KEY.format(to="+15550100")] = "Time to stretch."
    redis.store[_LAST_REPLY_AT_KEY.format(to="+15550100")] = "1762280000.5"

    assert await worker._last_delivery("+15550100") == ("Time to stretch.", 1762280000.5)


# A half-written pair is a miss, not a guess.
@pytest.mark.asyncio
async def test_a_half_written_delivery_is_a_miss():
    redis = _Redis()
    worker = IMessageChatWorker(lambda *_: None, base_url="http://test", redis=redis)
    redis.store[_LAST_REPLY_KEY.format(to="+15550100")] = "Time to stretch."

    assert await worker._last_delivery("+15550100") is None


# The turn carries the delivered bubble and its time to the backend, which is
# where the comparison with the live thread happens.
@pytest.mark.asyncio
async def test_the_turn_metadata_carries_the_delivered_bubble(monkeypatch):
    import httpx

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text='event: delta\ndata: {"content": "ok"}\n\n')

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)
    redis = _Redis()
    worker = IMessageChatWorker(lambda *_: None, base_url="http://test", redis=redis)
    redis.store[_LAST_REPLY_KEY.format(to="+15550100")] = "How did the interview go?"
    redis.store[_LAST_REPLY_AT_KEY.format(to="+15550100")] = "1762280000.5"

    turn = await worker._converse("user-1", "it went great", reply_to="+15550100")

    assert turn.reply == "ok"
    assert seen["body"]["metadata"]["previous_reply"] == "How did the interview go?"
    assert seen["body"]["metadata"]["previous_reply_at"] == 1762280000.5


# A native reply carries only replying_to; the delivered bubble would be a
# second, weaker answer to the same question.
@pytest.mark.asyncio
async def test_a_native_reply_does_not_carry_the_delivered_bubble(monkeypatch):
    import httpx

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text='event: delta\ndata: {"content": "ok"}\n\n')

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)
    redis = _Redis()
    worker = IMessageChatWorker(lambda *_: None, base_url="http://test", redis=redis)
    redis.store[_LAST_REPLY_KEY.format(to="+15550100")] = "How did the interview go?"
    redis.store[_LAST_REPLY_AT_KEY.format(to="+15550100")] = "1762280000.5"

    await worker._converse(
        "user-1", "that one", replying_to="the aqueduct", reply_to="+15550100"
    )

    assert seen["body"]["metadata"]["replying_to"] == "the aqueduct"
    assert "previous_reply" not in seen["body"]["metadata"]
