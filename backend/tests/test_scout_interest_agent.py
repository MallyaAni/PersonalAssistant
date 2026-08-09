import json

import pytest

from backend.memory.interest_agent import ScoutInterestProposalAgent


class _DecisionLLM:
    """Return one configured grammar-valid classifier decision."""

    # Store the decision and capture the request for boundary assertions.
    def __init__(self, decision: dict[str, object]) -> None:
        self.decision = decision
        self.calls: list[dict[str, object]] = []

    # Mimic the provider-neutral structured chat boundary.
    def chat(
        self,
        messages,
        max_tokens=1024,
        response_schema=None,
        temperature=None,
    ):
        self.calls.append(
            {
                "messages": messages,
                "max_tokens": max_tokens,
                "response_schema": response_schema,
                "temperature": temperature,
            }
        )
        return {"content": json.dumps(self.decision)}


# Understand the exact natural-language list entered by testuser.
@pytest.mark.asyncio
async def test_semantic_agent_extracts_each_explicit_interest() -> None:
    llm = _DecisionLLM(
        {
            "explicit": True,
            "interests": ["basketball", "soccer", "baseball", "hiking"],
        }
    )

    proposal = await ScoutInterestProposalAgent(llm).propose(
        "My interests are basketball, soccer, baseball, hiking"
    )

    assert proposal is not None
    assert proposal.labels == ("basketball", "soccer", "baseball", "hiking")
    assert llm.calls[0]["temperature"] == 0
    assert llm.calls[0]["response_schema"]["properties"]["explicit"]


# Keep semantic understanding approval-gated and reject model inference.
@pytest.mark.asyncio
async def test_semantic_agent_returns_no_proposal_without_explicit_user_intent() -> (
    None
):
    llm = _DecisionLLM({"explicit": False, "interests": []})

    proposal = await ScoutInterestProposalAgent(llm).propose(
        "What sports are popular near me?"
    )

    assert proposal is None


# Normalize and deduplicate model labels before they reach an approval card.
@pytest.mark.asyncio
async def test_semantic_agent_bounds_and_deduplicates_labels() -> None:
    llm = _DecisionLLM(
        {
            "explicit": True,
            "interests": [" Live   Jazz ", "live jazz", "Hiking"],
        }
    )

    proposal = await ScoutInterestProposalAgent(llm).propose("I love jazz and hiking.")

    assert proposal is not None
    assert proposal.labels == ("Live Jazz", "Hiking")


# --- not filling the profile with the same interest four times ----------------
#
# One message naming three kinds of theater produced "Community Theater",
# "Professional Theater" and "Musical Theater" beside an existing "Theater".
# Relevance then names a matched interest only when the best beats the runner-up
# by a margin, and interests that close sit on top of each other — so no theater
# event could ever clear it and every one was reported with no reason at all.


def _system_prompt(llm: _DecisionLLM) -> str:
    return str(llm.calls[0]["messages"][0]["content"])


@pytest.mark.asyncio
async def test_what_the_user_already_follows_is_given_to_the_model() -> None:
    llm = _DecisionLLM({"explicit": True, "interests": ["Theater"]})

    await ScoutInterestProposalAgent(llm).propose(
        "I love musical theater", ("Theater", "Books")
    )

    prompt = _system_prompt(llm)
    assert '"Theater"' in prompt
    assert '"Books"' in prompt
    # Told what to do with them, not merely shown them.
    assert "return that existing label exactly as written" in prompt


@pytest.mark.asyncio
async def test_a_profile_with_no_interests_yet_adds_no_catalogue() -> None:
    # The first interest anyone states has nothing to be merged into, and an
    # empty list in the prompt would be noise the model has to reason past.
    llm = _DecisionLLM({"explicit": True, "interests": ["Theater"]})

    await ScoutInterestProposalAgent(llm).propose("I love theater")

    assert "already follows" not in _system_prompt(llm)


@pytest.mark.asyncio
async def test_the_model_may_answer_with_an_interest_already_held() -> None:
    # The merge is the model's judgement, so the agent must pass its answer
    # through rather than treating a known label as nothing new to say.
    llm = _DecisionLLM({"explicit": True, "interests": ["Theater"]})

    proposal = await ScoutInterestProposalAgent(llm).propose(
        "I am into professional theater", ("Theater",)
    )

    assert proposal is not None
    assert proposal.labels == ("Theater",)


@pytest.mark.asyncio
async def test_repeated_labels_in_one_answer_are_still_collapsed() -> None:
    # The catalogue makes a repeat more likely, since several phrasings can map
    # onto the same existing label within a single message.
    llm = _DecisionLLM(
        {"explicit": True, "interests": ["Theater", "theater", "  Theater  "]}
    )

    proposal = await ScoutInterestProposalAgent(llm).propose(
        "community, professional and musical theater", ("Theater",)
    )

    assert proposal is not None
    assert proposal.labels == ("Theater",)
