"""Which saved facts are preferences, and which utterances are about the user at all.

A preference is stored with a purpose, and that purpose is what later selects
it for the result ranker - so a wrong label is not cosmetic, it decides what
colours a recommendation months from now.

Three ways it goes wrong, all found by measurement on 2026-08-30 and all
asserted below.

Labelling too little: "I only want places on the metro" is the whole reason
this exists.

Labelling something transient: a dry run over the 18 real stored memories
tagged "feeling a little tired today and wants something chill nearby" as a
preference. It reads like taste and stops being true by Tuesday, and acting
on it in a month would act on something false.

Storing the wrong subject entirely: "don't bother storing the whole
conversation, just summarize it" was captured and labelled a standing
preference - the 2026-08-24 over-capture again, wearing an imperative
instead of an argument. The prompt's work-at-hand rule had said "should
work" and the model read an instruction as addressed to itself either way.
An instruction is now read for what it constrains, and this file is what
keeps that; the measured rates, including where recall is still low on
terse directives, are recorded in prompts/memory/proposal.md.
"""

import pytest

from backend.core.dependencies import get_llm_client
from backend.memory.proposal_agent import MemoryProposalAgent

pytestmark = pytest.mark.asyncio


async def _proposal(said: str) -> dict:
    """The top proposal for one utterance, or an empty mapping if there is none."""
    result = await MemoryProposalAgent(get_llm_client()).propose(said)
    return dict(result.proposals[0]) if result.proposals else {}


# Standing constraints, said both ways a person says them: declared, and
# aimed at the assistant. Recall is asserted as a rate over the set, not per
# case - measured over four runs on 2026-08-30 these capture 7-9 of 10 each
# time, and single cases flake in both groups. A threshold of six catches a
# collapse (the machinery rule over-suppressing, a schema change dropping
# proposals) without failing on the model's ordinary variance.
CONSTRAINTS = [
    "I only want places I can get to on the metro, nothing needing a car.",
    "I can't stand loud bars, I never enjoy them.",
    "I'm vegetarian so keep that in mind for food recommendations.",
    "I'm allergic to peanuts, by the way.",
    "Don't suggest anything over $50.",
    "Keep it under $50, that's my limit.",
    "Don't bother with anything over about $50, that's my ceiling.",
    "Don't send me anywhere I need a car to reach.",
    "Don't recommend anywhere with loud music, I can't stand it.",
    "Please don't suggest seafood, I don't eat it.",
]


async def test_a_captured_constraint_is_always_labelled_a_preference(
    llm: object,
) -> None:
    # The property this file exists for, asserted with no tolerance: measured
    # over roughly forty captures, not one constraint came back as a plain
    # fact. A miss here means taste is stored where the ranker cannot find it.
    captured = []
    for said in CONSTRAINTS:
        top = await _proposal(said)
        if not top:
            continue
        captured.append(said)
        assert top.get("is_preference"), (
            f"stored where the ranker will not look: {said!r} -> {top.get('content')!r}"
        )
    assert len(captured) >= 6, (
        f"only {len(captured)} of {len(CONSTRAINTS)} constraints captured at all; "
        "measured range is 7-9, so this is a collapse rather than variance"
    )


# The transient cases. Each sounds like taste and expires anyway.
@pytest.mark.parametrize(
    "said",
    [
        "I'm feeling a little tired today and want something chill nearby.",
        "I'm pretty busy this week so keep it light.",
    ],
)
async def test_how_someone_feels_today_is_not_a_standing_preference(
    llm: object, said: str
) -> None:
    top = await _proposal(said)
    assert not top.get("is_preference"), f"a passing mood stored as standing: {top}"


# A plain fact is not a preference, or the label selects everything and the
# ranker is handed noise instead of taste.
@pytest.mark.parametrize(
    "said",
    [
        "I drive a Tesla Model 3.",
        "I keep my spare house key with the neighbour in flat three.",
    ],
)
async def test_a_plain_fact_is_not_labelled_a_preference(
    llm: object, said: str
) -> None:
    top = await _proposal(said)
    assert not top.get("is_preference"), f"a plain fact labelled a preference: {top}"


# The subject test, in the direction that actually shipped a defect. An
# instruction about this system's own workings is the work at hand: it is
# not a fact about the user, and it is certainly not a standing preference.
@pytest.mark.parametrize(
    "said",
    [
        "don't bother storing the whole conversation, just summarize it",
        "don't remember any of this",
        "the assistant should keep older conversations searchable instead of "
        "forgetting them",
    ],
)
async def test_an_instruction_about_the_machinery_stores_nothing(
    llm: object, said: str
) -> None:
    assert await _proposal(said) == {}, "a remark about the system was stored"
