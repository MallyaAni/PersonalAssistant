"""Measure whether the assistant knows what AniOS itself can do.

Asked what was needed to schedule something reporting on the local area, the
reply improvised requirements as though no such feature existed - while Scout
is exactly that feature and its inputs are known. These run the real model and
assert on the answer, because a structural test cannot tell you the reply sent
the user off to build what they already own.
"""

import pytest

from backend.agents.graph import _build_system_prompt
from backend.core.dependencies import get_llm_client

pytestmark = pytest.mark.asyncio


# The roster ConversationService supplies, in the shape the registry produces.
# Passed explicitly rather than left empty: the prompt renders whatever agents
# exist and nothing when none do, so an empty context would test the absence of
# a roster instead of the behaviour that ships.
_ROSTER = [
    {
        "name": "Scout",
        "role": (
            "Finds things happening near you that match what you like, and "
            "turns each one into a calendar entry"
        ),
        "trigger": "Weekly schedule",
        "setup_needs": (
            "interests to follow, a home locality, a cadence with an hour and "
            "timezone, and somewhere to deliver to"
        ),
    },
    {
        "name": "Deck",
        "role": "Plans and builds editable presentations in its own worker",
        "trigger": "Delegated from chat",
        "setup_needs": "",
    },
]


async def _ask(question: str) -> str:
    llm = get_llm_client()
    messages = [
        {"role": "system", "content": _build_system_prompt({"agents": _ROSTER})},
        {"role": "user", "content": question},
    ]
    try:
        result = llm.chat(messages, 900)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"main model unreachable: {type(exc).__name__}")
    return str(result.get("content") or "").lower()


# The reported case: a goal Scout already covers must be answered as Scout.
async def test_a_scheduled_local_roundup_is_answered_as_the_existing_feature() -> None:
    answer = await _ask(
        "What information do you need for running a scheduled agent that "
        "tells me about things going on in the area?"
    )
    assert "scout" in answer
    # The real inputs, not improvised ones. Locality and cadence are the two
    # that a generic answer reliably omits.
    assert any(word in answer for word in ("locality", "location", "area"))
    assert any(word in answer for word in ("cadence", "schedule", "how often"))
    assert any(word in answer for word in ("interest", "topics"))


# Generalised past the reported wording: a deck goal must reach the deck agent.
@pytest.mark.parametrize(
    "question",
    [
        "I need to present our roadmap to the team next week, what can you do?",
        "What's the best way to get a slide deck out of you?",
    ],
)
async def test_a_presentation_goal_names_the_deck_capability(question: str) -> None:
    answer = await _ask(question)
    assert any(word in answer for word in ("deck", "slide", "presentation"))


# Knowing the capabilities must not turn into claiming they were performed.
async def test_it_does_not_claim_to_have_set_the_agent_up() -> None:
    answer = await _ask(
        "Set up a scheduled agent for local events in my area for me."
    )
    assert not any(
        phrase in answer
        for phrase in (
            "i've set up",
            "i have set up",
            "i've scheduled",
            "i have scheduled",
            "is now scheduled",
            "i've created",
            "i have created",
        )
    )
