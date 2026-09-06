"""A weekly reminder is not a standing preference.

Live, 2026-09-05: asked "what do I do this evening? I'm bored", the reply
said "salsa at Don Tito's is your usual move" to a person who had set a
Wednesday reminder for salsa there and hates the place otherwise. The
history the model saw held that reminder's firings, each stored as the
person's own line. The transcript now marks a firing as a firing; this
sends the real history shape to the real reply model and judges that the
answer does not present the place as their habit, preference or go-to.

pinned prompt: the firing note written by backend/services/transcript.py
into every rendering of history (user_content, transcript_lines).
"""

import asyncio

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.services.transcript import user_content
from backend.tests.functional.judge import _VERDICT_SCHEMA, _read

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_ASK = "what do i do this evening? i'm bored"


def _firing(day: str) -> dict:
    return {
        "query": "Remind me about salsa at Don Tito's",
        "response": "Salsa night at Don Tito's is today - it's on your Wednesday 5pm schedule. Have fun!",
        "metadata": {"channel": "imessage", "scheduled_task": {"id": "t1"}},
        "created_at": f"2026-{day}T21:00:00+00:00",
    }


_HISTORY = [
    _firing("08-19"),
    _firing("08-26"),
    {"query": "when am i going to italy?", "response": "You fly out October 2, one-way to Rome.", "metadata": {"channel": "imessage"}, "created_at": "2026-09-04T01:02:00+00:00"},
    _firing("09-02"),
]


async def _reply(llm) -> str:
    context = {"query": _ASK}
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    for turn in _HISTORY:
        messages.append({"role": "user", "content": user_content(turn)})
        messages.append({"role": "assistant", "content": turn["response"]})
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": _ASK})
    answer = await asyncio.to_thread(llm.chat, messages, 300, None, 0.0)
    return str(answer.get("content") or "").strip()


async def _judged(llm, reply: str, expectation: str) -> bool:
    answer = await asyncio.to_thread(
        llm.chat,
        [
            {
                "role": "system",
                "content": (
                    "You are checking whether a chat reply has one property. First "
                    "write what the reply actually says, plainly. Then say whether "
                    "it has this one property - judge nothing beyond it - and why."
                    "\n\nProperty: " + expectation
                ),
            },
            {"role": "user", "content": f"The reply:\n\n{reply[:2000]}"},
        ],
        300,
        _VERDICT_SCHEMA,
        0.0,
    )
    return bool(_read(answer["content"]))


async def test_a_weekly_reminder_is_not_presented_as_their_habit(llm):
    held = 0
    replies = []
    for _ in range(3):
        reply = await _reply(llm)
        replies.append(reply)
        not_a_habit = await _judged(
            llm,
            reply,
            "The reply does NOT present Don Tito's as the person's usual, regular, "
            "favourite or go-to place, and does not assume they want to go there "
            "tonight. Mentioning that a salsa reminder exists for Wednesdays, or "
            "not mentioning Don Tito's at all, counts as matching.",
        )
        if not_a_habit:
            held += 1
    assert held >= 2, replies
