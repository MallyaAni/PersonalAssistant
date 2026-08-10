"""An interest must survive the way people actually phrase it.

Capture is the only path by which Scout learns what someone cares about, and it
fails silently: an interest the model does not propose is never offered, never
approved, and leaves no trace that anything was missed. The user's report was
"approved saving in memory but it didn't automatically add into scout" — the
half of that failure which lives here is the half where nothing was ever
proposed.

The prompt already says not to depend on trigger words. Measured against the
running model it did: "I love woodworking" produced the interest and "I am into
woodworking" produced nothing, as did "I am a big fan of jazz". These fix the
phrasings rather than the sentences, so the next rewrite of the prompt cannot
quietly narrow them back down to the examples it happens to list.
"""

import pytest

from backend.core.dependencies import get_llm_client
from backend.memory.proposal_agent import MemoryProposalAgent

pytestmark = pytest.mark.asyncio


def _interests(result: object) -> list[str]:
    labels: list[str] = []
    for proposal in result.proposals:  # type: ignore[attr-defined]
        if proposal.get("kind") == "discovery_interests":
            labels.extend(proposal.get("labels") or [])
    return [label.lower() for label in labels]


# Every one of these says the same thing about the same person. None of them is
# unusual, and none is a trigger phrase.
@pytest.mark.parametrize(
    "phrasing",
    [
        "I love woodworking",
        "I am into woodworking",
        "I'm into woodworking",
        "I am really into woodworking",
        "I am a big fan of woodworking",
        "I enjoy woodworking",
        "woodworking is my thing",
        "I have gotten into woodworking lately",
        "I do a lot of woodworking",
        "woodworking is a hobby of mine",
    ],
)
async def test_an_interest_survives_the_way_it_is_phrased(
    llm: object, phrasing: str
) -> None:
    agent = MemoryProposalAgent(get_llm_client())
    assert "woodworking" in _interests(await agent.propose(phrasing))


# Two interests in one sentence stay two, and a phrase stays whole. The stored
# "Social" and "Network" on a real account are what a split looks like after the
# fact, and nothing about them says they were ever one phrase.
@pytest.mark.parametrize(
    ("said", "expected"),
    [
        (
            "I am into swing dancing and rock climbing",
            ["swing dancing", "rock climbing"],
        ),
        (
            "I am into machine learning and craft beer",
            ["machine learning", "craft beer"],
        ),
        ("I follow Formula 1 and stand up comedy", ["formula 1", "stand up comedy"]),
    ],
)
async def test_a_multi_word_interest_is_one_label(
    llm: object, said: str, expected: list[str]
) -> None:
    found = _interests(await MemoryProposalAgent(get_llm_client()).propose(said))
    for label in expected:
        assert label in found, f"{label!r} missing from {found!r}"


# The other half of the judgement, kept here so a prompt loosened to catch the
# phrasings above cannot pass by proposing everything.
@pytest.mark.parametrize(
    "said",
    [
        "What is my dog called?",
        "My wife loves pottery",
        "Do you think I would like woodworking?",
        "My dog is called Biscuit",
    ],
)
async def test_what_is_not_the_user_s_own_interest_is_not_captured(
    llm: object, said: str
) -> None:
    assert _interests(await MemoryProposalAgent(get_llm_client()).propose(said)) == []
