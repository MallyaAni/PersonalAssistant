"""The follow-up resolver's reading reaches the reply model: attached once, in
the context funnel every branch passes through, rendered last."""

from backend.agents.graph import _build_turn_context
from backend.services.conversation_service import _mark_turn
from backend.services.followup import Resolution, current_followup


def test_the_reading_is_attached_when_it_says_something_the_message_does_not():
    token = current_followup.set(Resolution("Which ice cream flavours do you think we'd like?", "subject", "ice cream"))
    try:
        context = {"query": "based on what you know about us what do you think we will like"}
        _mark_turn(context, {"channel": "imessage_group"}, None)
        assert context["followup"] == {
            "refers_to": "subject",
            "subject": "ice cream",
            "as": "Which ice cream flavours do you think we'd like?",
        }
    finally:
        current_followup.reset(token)


def test_a_reading_that_changes_nothing_is_not_attached():
    token = current_followup.set(Resolution("what's the capital of Peru?", "none", ""))
    try:
        context = {"query": "what's the capital of Peru?"}
        _mark_turn(context, {}, None)
        assert "followup" not in context
    finally:
        current_followup.reset(token)
    context = {"query": "hi"}
    _mark_turn(context, {}, None)
    assert "followup" not in context


def test_the_reading_is_rendered_last_in_the_turn_context():
    context = {
        "channel": "imessage_group",
        "group": {"chat_name": "Groupie", "speaker_name": "Ani", "members": [{"name": "Ani"}, {"name": "Jen"}]},
        "followup": {"refers_to": "subject", "subject": "ice cream", "as": "Which ice cream flavours do you think we'd like?"},
    }
    text = _build_turn_context(context)
    assert "the newest message means: Which ice cream flavours do you think we'd like?" in text
    assert "It is about ice cream" in text
    assert text.index("was sent by Ani") < text.index("the newest message means")
    assert _build_turn_context({"channel": "imessage"}) == ""
