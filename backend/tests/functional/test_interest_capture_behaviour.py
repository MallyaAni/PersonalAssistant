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


# A label the way it is compared here: lowercase, and with a hyphen read as
# the space it stands for. "stand-up comedy" and "stand up comedy" are one
# interest spelled two ways, and the model returns the hyphenated form
# deterministically - failing on that asserted the model's punctuation rather
# than the thing this file is about, which is whether a phrase was split.
# "stand up" or "comedy" alone still does not match, so the guard is intact.
def _label(text: str) -> str:
    return text.lower().replace("-", " ").strip()


def _interests(result: object) -> list[str]:
    labels: list[str] = []
    for proposal in result.proposals:  # type: ignore[attr-defined]
        if proposal.get("kind") == "discovery_interests":
            labels.extend(proposal.get("labels") or [])
    return [_label(label) for label in labels]


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
        assert _label(label) in found, f"{label!r} missing from {found!r}"


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


# The shape that actually polluted a real account: the subject matter of a
# working conversation. A user spent a day discussing infrastructure - a
# database engine, a caching layer, a coding project - and the classifier
# stored the tools as Scout interests, which a local-events agent then aims
# searches at. Discussing, building, asking about, or troubleshooting
# something states no interest, however long the conversation dwells on it.
@pytest.mark.parametrize(
    "said",
    [
        "Can we use the new database engine for the migration project?",
        "The caching layer is finally working properly now",
        "Let's finish setting up the deployment pipeline tomorrow",
        "I've been debugging the authentication service all day",
        "Does the smaller model fit on one machine for this project?",
        "Is the response time better with the rewrite we did?",
    ],
)
async def test_working_conversation_subject_matter_is_not_an_interest(
    llm: object, said: str
) -> None:
    assert _interests(await MemoryProposalAgent(get_llm_client()).propose(said)) == []


# The shape that actually fired, taken from a real polluted turn and
# generalised: first-person desire or action INSIDE the task at hand. "I'd
# like to use it for X", "I set it up on Y with Z" - six tool names from one
# such message became Scout interests. Wanting to do the work, or having done
# it, is the work; it states no standing pursuit.
@pytest.mark.parametrize(
    "said",
    [
        "I'd like to use it for editing like the professional tools and get "
        "great results. I set it up on a single workstation with the new "
        "toolkit and fast storage",
        "I want to get much better performance out of this configuration",
        "I set up the pipeline on the staging server with the new runtime",
        "I'd like to try the migration approach we discussed this weekend",
        # The aspiration register that actually fired on a real account:
        # wanting to use a setup for a task and get good at it reads as
        # enjoyment to the classifier, and once one interest fires the tools
        # named around it cascade into labels of their own.
        "I would like to use it for video editing like the professional "
        "studios and get amazing editing abilities. I set it up on a single "
        "workstation with the new capture card and fast storage on the big "
        "monitor",
    ],
)
async def test_first_person_task_intent_is_not_an_interest(
    llm: object, said: str
) -> None:
    assert _interests(await MemoryProposalAgent(get_llm_client()).propose(said)) == []


# The boundary that keeps the fix honest in both directions: a technical
# subject IS an interest when the user states it as an enjoyed pursuit. The
# discrimination is the stating of enjoyment, never the topic's domain -
# ruling out technology as such would be a topic blocklist, which is the
# keyword thinking this project forbids.
@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("I genuinely enjoy tinkering with home servers on weekends", "server"),
        ("I've gotten really into 3d printing lately", "3d printing"),
    ],
)
async def test_an_enjoyed_technical_pursuit_still_captures(
    llm: object, said: str, expected: str
) -> None:
    found = _interests(await MemoryProposalAgent(get_llm_client()).propose(said))
    assert any(expected in label for label in found), found
