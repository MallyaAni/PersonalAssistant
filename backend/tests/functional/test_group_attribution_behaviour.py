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


async def _propose(structured_llm, text: str, known_interests: tuple[str, ...] = ()):
    agent = MemoryProposalAgent(structured_llm)
    return (await agent.propose(text, known_interests, speaker="Ani", roster=ROSTER)).proposals


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


async def test_a_decision_made_together_is_the_groups_fact(structured_llm):
    # Deploy #9's sweep gap (2026-08-28): this exact sentence produced no
    # proposal, so the room forgot its own plan.
    for text in (
        "Scout, just so you know, we all settled on thai for friday dinner",
        "we're doing Thai on Friday at 7",
    ):
        proposals = await _propose(structured_llm, text)
        facts = [p for p in proposals if p["kind"] == "semantic_fact"]
        assert facts, (text, proposals)
        assert "the group" in _names(facts) or _names(facts) >= {"ani", "jen"}, (text, facts)
        copies = [owner for proposal in facts for owner, _ in _owned_copies(proposal, GROUP, ROOM)]
        assert GROUP in copies, (text, copies)
        assert "u-jen" not in copies and "u-sam" not in copies, (text, copies)


async def test_a_plan_survives_a_catalogue_that_already_lists_its_subject(structured_llm):
    """Deploy #20, 2026-08-28: with "Thai food" among the speaker's followed
    interests, the group's own plan was dropped 3 times in 6 - the model read
    the interest catalogue as "already known". Several runs, because the
    failure was intermittent."""
    captured = 0
    runs = 4
    for _ in range(runs):
        proposals = await _propose(structured_llm, "Scout, just so you know, we all settled on thai for friday dinner", ("Thai food",))
        captured += any(p["kind"] == "semantic_fact" for p in proposals)
    assert captured >= runs - 1, f"{captured}/{runs} captured with the catalogue"


async def test_us_and_we_are_the_group(structured_llm):
    for text in ("we're all into climbing these days", "let's meet at the usual place at 6 for us"):
        proposals = await _propose(structured_llm, text)
        if not proposals:
            continue
        assert "the group" in _names(proposals) or _names(proposals) >= {"jen", "sam"}, (text, proposals)
        copies = [owner for proposal in proposals for owner, _ in _owned_copies(proposal, GROUP, ROOM)]
        assert "u-jen" not in copies and "u-sam" not in copies, (text, copies)


async def test_a_fact_about_another_member_is_the_groups_with_its_source(structured_llm):
    # Measured 5/6 on 2026-08-28 (2/6 before the stray-space fix): the model
    # sometimes reads a remark about another person as nothing to keep. What
    # must never vary is where it lands when it is kept, so every capturing
    # run is checked and the rate is held at most one miss in four.
    captured = 0
    runs = 4
    for _ in range(runs):
        proposals = await _propose(structured_llm, "Jen hates cilantro, don't order anything with it")
        facts = [p for p in proposals if p["kind"] in {"semantic_fact", "episodic", "entity", "knowledge"}]
        assert not any(p["kind"] == "discovery_interests" and "cilantro" in " ".join(p.get("labels", [])) for p in proposals)
        if not facts:
            continue
        captured += 1
        assert "jen" in _names(facts), facts
        copies = [(owner, copy) for proposal in facts for owner, copy in _owned_copies(proposal, GROUP, ROOM)]
        assert all(owner == GROUP for owner, _ in copies), copies
        assert any("said by Ani" in str(copy.get("content") or "") for _, copy in copies), copies
    assert captured >= runs - 1, f"{captured}/{runs} captured"


async def test_a_question_captures_nothing(structured_llm):
    assert await _propose(structured_llm, "Scout, what does Jen like to eat?") == ()
