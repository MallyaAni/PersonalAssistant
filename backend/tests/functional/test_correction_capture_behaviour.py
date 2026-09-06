"""A curt rejection of a suggestion is a preference about the person's own
life, and is captured as one; a rejection of the assistant's behaviour is not.

Live, 2026-09-05: "shut it with don titos , i don't care about that" proposed
nothing (0 of 3), read as an instruction to the assistant, and the reply
went on suggesting the place. This sends the phrasings that failed and the
ones that never did to the real classifier and asks for a stored preference
naming the place, while a remark about how the assistant replies still
fills nothing.

pinned prompt: memory/proposal (the rejection rule).
"""

import pytest

from backend.core.dependencies import get_llm_client
from backend.memory.proposal_agent import MemoryProposalAgent

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_PREVIOUS = "Alright, so patio it is. Don Tito's in Courthouse your typical go-to? If you want I can pull up what's on there tonight."


@pytest.mark.parametrize(
    "said",
    [
        "shut it with don titos , i don’t care about that",
        "stop suggesting don tito's, i only go there for salsa on wednesdays",
        "i hate don tito's except for salsa nights",
    ],
)
async def test_a_rejection_of_a_suggested_place_is_a_stored_preference(llm, said):
    hits = 0
    seen = []
    for _ in range(3):
        result = await MemoryProposalAgent(get_llm_client()).propose(said, previous_reply=_PREVIOUS)
        facts = [p for p in result.proposals if p.get("kind") == "semantic_fact"]
        seen.append(facts)
        if any(p.get("is_preference") and "tito" in str(p.get("content", "")).lower() for p in facts):
            hits += 1
    assert hits >= 2, seen


@pytest.mark.parametrize(
    "said",
    [
        "stop asking me follow-up questions every time",
        "don't summarise the conversation, just answer",
    ],
)
async def test_a_rejection_of_the_assistants_own_behaviour_still_fills_nothing(llm, said):
    misses = 0
    seen = []
    for _ in range(3):
        result = await MemoryProposalAgent(get_llm_client()).propose(said, previous_reply=_PREVIOUS)
        seen.append(result.proposals)
        if any(p.get("kind") == "semantic_fact" for p in result.proposals):
            misses += 1
    assert misses <= 1, seen
