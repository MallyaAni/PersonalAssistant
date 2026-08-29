"""When a turn was said, in every place a conversation is shown to a model.

The failure, in a real group chat on 2026-08-29: a reminder was set on the
28th for "tonight at 9:00 PM" and fired that evening. The next afternoon the
assistant told the room "she's still getting her triple chocolate tonight".
The words were right there in the history - and nothing in the history said
how old they were, so "tonight" read as today's.

Everything needed was already in the database. `created_at` simply never left
it: the turn dict handed to every renderer had id, query, response and
metadata, and no time at all.
"""

from backend.agents.reply.nodes import assemble
from backend.services.conversation_service import _planner_history
from backend.services.followup import _recent
from backend.services.main_action_selector import render_recent_history
from backend.services.transcript import said_at, transcript_lines, user_content

EVENING = "2026-08-28T23:17:03+00:00"  # 7:17pm in New York, the 28th
EAST = "America/New_York"


def _turn(query: str, response: str = "", when: str | None = EVENING, name: str = "") -> dict:
    turn: dict = {"query": query, "response": response}
    if when:
        turn["created_at"] = when
    if name:
        turn["metadata"] = {"group": {"speaker_name": name}}
    return turn


def test_a_turn_is_stamped_in_the_readers_zone():
    # The whole point: 23:17 UTC is the previous evening in New York, and a
    # stamp on the wrong day would be worse than no stamp at all.
    assert said_at(_turn("x"), EAST) == "Fri 28 Aug 7:17pm"


def test_a_turn_with_no_zone_is_stamped_and_says_it_is_utc():
    assert said_at(_turn("x")) == "Fri 28 Aug 11:17pm UTC"


def test_a_turn_with_no_time_is_not_stamped_at_all():
    # Turns stored before 2026-08-29 have no created_at in their dict. They
    # must render exactly as they always did rather than gaining a wrong one.
    assert said_at(_turn("x", when=None)) == ""
    assert user_content(_turn("hello", when=None)) == "hello"
    assert said_at({"created_at": "not a time"}) == ""
    assert said_at({}) == ""


def test_the_reply_sees_the_stamp_beside_the_speaker():
    history = [_turn("you already know", "Reminder set for tonight at 9:00 PM", name="Ani")]
    state = {
        "history": history,
        "system_prompt": "sys",
        "query": "and Jen?",
        "context": {"timezone": EAST},
    }
    messages = assemble(state)["prompt_messages"]
    assert messages[1] == {
        "role": "user",
        "content": "[Fri 28 Aug 7:17pm] Ani: you already know",
    }
    # The assistant's own words are replayed unchanged - the stamp on the
    # question is what dates the exchange.
    assert messages[2]["content"] == "Reminder set for tonight at 9:00 PM"


def test_the_router_and_the_resolver_read_a_dated_transcript():
    history = [_turn("you already know", "Reminder set for tonight at 9:00 PM", name="Ani")]
    for rendered in (_recent(history, EAST), render_recent_history(history, EAST)):
        assert "[Fri 28 Aug 7:17pm] Ani: you already know" in rendered
        assert "[Fri 28 Aug 7:17pm] Assistant: Reminder set for tonight" in rendered


def test_the_search_planner_sees_it_too():
    assert _planner_history([_turn("what's on tonight", "here you go", name="Ani")], EAST)[0] == {
        "role": "user",
        "content": "[Fri 28 Aug 7:17pm] Ani: what's on tonight",
    }


def test_an_undated_conversation_renders_byte_for_byte_as_before():
    # The regression that would matter most: every existing prompt shape.
    history = [_turn("hello", "hi", when=None)]
    assert transcript_lines(history) == ["User: hello", "Assistant: hi"]
    assert _recent(history) == "User: hello\nAssistant: hi"
    assert render_recent_history(history) == "User: hello\nAssistant: hi"


def test_two_turns_from_different_days_are_distinguishable():
    # The exact shape of the failure: last night's plan and this afternoon's
    # question sitting in one window.
    history = [
        _turn("ice cream tonight?", "Reminder set for 9pm", name="Ani"),
        _turn("what's she getting", "chocolate", when="2026-08-29T18:10:00+00:00", name="Ani"),
    ]
    lines = transcript_lines(history, EAST)
    assert lines[0].startswith("[Fri 28 Aug 7:17pm]")
    assert lines[2].startswith("[Sat 29 Aug 2:10pm]")


def test_the_stamp_does_not_change_between_turns():
    # It is absolute, not relative ("Fri 28 Aug", never "yesterday"), because
    # the history prefix is cached verbatim between turns - measured at 16.5x
    # on a 34k conversation - and a stamp that re-rendered would throw that
    # away, and go stale at midnight besides.
    turn = _turn("x", name="Ani")
    assert user_content(turn, EAST) == user_content(turn, EAST)
    assert "yesterday" not in user_content(turn, EAST).casefold()
    assert "ago" not in user_content(turn, EAST).casefold()
