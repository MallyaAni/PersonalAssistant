"""Is a reminder's time ever Scout's sweep schedule? And what does "this" mean?

2026-08-26 21:28: "send another don tito reminder at 7" was captured as the
sweep's schedule (daily, hour 7) and applied. Scout, which ran daily at
5 PM, was announced as a "daily 7 AM check"; "when did i say 7 am for
scout?" got an invented history; "adjust this to daily at 3pm" - a Scout
continuation - moved a stretch reminder instead. The schedule field now
means the sweep's own cadence, and the agent sees the previous reply so
"this" resolves to what was actually discussed.
"""

from __future__ import annotations

import pytest

from backend.core.dependencies import get_memory_proposal_agent

pytestmark = pytest.mark.asyncio

_SCOUT_REPLY = (
    "You mentioned the daily 7 AM Scout check when we set up your recurring "
    "events sweep. Let me know if you want to adjust the time or frequency."
)
_REMINDER_REPLY = "Done - I've set a reminder about Don Tito's for tonight at 7:00 PM."


def _schedule(result):
    return next((p for p in result.proposals if p["kind"] == "discovery_schedule"), None)


@pytest.mark.parametrize(
    "said",
    [
        "send another don tito reminder at 7",
        "remind me every day at 3pm to stretch",
        "set a reminder for salsa at don titos for every wednesday at 5pm",
        "text me the weather every morning at 8",
    ],
)
async def test_a_reminder_at_a_time_is_not_the_sweep_schedule(llm, said: str) -> None:
    result = await get_memory_proposal_agent().propose(said)
    assert _schedule(result) is None, (said, result.proposals)


async def test_the_sweep_s_own_schedule_still_captures(llm) -> None:
    result = await get_memory_proposal_agent().propose("change scout to run daily at 3pm")
    schedule = _schedule(result)
    assert schedule and schedule["cadence"] == "daily" and schedule["hour"] == 15, result.proposals


async def test_this_after_a_scout_reply_means_the_sweep(llm) -> None:
    result = await get_memory_proposal_agent().propose(
        "adjust this to daily at 3pm", previous_reply=_SCOUT_REPLY
    )
    schedule = _schedule(result)
    assert schedule and schedule["cadence"] == "daily" and schedule["hour"] == 15, result.proposals


async def test_this_after_a_reminder_reply_is_not_the_sweep(llm) -> None:
    result = await get_memory_proposal_agent().propose(
        "adjust this to daily at 3pm", previous_reply=_REMINDER_REPLY
    )
    assert _schedule(result) is None, result.proposals


async def test_the_previous_reply_is_never_a_source_of_facts(llm) -> None:
    result = await get_memory_proposal_agent().propose(
        "thanks",
        previous_reply="Your dentist is Dr. Lee on Wilson Blvd and you love swing dancing.",
    )
    assert result.proposals == (), result.proposals
