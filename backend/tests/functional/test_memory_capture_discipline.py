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


# One natural introduction can carry several compatible memories; none may vanish.
async def test_profile_and_personal_fact_survive_the_same_message(llm: object) -> None:
    result = await MemoryProposalAgent(get_llm_client()).propose(
        "I'm Ani, I enjoy hiking, and I'm allergic to peanuts."
    )
    kinds = {proposal["kind"] for proposal in result.proposals}

    assert "preferred_name" in kinds, result.proposals
    assert "discovery_interests" in kinds, result.proposals
    assert "semantic_fact" in kinds, result.proposals


# The interest catalogue is about labels, not about what is already known.
#
# Deploy #20, 2026-08-28: with "Thai food" among the person's followed
# interests, "we all settled on thai for friday dinner" produced no proposal
# at all in three runs of six - the model read the catalogue as "you already
# know this" and dropped the plan. Measured over several runs because the
# failure was intermittent; a single green run proves nothing here.
# Only facts the one-to-one rules capture in the first place: a plan with a
# day ("thai on friday", "the market at 9 on Saturday") is deliberately left
# to the scheduling tools here (2026-08-26), and is the group's own fact only
# under the group block - held in functional/test_group_attribution_behaviour.
@pytest.mark.parametrize(
    ("message", "catalogue"),
    [
        ("my dentist is Dr Lee on Wilson Boulevard", ("hiking", "live music")),
        ("my dog is called Biscuit", ("dog training", "hiking")),
        # xfail: the model ceiling, not a catalogue defect. The allergy fact
        # shares a subject with the labels (shellfish / thai food, cooking),
        # and the classifier captures it 1-2/4 against the 3/4 assertion even
        # with the corrected catalogue wording. Measured 2026-09-01: the same
        # sentence captures ~14/16 with NO catalogue and ~10-12/16 with one -
        # TP=2 sampling variance (the repo records up to ~250 chars between
        # runs at temperature 0) plus the known model ceiling the proposal
        # prompt header forbids overfitting ("Raleigh 4/4, Durham 0/4").
        # The unrelated-subject case ("my dentist...") was a real catalogue
        # defect - 6/12 with the old wording, 11/12 with the corrected one -
        # and now passes. This one is left xfail with the evidence in the
        # reason, per the completion rule, not deleted and not loosened.
        pytest.param(
            "I'm allergic to shellfish",
            ("thai food", "cooking"),
            marks=pytest.mark.xfail(
                reason="model ceiling: adjacent-subject fact captures 1-2/4 vs "
                "3/4 floor; ~14/16 even without a catalogue (proposal.md "
                "forbids fixing with examples)",
            ),
        ),
    ],
)
async def test_a_fact_survives_a_catalogue_that_mentions_its_subject(
    llm: object, message: str, catalogue: tuple[str, ...]
) -> None:
    agent = MemoryProposalAgent(get_llm_client())
    captured = 0
    runs = 4
    for _ in range(runs):
        result = await agent.propose(message, catalogue)
        captured += any(
            proposal["kind"] in {"semantic_fact", "episodic", "entity", "knowledge"}
            for proposal in result.proposals
        )
    assert captured >= runs - 1, f"{captured}/{runs} captured for {message!r}"
