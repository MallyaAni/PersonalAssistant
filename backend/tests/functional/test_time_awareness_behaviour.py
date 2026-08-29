"""What the model says about a plan that has already happened.

The turn this replays went to a real group chat on 2026-08-29. A reminder had
been set the previous evening - "Done! Reminder set for tonight at 9:00 PM -
you and Jenos are both on the ice-cream run" - and it fired that night. The
next afternoon, asked something unrelated about Jen, the assistant answered
"She's still getting her triple chocolate tonight either way."

Nothing was hallucinated. The words "tonight at 9:00 PM" were sitting in the
history, and the history carried no times at all, so a sentence from last
night was indistinguishable from one said a minute ago. The fix is that every
stored turn is now dated where it is rendered
(`backend/services/transcript.py`), and the current time is already in front
of the model. This test is the part a structural test cannot reach: whether
the model, given the dates, actually uses them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.agents.graph import _build_system_prompt
from backend.agents.reply.nodes import assemble

pytestmark = pytest.mark.asyncio

EAST = "America/New_York"

# The room as it stood: the plan made on Friday evening, and the run itself.
YESTERDAY = [
    {
        "query": "remind me and jenos to grab ice cream tonight at 9",
        "response": "Done! Reminder set for tonight at 9:00 PM - you and Jenos are both on the ice-cream run.",
        "created_at": "2026-08-28T23:17:03+00:00",
        "metadata": {"group": {"speaker_name": "Ani"}},
    },
    {
        "query": "this is Jen. I am a HUGE chocolate fan, always the most chocolate possible",
        "response": "Got it, Jen - noted: you are a full-send chocolate person. Darkest triple-chocolate anything.",
        "created_at": "2026-08-29T04:26:13+00:00",
        "metadata": {"group": {"speaker_name": "Jenos"}},
    },
]

# Saturday afternoon, the moment the wrong answer was actually sent. Frozen,
# not read from the clock: this test asserts about "tonight", and a test whose
# meaning depends on the day it runs is not a test.
NOW = datetime(2026, 8, 29, 18, 10, tzinfo=UTC)
LOCAL_NOW = NOW.astimezone(ZoneInfo(EAST))


def _reply(llm, query: str, history: list[dict]) -> str:
    context = {
        "channel": "imessage_group",
        "query": query,
        "timezone": EAST,
        "place": "Arlington, Virginia",
        # A datetime, which is what the production context carries - a string
        # here would be silently ignored and the real clock used instead.
        "local_now": LOCAL_NOW,
    }
    state = {
        "history": history,
        "system_prompt": _build_system_prompt(context, now=LOCAL_NOW),
        "query": query,
        "context": context,
    }
    messages = assemble(state)["prompt_messages"]
    # The clock has to actually be in front of the model, or the two tests
    # below are measuring nothing.
    assert any("2026-08-29" in str(message.get("content")) for message in messages), messages
    return str(llm.chat(messages, 400, None, 0.0)["content"]).strip()


async def test_last_nights_plan_is_not_described_as_tonights(llm):
    answer = _reply(llm, "Ani: what is Jen getting again?", YESTERDAY)
    print(f"\n--- answer ---\n{answer}\n")
    lowered = answer.casefold()
    # The exact sentence that was sent: "She's still getting her triple
    # chocolate tonight either way."
    assert "chocolate" in lowered, answer
    assert "tonight" not in lowered, answer


async def test_a_plan_made_today_may_still_be_called_tonight(llm):
    # The other half, and the reason this is not just a banned word: a plan
    # made this morning for 9pm today IS tonight, and a model too timid to
    # say so has been made worse, not better.
    today = [
        {
            "query": "remind us to grab ice cream at 9 tonight",
            "response": "Done! Reminder set for tonight at 9:00 PM.",
            "created_at": "2026-08-29T13:40:00+00:00",
            "metadata": {"group": {"speaker_name": "Ani"}},
        }
    ]
    answer = _reply(llm, "Ani: when are we going again?", today)
    print(f"\n--- answer ---\n{answer}\n")
    assert "9" in answer, answer
    assert "tomorrow" not in answer.casefold(), answer


async def test_the_model_can_say_which_day_an_old_turn_was(llm):
    # The narrowest possible probe: does the stamp reach the model at all and
    # can it read it? If this fails, the two above are testing nothing.
    answer = _reply(llm, "Ani: what day did I set that ice cream reminder?", YESTERDAY)
    print(f"\n--- answer ---\n{answer}\n")
    lowered = answer.casefold()
    assert "friday" in lowered or "28" in lowered or "yesterday" in lowered, answer
