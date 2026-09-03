"""The reply knows what day it is. On 2026-09-03 a scheduled chess tip in a
group ended "have fun at trivia later!" the morning after their Wednesday
trivia, because the only time fact in the prompt was a bare date and the
recalled memory said "today". The prompt now carries the weekday and the
local time, a recalled memory carries the day it was noted, and a memory is
saved with its relative words written as dates. These send the real prompts
to the real reply model.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.agents.graph import _build_system_prompt, _build_turn_context
from backend.tests.functional.semantic import states

pytestmark = pytest.mark.asyncio

THURSDAY_MORNING = datetime(2026, 9, 3, 9, 0, tzinfo=ZoneInfo("America/New_York"))


def _context(memory: str) -> dict:
    return {
        "channel": "imessage_group",
        "scheduled_task": True,
        "local_now": THURSDAY_MORNING,
        "timezone": "America/New_York",
        "semantic": [{"content": memory, "created_at": "2026-09-02T09:23:08"}],
    }


def _reply(llm, context: dict, asked: str) -> str:
    system = _build_system_prompt(context)
    turn_context = _build_turn_context(context, include_save_state=False)
    result = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"{turn_context}\n\n{asked}"},
        ],
        300,
        None,
        0.0,
    )
    return str(result["content"])


@pytest.mark.parametrize(
    "memory",
    [
        "Ani and Jenos are going to trivia at Courthouse Social on Wednesday 2 September 2026; they go often. (said by Ani)",
        # The wording as it was saved before the fix: the noted day and the
        # weekday line alone must be enough.
        "Ani and Jenos are going to trivia at Courthouse Social today; they go often. (said by Ani)",
    ],
)
async def test_a_chess_tip_the_morning_after_trivia_does_not_wish_them_fun_at_trivia_later(llm, memory):
    text = _reply(llm, _context(memory), "send me a random beginner-friendly chess tip")
    assert states(text, "the reply gives a chess tip"), text
    assert not states(
        text,
        "the reply says or implies trivia is happening later today, tonight, or soon",
    ), text


async def test_asked_when_trivia_is_the_reply_knows_it_was_yesterday(llm):
    memory = "Ani and Jenos are going to trivia at Courthouse Social on Wednesday 2 September 2026; they go often. (said by Ani)"
    context = _context(memory)
    context["scheduled_task"] = False
    text = _reply(llm, context, "when is trivia?")
    assert states(text, "the reply says trivia was yesterday or on Wednesday 2 September, already past"), text
    assert not states(text, "the reply says trivia is today or later today"), text


# No saved place means no zone. The operator's rule (2026-09-03): the time
# comes from where the person is, and when that is not known, ask for it -
# but only when the answer turns on it.
async def test_with_no_known_place_a_tonight_question_asks_for_the_city(llm):
    context = {"channel": "imessage", "local_now": None, "timezone": ""}
    text = _reply(llm, context, "anything fun going on tonight?")
    assert states(text, "the reply asks which city or where the person is"), text


async def test_with_no_known_place_a_question_that_does_not_need_it_is_just_answered(llm):
    context = {"channel": "imessage", "local_now": None, "timezone": ""}
    text = _reply(llm, context, "what's a good opening for a beginner in chess?")
    assert states(text, "the reply answers the chess question"), text
    assert not states(text, "the reply asks where the person is or what city they are in"), text
