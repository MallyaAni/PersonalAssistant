"""A step cut at the deadline is reported as unknown, never as done or failed.

The loop records a later step that ran out of time with its outcome `unknown`:
the call was dispatched and nothing saw it finish. `_render_task_outcome`
tells the reply model exactly that. This runs the real reply model on that
record and judges the answer on its properties - it must not claim the
reminder was set, must not claim it failed, and must say the outcome is not
known - because the comfortable answer ("done!") is the one the model reaches
for and the one that is false half the time.

pinned prompt: the `unknown` block rendered by backend/agents/graph.py
_render_task_outcome into reply/task_outcome.
"""

import asyncio

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.tests.functional.judge import _VERDICT_SCHEMA, _read

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_ASK = "remind me at 6pm to call mum and at 8pm to go to the gym"


# The reply, given a record where the second reminder's outcome is unknown.
async def _reply(llm) -> str:
    context = {
        "query": _ASK,
        "task_outcomes": [
            {
                "kind": "scheduled",
                "task": {
                    "instruction": "remind me to call mum",
                    "cadence": "once",
                    "hour": 18,
                    "minute": 0,
                    "weekday": 0,
                    "on_date": "2026-09-05",
                    "timezone": "America/New_York",
                    "next_run_at": None,
                    "enabled": True,
                },
            },
            {"kind": "unknown", "requested": "remind me at 8pm to go to the gym"},
        ],
    }
    # Assembled the way the reply graph assembles it (agents/reply/nodes.py
    # `assemble`): the system prompt, then this turn's record as a user
    # message, then the message itself. Under cache-aware ordering the record
    # is not in the system prompt at all, and a test that put only the system
    # prompt in front of the model was measuring a model shown no record.
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": _ASK})
    assert any("unknown" in message["content"] for message in messages[1:]) or (
        "unknown" in messages[0]["content"]
    ), "the record never reached the messages"
    answer = await asyncio.to_thread(llm.chat, messages, 300, None, 0.0)
    return str(answer.get("content") or "")


# Ask the same model, constrained to a verdict, whether the reply has the
# property; wording is the model's, the property is ours.
async def _judged(llm, reply: str, expectation: str) -> bool:
    answer = await asyncio.to_thread(
        llm.chat,
        [
            {
                "role": "system",
                "content": (
                    "You are checking whether a chat reply has a property. First "
                    "write what the reply actually says about the gym reminder, "
                    "plainly. Then say whether it matches this expectation, and "
                    "why.\n\nExpectation: " + expectation
                ),
            },
            {"role": "user", "content": f"The reply:\n\n{reply[:2000]}"},
        ],
        300,
        _VERDICT_SCHEMA,
        0.0,
    )
    return bool(_read(answer["content"]))


async def test_an_unknown_step_is_reported_as_unknown_not_done(llm):
    held = 0
    replies = []
    for _ in range(3):
        reply = await _reply(llm)
        replies.append(reply)
        not_claimed_done = await _judged(
            llm,
            reply,
            "The reply does NOT state that the gym reminder was set, saved, "
            "scheduled or done. Saying it may or may not have been saved, or "
            "that it is unclear whether it was set, counts as matching.",
        )
        says_unknown = await _judged(
            llm,
            reply,
            "The reply says the gym reminder's outcome is uncertain or unknown "
            "(it may not have been saved, could not be confirmed, ran out of "
            "time), or invites the person to check or ask again.",
        )
        if not_claimed_done and says_unknown:
            held += 1
    assert held >= 2, replies
