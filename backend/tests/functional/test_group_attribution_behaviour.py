"""Who a fact said in a group is about, on the real routing model - and
whose memory it therefore lands in.

Pins prompts/memory/proposal_group.md. "Jen and I", "us", "we're all" are
read for meaning, never matched; and a fact about another member is the
group's knowledge with its source, never a write into that member's memory.
"""

from __future__ import annotations

import pytest

from backend.memory.proposal_agent import MemoryProposalAgent
from backend.services.conversation_service import _owned_copies

pytestmark = pytest.mark.asyncio

ROSTER = ("Ani", "Jen", "Sam")
ROOM = {
    "speaker_user_id": "u-ani",
    "speaker_name": "Ani",
    "members": [{"user_id": "u-ani", "name": "Ani"}, {"user_id": "u-jen", "name": "Jen"}, {"user_id": "u-sam", "name": "Sam"}],
}
GROUP = "group:test"


def _names(proposals) -> set[str]:
    return {name.casefold() for proposal in proposals for name in proposal.get("about", [])}


async def _propose(structured_llm, text: str):
    agent = MemoryProposalAgent(structured_llm)
    return (await agent.propose(text, speaker="Ani", roster=ROSTER)).proposals


async def test_a_members_own_statement_is_about_the_speaker(structured_llm):
    proposals = await _propose(structured_llm, "I love hiking, honestly it's my favourite thing")
    assert proposals, "an interest was expected"
    assert _names(proposals) <= {"ani", "me"}, proposals
    owners = {owner for proposal in proposals for owner, _ in _owned_copies(proposal, GROUP, ROOM)}
    assert "u-ani" in owners and "u-jen" not in owners and "u-sam" not in owners


async def test_jen_and_i_is_about_both_not_the_speaker_alone(structured_llm):
    proposals = await _propose(structured_llm, "Jen and I are doing Thai on Friday at 7")
    assert proposals, "a plan was expected"
    names = _names(proposals)
    assert names & {"jen", "the group"}, proposals
    copies = [owner for proposal in proposals for owner, _ in _owned_copies(proposal, GROUP, ROOM)]
    assert "u-jen" not in copies, "Jen's memory must never be written on Ani's word"
    assert GROUP in copies
    # Ani's own share of the plan is Ani's too, when the agent names Ani.
    if "ani" in names:
        assert "u-ani" in copies


async def test_us_and_we_are_the_group(structured_llm):
    for text in ("we're all into climbing these days", "let's meet at the usual place at 6 for us"):
        proposals = await _propose(structured_llm, text)
        if not proposals:
            continue
        assert "the group" in _names(proposals) or _names(proposals) >= {"jen", "sam"}, (text, proposals)
        copies = [owner for proposal in proposals for owner, _ in _owned_copies(proposal, GROUP, ROOM)]
        assert "u-jen" not in copies and "u-sam" not in copies, (text, copies)


async def test_a_fact_about_another_member_is_the_groups_with_its_source(structured_llm):
    proposals = await _propose(structured_llm, "Jen hates cilantro, don't order anything with it")
    facts = [p for p in proposals if p["kind"] in {"semantic_fact", "episodic", "entity", "knowledge"}]
    assert facts, proposals
    assert "jen" in _names(facts), facts
    copies = [(owner, copy) for proposal in facts for owner, copy in _owned_copies(proposal, GROUP, ROOM)]
    assert all(owner == GROUP for owner, _ in copies), copies
    assert any("said by Ani" in str(copy.get("content") or "") for _, copy in copies), copies
    assert not any(p["kind"] == "discovery_interests" and "cilantro" in " ".join(p.get("labels", [])) for p in proposals)


async def test_a_question_captures_nothing(structured_llm):
    assert await _propose(structured_llm, "Scout, what does Jen like to eat?") == ()
