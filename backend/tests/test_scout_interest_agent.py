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
