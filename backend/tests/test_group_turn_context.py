"""The room's identity line rides in the turn context, last, for group turns only."""

from backend.agents.graph import _build_turn_context, turn_context_messages
from backend.config.settings import settings

ROOM = {
    "channel": "imessage_group",
    "group": {
        "chat_name": "Groupie",
        "speaker_name": "Ani",
        "members": [{"user_id": "u-ani", "name": "Ani"}, {"user_id": "u-jen", "name": "Jen"}],
    },
}


def test_a_group_turn_says_who_is_speaking_at_the_end():
    text = _build_turn_context({**ROOM, "tool_notices": [{"tool": "get_weather", "reason": "x"}]})
    assert 'group chat "Groupie" and was sent by Ani - that is their name, known to you; the people in it are Ani, Jen' in text
    assert text.rstrip().endswith("superseded by what your instructions say now.")
    assert text.index("Tool notices") < text.index("was sent by Ani")


def test_a_direct_turn_carries_no_room_line():
    assert "was sent by" not in _build_turn_context({"channel": "imessage", "tool_notices": [{"tool": "x"}]})
    assert _build_turn_context({}) == ""


def test_the_line_reaches_the_message_after_the_history(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_CACHE_ORDERING", True)
    (message,) = turn_context_messages(ROOM)
    assert message["role"] == "user" and "was sent by Ani" in message["content"]
