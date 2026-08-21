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
from backend.services.main_action_selector import MainActionSelector
from backend.tests.functional.semantic import states

# Greedy decoding, deliberately. This suite is a regression gate: at the
# server's default sampling temperature the model sometimes named both
# image capabilities and sometimes omitted editing, so a red run could
# not be told from a real prompt regression. At temperature zero the
# same prompt gives the same answer, so red means something changed.
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


class _TrustedSearchPolicy:
    """Report the search server as auto-invocable, without an MCP session."""

    # describe_capabilities asks only this; nothing else about the service is
    # reachable from it, so a stub keeps the test off the network.
    def can_auto_invoke(self, server_id: str) -> bool:
        return True


# The capabilities the shipped selector actually offers, read from the selector
# rather than transcribed. Transcribing them here would recreate exactly the
# second copy this list was introduced to remove: the test would keep passing
# against wording the product no longer uses.
def _capabilities() -> list[dict[str, str]]:
    selector = MainActionSelector(
        llm=None,  # type: ignore[arg-type]
        mcp_invocation=_TrustedSearchPolicy(),  # type: ignore[arg-type]
        search_server_id="internet",
        search_tool_name="search_web",
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )
    return selector.describe_capabilities()


async def _ask(question: str) -> str:
    llm = get_llm_client()
    messages = [
        {
            "role": "system",
            "content": _build_system_prompt(
                {"agents": _ROSTER, "capabilities": _capabilities()}
            ),
        },
        {"role": "user", "content": question},
    ]
    try:
        result = llm.chat(messages, 900, None, 0.0)
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
    # The real inputs, not improvised ones - judged as what is asked for,
    # because "where you are" asks for locality without containing any of the
    # words a marker list would guess.
    assert states(answer, "asks for or mentions the user's location or area"), answer
    assert states(
        answer, "asks for or mentions how often it should run or a schedule"
    ), answer
    assert states(answer, "asks for or mentions the user's interests"), answer


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


# Both halves of the picture capability must survive the derivation. The list
# that shipped before said "generating a new picture, or editing one already in
# view" in one line; these are now two rows and either could go missing.
async def test_it_names_both_making_and_changing_a_picture() -> None:
    answer = await _ask("What can you do with images?")

    assert states(answer, "says it can create or generate new images"), answer
    assert states(answer, "says it can edit or change an existing image"), answer


# A diagram goal must reach the diagram capability, phrased as a goal rather
# than as the word the tool description happens to use.
#
# Deliberately the weaker of two assertions that were measured. Also requiring
# the answer to name a kind AniOS actually draws (flowchart, architecture,
# sequence, ...) discriminates far better - 14/15 with the capability list
# against 1/4 with it removed, versus 15/15 and 3/4 for this one - but it
# flaked once in fifteen, and a gate that fails 7% of the time gets ignored
# rather than read. The proof that the derived list is what the model is
# reading lives in the picture test above, which is both strong and stable.
async def test_a_diagram_goal_names_the_diagram_capability() -> None:
    answer = await _ask(
        "I need to show my team how our services connect to each other. "
        "What can you do for that?"
    )

    assert "diagram" in answer


# The tuned generate_image wording is now visible to the reply model too, and
# the case it was tuned for is a written request about a visual subject: it is
# answered as words, not deflected to the picture capability.
async def test_a_written_request_is_not_deflected_to_the_picture_capability() -> None:
    answer = await _ask("Write me a haiku about rain.")

    assert not any(
        phrase in answer
        for phrase in (
            "generate an image",
            "generating an image",
            "create an image",
            "creating an image",
            "generate a picture",
            "create a picture",
            "i'll draw",
            "i will draw",
        )
    )
    # A haiku, not a description of one: three short lines of actual verse.
    assert len([line for line in answer.splitlines() if line.strip()]) >= 3


# Knowing the capabilities must not turn into claiming they were performed.
async def test_it_does_not_claim_to_have_set_the_agent_up() -> None:
    answer = await _ask("Set up a scheduled agent for local events in my area for me.")
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
