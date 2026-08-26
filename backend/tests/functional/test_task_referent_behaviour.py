"""Does "adjust this" pick the thing the assistant just named - and nothing when
that thing is not a task?

2026-08-26: after the assistant had mentioned Scout's daily check, "adjust
this to daily at 3pm" picked the person's stretch reminder - the only daily
task - and moved it. The picker now sees the previous reply; the reply,
asked "when did I say 7 am?", must not invent the conversation.
"""

from __future__ import annotations

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.core.dependencies import get_routing_llm_client
from backend.tasks.picker import pick_task
from backend.tests.functional.semantic import states

pytestmark = pytest.mark.asyncio

_TASKS = [
    {"id": "t-stretch", "instruction": "Remind me to stretch", "cadence": "daily", "hour": 18, "minute": 0, "timezone": "America/New_York"},
    {"id": "t-tito", "instruction": "Don Tito reminder tonight", "cadence": "once", "hour": 19, "minute": 0, "timezone": "America/New_York"},
]


async def test_this_after_a_scout_message_picks_no_task() -> None:
    llm = get_routing_llm_client()
    for _ in range(2):
        chosen = await pick_task(
            llm, "this", _TASKS,
            hint="You mentioned the daily 7 AM Scout check when we set up your events sweep. Let me know if you want to adjust the time.",
        )
        assert chosen is None, chosen


async def test_this_after_a_task_message_picks_that_task() -> None:
    llm = get_routing_llm_client()
    chosen = await pick_task(
        llm, "this", _TASKS,
        hint="Done - I've set a reminder about Don Tito's for tonight at 7:00 PM.",
    )
    assert chosen == "t-tito", chosen


async def test_the_reply_does_not_invent_what_the_person_said(llm) -> None:
    context = {"capabilities": []}
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.extend([
        {"role": "user", "content": "send another don tito reminder at 7"},
        {"role": "assistant", "content": "Done - I've set a reminder about Don Tito's for tonight at 7:00 PM."},
        {"role": "user", "content": "when did i say 7 am for scout?"},
    ])
    text = str(llm.chat(messages, 300, None, 0.0)["content"])
    assert not states(text, "The reply claims the user previously said or asked for 7 AM."), text
    assert states(text, "The reply says it cannot find or does not see the user having said that."), text
