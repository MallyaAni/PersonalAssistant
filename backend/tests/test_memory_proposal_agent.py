import json

import pytest

from backend.memory.proposal_agent import MemoryProposalAgent


class _DecisionLLM:
    """Return one configured grammar-valid semantic memory decision."""

    # Store the decision and capture the provider-neutral request.
    def __init__(self, decision: dict[str, object]) -> None:
        self.decision = decision
        self.calls: list[dict[str, object]] = []

    # Mimic the structured local-model boundary.
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


# Extract every compatible fact from the exact reported introduction.
@pytest.mark.asyncio
async def test_semantic_agent_extracts_name_and_interests_together() -> None:
    llm = _DecisionLLM(
        {
            "preferred_name": "Jen",
            "interests": ["acting", "theater", "networking events"],
        }
    )

    result = await MemoryProposalAgent(llm).propose(
        "hi my name is Jen and i like acting, theater, networking events"
    )

    assert result.proposals == (
        {"kind": "preferred_name", "value": "Jen"},
        {
            "kind": "discovery_interests",
            "labels": ["acting", "theater", "networking events"],
        },
    )
    assert llm.calls[0]["temperature"] == 0
    assert llm.calls[0]["response_schema"]["properties"]["preferred_name"]


# A profile detail must not make a compatible long-term fact disappear.
@pytest.mark.asyncio
async def test_profile_and_general_facts_from_one_message_are_both_kept() -> None:
    llm = _DecisionLLM(
        {
            "preferred_name": "Jen",
            "interests": ["acting"],
            "semantic_fact": "My dog is called Biscuit.",
        }
    )

    result = await MemoryProposalAgent(llm).propose(
        "I'm Jen, I love acting, and my dog is called Biscuit."
    )

    assert result.proposals == (
        {"kind": "preferred_name", "value": "Jen"},
        {"kind": "discovery_interests", "labels": ["acting"]},
        {"kind": "semantic_fact", "content": "My dog is called Biscuit."},
    )


# Keep questions and model inferences out of the approval queue.
@pytest.mark.asyncio
async def test_semantic_agent_returns_no_unsupported_memory() -> None:
    llm = _DecisionLLM({})

    result = await MemoryProposalAgent(llm).propose(
        "Would someone named Jen enjoy theater?"
    )

    assert result.proposals == ()


# Normalize duplicate labels and preserve the user's existing broad interest.
@pytest.mark.asyncio
async def test_semantic_agent_validates_interest_labels() -> None:
    llm = _DecisionLLM({"interests": [" Theater ", "theater", "Networking   Events"]})

    result = await MemoryProposalAgent(llm).propose(
        "Stage work and professional mixers are my thing.",
        ("Theater",),
    )

    assert result.proposals == (
        {
            "kind": "discovery_interests",
            "labels": ["Theater", "Networking Events"],
        },
    )
    prompt = str(llm.calls[0]["messages"][0]["content"])
    assert '"Theater"' in prompt
    assert "Do not depend on particular trigger words" in prompt


# Prefer one structured general-memory type instead of duplicating a fact.
@pytest.mark.asyncio
async def test_semantic_agent_maps_an_explicit_entity_relationship() -> None:
    llm = _DecisionLLM(
        {
            "entity": {
                "entity_type": "person",
                "canonical_name": "Dr. Rivera",
                "relationship": "dentist",
            },
            "semantic_fact": "Dr. Rivera is my dentist.",
        }
    )

    result = await MemoryProposalAgent(llm).propose(
        "Please keep track of Dr. Rivera, who is my dentist."
    )

    assert result.proposals == (
        {
            "kind": "entity",
            "entity_type": "person",
            "canonical_name": "Dr. Rivera",
            "attributes": {"relationship": "dentist"},
        },
    )


# Convert every remaining semantic category into its existing typed API payload.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (
            {"response_style": "concise"},
            ({"kind": "response_style", "value": "concise"},),
        ),
        (
            {"locality": {"label": "Arlington", "region": "Virginia"}},
            (
                {
                    "kind": "discovery_locality",
                    "label": "Arlington",
                    "region": "Virginia",
                },
            ),
        ),
        (
            {
                "procedure": {
                    "name": "Deploy preview",
                    "steps": ["Build the app", "Publish the artifact"],
                }
            },
            (
                {
                    "kind": "procedure",
                    "name": "Deploy preview",
                    "description": "User-approved workflow: Deploy preview",
                    "steps": [
                        {"order": 1, "instruction": "Build the app"},
                        {"order": 2, "instruction": "Publish the artifact"},
                    ],
                },
            ),
        ),
        (
            {"knowledge": {"title": "Router note", "content": "Use port 8080."}},
            (
                {
                    "kind": "knowledge",
                    "title": "Router note",
                    "content": "Use port 8080.",
                },
            ),
        ),
        (
            {"semantic_fact": "My dog is called Biscuit."},
            ({"kind": "semantic_fact", "content": "My dog is called Biscuit."},),
        ),
        (
            {"episodic_event": "I attended the summer acting workshop."},
            (
                {
                    "kind": "episodic",
                    "content": "I attended the summer acting workshop.",
                },
            ),
        ),
    ],
)
async def test_semantic_agent_maps_each_typed_category(
    decision: dict[str, object],
    expected: tuple[dict[str, object], ...],
) -> None:
    result = await MemoryProposalAgent(_DecisionLLM(decision)).propose(
        "Semantically interpreted test utterance."
    )

    assert result.proposals == expected
