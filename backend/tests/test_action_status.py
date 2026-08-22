"""The turn announces what it is doing, and the iMessage ack uses it."""

import asyncio
import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.config.settings import settings
from backend.services.conversation_service import ConversationService
from backend.tools import SearchAction, UseSkillAction
from backend.workers.imessage_chat import IMessageChatWorker, TurnResult


def test_a_routed_action_becomes_a_status_event_with_a_waiting_line():
    event = ConversationService._action_event(SearchAction("spark temps"))
    assert event is not None
    assert event["event"] == "action"
    assert event["data"]["label"] == "Web search"
    assert event["data"]["detail"] == "spark temps"
    assert event["data"]["waiting"].strip()
    assert ConversationService._action_event(None) is None


def test_a_skill_is_announced_by_name():
    event = ConversationService._action_event(
        None, {"id": "s1", "name": "morning brief"}
    )
    assert event["data"] == {
        "label": "Skill",
        "detail": "morning brief",
        "waiting": event["data"]["waiting"],
    }
    assert "morning brief" in event["data"]["waiting"]
    assert (
        ConversationService._action_event(UseSkillAction("s1", "morning brief", "x"))[
            "data"
        ]["detail"]
        == "morning brief"
    )


class _Bridge:
    def __init__(self):
        self.sent: list[dict] = []

    async def __call__(self, tool, arguments):
        self.sent.append(arguments)
        return {"status": "sent"}


# The ack bubble carries the tool's own waiting line when the backend named
# one before the threshold, and the generic pleasantry otherwise.
@pytest.mark.asyncio
async def test_the_slow_turn_ack_uses_the_announced_waiting_line(monkeypatch):
    monkeypatch.setattr(settings, "IMESSAGE_CHAT_ACK_SECONDS", 0.05)
    bridge = _Bridge()
    worker = IMessageChatWorker(bridge, base_url="http://backend:8000")
    status: list[str] = []

    async def slow_turn():
        status.append("🔎 Rummaging through the internet…")
        await asyncio.sleep(0.2)
        return TurnResult("72F", ())

    turn = await worker._with_ack(slow_turn(), "+15550001111", status)
    assert turn.reply == "72F"
    assert bridge.sent == [
        {"to": "+15550001111", "body": "🔎 Rummaging through the internet…"}
    ]

    bridge.sent.clear()

    async def slow_plain():
        await asyncio.sleep(0.2)
        return TurnResult("hi", ())

    await worker._with_ack(slow_plain(), "+15550001111", [])
    assert bridge.sent
    assert bridge.sent[0]["body"] != ""
    assert "Rummaging" not in bridge.sent[0]["body"]


@pytest.mark.asyncio
async def test_the_action_event_is_collected_from_the_stream():
    worker = IMessageChatWorker(_Bridge(), base_url="http://backend:8000")
    status: list[str] = []
    collected: list[str] = []
    await worker._consume_event(
        "u",
        "action",
        {"label": "Weather", "waiting": "🌤️ Peeking out the window…"},
        collected,
        [],
        status,
    )
    await worker._consume_event("u", "delta", {"content": "72F"}, collected, [], status)
    assert status == ["🌤️ Peeking out the window…"]
    assert collected == ["72F"]
