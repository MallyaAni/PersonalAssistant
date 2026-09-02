"""One statement in a room yields one saved fact, not two phrasings of it.

Live in the Groupie room (2026-09-02) "JenOS please remember that I am
female. Thanks!" was saved to each owner twice - "Jenos is female" and "User
is female" - because the classifier proposed both. Against the real
classifier and the real embedder: the two candidates still come out, and the
same-turn collapse keeps one.
"""
import pytest

from backend.core.dependencies import get_llm_client
from backend.memory.proposal_agent import MemoryProposalAgent
from backend.services.conversation_service import ConversationService

pytestmark = pytest.mark.asyncio


async def test_a_statement_in_a_room_is_one_fact_after_the_collapse(llm):
    result = await MemoryProposalAgent(get_llm_client()).propose(
        "JenOS please remember that I am female. Thanks!", speaker="Jen", roster=("Jen", "Ani")
    )
    facts = tuple(p for p in result.proposals if p.get("kind") == "semantic_fact")
    assert facts, result.proposals
    service = ConversationService.__new__(ConversationService)
    kept = await service._without_same_turn_duplicates(facts, "Jen")
    assert len(kept) == 1, [c.get("content") for c in kept]
    assert "female" in str(kept[0].get("content")).casefold()
