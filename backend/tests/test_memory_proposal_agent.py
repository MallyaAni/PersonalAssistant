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
        {"kind": "semantic_fact", "content": "My dog is called Biscuit.", "is_preference": False},
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
            ({"kind": "semantic_fact", "content": "My dog is called Biscuit.", "is_preference": False},),
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


@pytest.mark.asyncio
async def test_the_interest_catalogue_says_it_is_about_labels_only() -> None:
    """Deploy #20, 2026-08-28: with "Thai food" already followed, "we all
    settled on thai for friday dinner" produced nothing 3 times in 6 - the
    model read the catalogue as "already known". The catalogue now says what
    it is for; this holds the wording that carries that meaning."""
    llm = _DecisionLLM({"semantic_fact": "The group settled on Thai for Friday dinner."})
    await MemoryProposalAgent(llm).propose("we all settled on thai for friday dinner", ("Thai food",))
    system = llm.calls[0]["messages"][0]["content"]
    assert "already follows these Scout interests" in system
    assert "interest labels only" in system
    assert "never means a fact, plan, decision or event is already known" in system
    # Without a catalogue the prompt is unchanged.
    plain = _DecisionLLM({"semantic_fact": "x"})
    await MemoryProposalAgent(plain).propose("something", ())
    assert "already follows" not in plain.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_the_ordinary_prompt_is_byte_identical_whether_or_not_there_is_a_group() -> None:
    """One stray space from an empty group block flipped this classifier on a
    pinned case - a remark about the system stored as a user fact, 6/6 wrong
    against 6/6 right at temperature 0 - and group text in this prompt cost
    ordinary capture (an interest 6/6 privately, 2/6 in a room). A group turn
    asks its own question in its own call; this prompt never changes."""
    from backend.agents.memory.prompts import MEMORY_PROPOSAL_SYSTEM

    plain = _DecisionLLM({})
    await MemoryProposalAgent(plain).propose("hello")
    (only_call,) = plain.calls
    system = only_call["messages"][0]["content"]
    assert system.startswith(MEMORY_PROPOSAL_SYSTEM + "Meaning examples:"), repr(
        system[len(MEMORY_PROPOSAL_SYSTEM) :][:40]
    )

    catalogued = _DecisionLLM({})
    await MemoryProposalAgent(catalogued).propose("hello", ("hiking",))
    assert catalogued.calls[0]["messages"][0]["content"].startswith(
        MEMORY_PROPOSAL_SYSTEM + "The user already follows"
    )

    grouped = _DecisionLLM({})
    await MemoryProposalAgent(grouped).propose("hello", speaker="Ani", roster=("Ani", "Jen"))
    prompts = [call["messages"][0]["content"] for call in grouped.calls]
    ordinary = [text for text in prompts if "group chat" not in text]
    attribution = [text for text in prompts if "group chat" in text]
    assert len(ordinary) == 1 and len(attribution) == 1, prompts
    # Byte for byte the prompt a private message gets.
    assert ordinary[0] == system
    assert MEMORY_PROPOSAL_SYSTEM not in attribution[0]
