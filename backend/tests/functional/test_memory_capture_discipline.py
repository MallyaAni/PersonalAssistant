"""A statement about the system is not a memory about the user.

The 2026-08-24 23:52 incident: a rebuttal in a design discussion - the user
arguing how conversation history *should* be handled - was persisted as a
user_explicit semantic fact and answered with "noted and saved". The
classifier reads one message with no history, so the prompt's wording is the
only place this distinction can live: remarks about the assistant, its
memory, or the machinery under discussion propose nothing, while first-person
facts about the user's own life still do. The positive cases are the guard
against fixing the incident by capturing nothing at all.
"""

import pytest

from backend.core.dependencies import get_llm_client
from backend.memory.proposal_agent import MemoryProposalAgent

pytestmark = pytest.mark.asyncio


# The machinery under discussion, argued about, described, or corrected.
# The first is the verbatim turn that was mis-stored; the others are the same
# subject shape in different clothes, so the fix cannot be a phrase match.
@pytest.mark.parametrize(
    "remark",
    [
        "but conversation history will be summarized and important facts "
        "stored in memory",
        "the assistant is supposed to keep older conversations searchable "
        "instead of forgetting them",
        "if the context window overflows, older turns should get trimmed "
        "and the summary kept",
    ],
)
async def test_a_point_about_the_system_is_not_a_memory(
    llm: object, remark: str
) -> None:
    result = await MemoryProposalAgent(get_llm_client()).propose(remark)
    assert result.proposals == (), result.proposals


# The other side of the line: stable first-person facts about the user's own
# life must keep capturing, or the fix above merely traded one failure for a
# quieter one.
async def test_a_fact_about_the_user_s_own_life_still_captures(
    llm: object,
) -> None:
    result = await MemoryProposalAgent(get_llm_client()).propose(
        "I'm allergic to peanuts, by the way."
    )
    assert result.proposals, "a stated allergy must produce a proposal"
    assert "peanut" in str(result.proposals).casefold(), result.proposals


async def test_a_first_person_arrangement_still_captures(llm: object) -> None:
    result = await MemoryProposalAgent(get_llm_client()).propose(
        "I keep my spare house key with the neighbour in flat three."
    )
    assert result.proposals, "a stated arrangement must produce a proposal"
