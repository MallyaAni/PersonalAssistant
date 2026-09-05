"""A turn that handed its remaining work to a run says so, and does not say
the whole request is done.

The loop records the hand-off - the steps completed this turn and why it
stopped - and `reply/handed_off` tells the reply model what that means. This
runs the real reply model on such a record and judges the answer on its
properties: it must report the completed step's result, must say the rest
is being finished in the background, and must not state or guess the
weather. The comfortable answer ("here's the ramen, and tonight will be
clear") is the one that is false.

pinned prompt: reply/handed_off.
"""

import asyncio

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.services.turn_steps import BUDGET
from backend.tests.functional.judge import _VERDICT_SCHEMA, _read

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_ASK = "find me a good ramen place near Davis Square and tell me if it'll rain tonight"


# The reply, given a record where the search was done and the weather was not.
async def _reply(llm) -> str:
    context = {
        "query": _ASK,
        "search": [
            {
                "title": "Yume Wo Katare - Davis Square",
                "url": "https://example.com/yume",
                "snippet": "Pork-heavy Jiro-style ramen; expect a line. 1923 Massachusetts Ave.",
            }
        ],
        "handed_off": {
            "run_id": "run-1",
            "steps_done": ["web search: ramen near Davis Square (1 results)"],
            "stopped": BUDGET,
        },
    }
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": _ASK})
    assert any("Handed off" in message["content"] for message in messages), "the record never reached the messages"
    answer = await asyncio.to_thread(llm.chat, messages, 300, None, 0.0)
    return str(answer.get("content") or "").strip()


# Ask the same model, constrained to a verdict, whether the reply has the
# property; wording is the model's, the property is ours.
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


async def test_a_handed_off_turn_reports_the_done_part_and_says_the_rest_continues(llm):
    held = 0
    replies = []
    verdicts = []
    for _ in range(3):
        reply = await _reply(llm)
        replies.append(reply)
        names_place = await _judged(
            llm,
            reply,
            "The reply names the ramen place that was found, Yume Wo Katare. "
            "Whether it says anything about the weather is irrelevant to this "
            "property.",
        )
        says_continuing = await _judged(
            llm,
            reply,
            "The reply says the weather part is still being worked on, will be "
            "finished in the background, or that the person will be told or "
            "updated about it later.",
        )
        no_weather_claim = await _judged(
            llm,
            reply,
            "The reply does NOT state or guess any weather outcome for tonight - "
            "no rain, clear, dry, temperature or forecast is given. Saying the "
            "weather is not yet known or is being checked counts as matching.",
        )
        verdicts.append((names_place, says_continuing, no_weather_claim))
        if names_place and says_continuing and no_weather_claim:
            held += 1
    assert held >= 2, (verdicts, replies)
