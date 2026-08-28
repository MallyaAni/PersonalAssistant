"""With a roster the memory agent is asked who each fact is about; without
one the call is exactly what it always was."""

import json

import pytest

from backend.memory.proposal_agent import MemoryProposalAgent


class _Llm:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def chat(self, messages, max_tokens, response_schema=None, temperature=0):
        self.calls.append({"messages": messages, "schema": response_schema})
        return {"content": json.dumps(self.payload)}


@pytest.mark.asyncio
async def test_a_group_turn_asks_about_and_stamps_it_on_every_proposal():
    llm = _Llm({"interests": ["hiking"], "semantic_fact": "Jen hates cilantro", "about": ["Jen"]})
    result = await MemoryProposalAgent(llm).propose("Jen hates cilantro", speaker="Ani", roster=("Ani", "Jen"))
    (call,) = llm.calls
    assert "about" in call["schema"]["properties"]
    system = call["messages"][0]["content"]
    assert "sent in a group chat by Ani" in system and "Ani, Jen" in system
    assert all(p["about"] == ["Jen"] for p in result.proposals)
    assert {p["kind"] for p in result.proposals} == {"discovery_interests", "semantic_fact"}


@pytest.mark.asyncio
async def test_a_direct_turn_is_unchanged():
    llm = _Llm({"semantic_fact": "My dog is Biscuit"})
    result = await MemoryProposalAgent(llm).propose("my dog is Biscuit")
    (call,) = llm.calls
    assert "about" not in call["schema"]["properties"]
    assert "group chat" not in call["messages"][0]["content"]
    assert result.proposals == ({"kind": "semantic_fact", "content": "My dog is Biscuit"},)


@pytest.mark.asyncio
async def test_blank_roster_names_are_dropped_from_about():
    llm = _Llm({"semantic_fact": "we're doing Thai on Friday", "about": ["the group", "  ", ""]})
    result = await MemoryProposalAgent(llm).propose("we're doing Thai on Friday", speaker="Ani", roster=("Ani", "Jen"))
    assert result.proposals[0]["about"] == ["the group"]
