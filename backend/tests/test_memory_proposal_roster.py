"""With a roster the memory agent is asked who each fact is about; without
one the call is exactly what it always was."""

import json

import pytest

from backend.memory.proposal_agent import MemoryProposalAgent


class _Llm:
    """Answers both questions a group turn asks: the ordinary decision and,
    when the prompt is the group one, the attribution decision."""

    def __init__(self, payload: dict, group_payload: dict | None = None) -> None:
        self.payload = payload
        self.group_payload = group_payload if group_payload is not None else payload
        self.calls: list[dict] = []

    def chat(self, messages, max_tokens, response_schema=None, temperature=0):
        system = messages[0]["content"]
        grouped = "group chat" in system
        self.calls.append({"messages": messages, "schema": response_schema, "grouped": grouped})
        return {"content": json.dumps(self.group_payload if grouped else self.payload)}


@pytest.mark.asyncio
async def test_a_group_turn_asks_a_second_question_and_stamps_who_it_is_about():
    # The ordinary decision keeps its own prompt; attribution is asked
    # separately, so group text can never crowd out ordinary capture.
    llm = _Llm(
        {"interests": ["hiking"]},
        {"semantic_fact": "Jen hates cilantro", "about": ["Jen"]},
    )
    result = await MemoryProposalAgent(llm).propose("Jen hates cilantro, and I love hiking", speaker="Ani", roster=("Ani", "Jen"))
    plain = next(call for call in llm.calls if not call["grouped"])
    grouped = next(call for call in llm.calls if call["grouped"])
    assert "about" not in plain["schema"]["properties"]
    assert "group chat" not in plain["messages"][0]["content"]
    assert "about" in grouped["schema"]["properties"]
    assert "sent in a group chat by Ani" in grouped["messages"][0]["content"] and "Ani, Jen" in grouped["messages"][0]["content"]
    # The ordinary interest survives, the group's fact about Jen is added,
    # and both say who they are about.
    assert {p["kind"] for p in result.proposals} == {"discovery_interests", "semantic_fact"}
    assert all(p["about"] == ["Jen"] for p in result.proposals)


@pytest.mark.asyncio
async def test_a_direct_turn_asks_one_question_and_is_unchanged():
    llm = _Llm({"semantic_fact": "My dog is Biscuit"})
    result = await MemoryProposalAgent(llm).propose("my dog is Biscuit")
    (call,) = llm.calls
    assert "about" not in call["schema"]["properties"]
    assert "group chat" not in call["messages"][0]["content"]
    # `is_preference` rides along with every semantic fact since 2026-08-30:
    # a preference is stored under its own purpose so a recommendation turn
    # can find it by kind, which embedding distance cannot do. `is_transient`
    # rides along since 2026-08-31 so a temporary state can be given a short
    # life and stop steering a weekly recommendation.
    assert result.proposals == (
        {
            "kind": "semantic_fact",
            "content": "My dog is Biscuit",
            "is_preference": False,
            "is_constraint": False,
            "is_transient": False,
        },
    )


@pytest.mark.asyncio
async def test_a_failed_attribution_call_leaves_the_ordinary_proposals():
    class _Flaky(_Llm):
        def chat(self, messages, max_tokens, response_schema=None, temperature=0):
            if "group chat" in messages[0]["content"]:
                raise RuntimeError("attribution model away")
            return super().chat(messages, max_tokens, response_schema, temperature)

    result = await MemoryProposalAgent(_Flaky({"semantic_fact": "I love hiking"})).propose(
        "I love hiking", speaker="Ani", roster=("Ani", "Jen")
    )
    # Unattributed: the owner rule reads that as the speaker's own words.
    assert result.proposals == (
        {
            "kind": "semantic_fact",
            "content": "I love hiking",
            "is_preference": False,
            "is_constraint": False,
            "is_transient": False,
            "about": [],
        },
    )


@pytest.mark.asyncio
async def test_blank_roster_names_are_dropped_from_about():
    llm = _Llm({"semantic_fact": "we're doing Thai on Friday"}, {"semantic_fact": "we're doing Thai on Friday", "about": ["the group", "  ", ""]})
    result = await MemoryProposalAgent(llm).propose("we're doing Thai on Friday", speaker="Ani", roster=("Ani", "Jen"))
    assert result.proposals[0]["about"] == ["the group"]
