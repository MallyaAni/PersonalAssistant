"""The proposal agent is handed the assistant's previous reply to resolve "this"."""

from __future__ import annotations

import json

import pytest

from backend.memory.proposal_agent import MemoryProposalAgent


class _LLM:
    def __init__(self) -> None:
        self.messages = None

    def chat(self, messages, max_tokens=1024, response_schema=None, temperature=None):
        self.messages = messages
        return {"content": json.dumps({"schedule": {"cadence": "daily", "hour": 15, "minute": 0, "weekday": 0}})}


@pytest.mark.asyncio
async def test_the_previous_reply_travels_labelled_as_a_referent_aid() -> None:
    llm = _LLM()
    result = await MemoryProposalAgent(llm).propose(
        "adjust this to daily at 3pm",
        previous_reply="You mentioned   the daily 7 AM Scout check.\n",
    )
    user = llm.messages[1]["content"]
    assert "never a source of facts: You mentioned the daily 7 AM Scout check." in user
    assert user.endswith("The user's current message: adjust this to daily at 3pm")
    assert result.proposals[0]["kind"] == "discovery_schedule"


@pytest.mark.asyncio
async def test_without_a_previous_reply_the_message_goes_alone() -> None:
    llm = _LLM()
    await MemoryProposalAgent(llm).propose("change scout to daily at 3pm")
    assert llm.messages[1]["content"] == "change scout to daily at 3pm"
