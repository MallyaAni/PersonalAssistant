"""The proposal agent never writes Scout's schedule, and never reads facts
from the previous reply it is handed.

2026-08-26 21:28: "send another don tito reminder at 7" was captured as
the sweep's schedule (daily, hour 7) and applied. The fix is one writer:
the routed scout_schedule tool sets the cadence (test_scout_schedule_behaviour),
and this agent has no schedule field at all. These cases hold the line
from the agent's side: no phrasing of a time - reminder or sweep - yields
a schedule proposal, and the previous reply, supplied to resolve "this",
is never a source of facts.
"""

from __future__ import annotations

import pytest

from backend.core.dependencies import get_memory_proposal_agent

pytestmark = pytest.mark.asyncio

_SCOUT_REPLY = (
    "You mentioned the daily 7 AM Scout check when we set up your recurring "
    "events sweep. Let me know if you want to adjust the time or frequency."
)


def _kinds(result):
    return sorted(p["kind"] for p in result.proposals)


@pytest.mark.parametrize(
    "said",
    [
        "send another don tito reminder at 7",
        "remind me every day at 3pm to stretch",
        "text me the weather every morning at 8",
        "change scout to run daily at 3pm",
        "run my sweep weekly on Sunday mornings",
    ],
)
async def test_a_stated_time_is_never_a_memory(llm, said: str) -> None:
    result = await get_memory_proposal_agent().propose(said)
    assert "discovery_schedule" not in _kinds(result), (said, result.proposals)
    assert not any(
        "3" in str(p.get("value", "")) or "7" in str(p.get("value", ""))
        for p in result.proposals if p["kind"] == "semantic_fact"
    ), (said, result.proposals)


async def test_this_after_a_scout_reply_proposes_nothing(llm) -> None:
    result = await get_memory_proposal_agent().propose(
        "adjust this to daily at 3pm", previous_reply=_SCOUT_REPLY
    )
    assert result.proposals == (), result.proposals


async def test_the_previous_reply_is_never_a_source_of_facts(llm) -> None:
    result = await get_memory_proposal_agent().propose(
        "thanks",
        previous_reply="Your dentist is Dr. Lee on Wilson Blvd and you love swing dancing.",
    )
    assert result.proposals == (), result.proposals
