"""Does a diagram request actually produce a diagram - across the range?

A live group chat got "I couldn't create that diagram" twice on 2026-08-29.
The cause was not the model's reasoning: it drew the right graph every time
and would not put an escape sequence inside a JSON string, returning the whole
thing on one line, or - once the instruction was reworded - a bare "flowchart
TD" with no body at all. Measured on the failing request, one attempt in five
survived.

The schema asks for an array of statements now, so no escape is involved and
the engine's grammar requires at least a declaration and one statement. This
suite is the guarantee that the fix holds across the kinds of diagram people
actually ask for, rather than on the single request that exposed it.
"""

from __future__ import annotations

import pytest

from backend.artifacts.diagram import LLMDiagramProvider
from backend.config.settings import settings
from backend.core.dependencies import get_llm_client

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

# What people ask for, and the Mermaid family each should land in. The type is
# asserted only where the request names one; a plain request may reasonably be
# drawn as a flowchart.
REQUESTS = [
    ("Roman aqueduct architecture thinking process", None),
    ("how a pull request gets reviewed and merged", None),
    ("the steps of making sourdough bread", None),
    ("how a message travels from my phone to the assistant and back", None),
    ("a sequence diagram of a user logging in with a password", "sequence"),
    ("a state diagram for an online order from placed to delivered", "state"),
    ("a mindmap of things to pack for a beach holiday", "mindmap"),
    ("a timeline of the Apollo programme", "timeline"),
    ("a class diagram for a library with books and members", "class"),
    ("an entity relationship diagram for a blog with posts and authors", "entity_relationship"),
]


@pytest.fixture(scope="module")
def provider():
    return LLMDiagramProvider(get_llm_client(), settings.MAIN_LLM_MODEL)


@pytest.mark.parametrize(("request_text", "expected_type"), REQUESTS)
async def test_a_diagram_request_produces_a_diagram(provider, request_text, expected_type):
    spec = await provider.generate(request_text)
    print(f"\n{request_text[:44]!r} -> {spec.diagram_type} ({len(spec.source.splitlines())} lines)")

    # A declaration and at least one statement: the shape that was failing.
    body = spec.source.splitlines()
    assert len(body) >= 2, spec.source
    assert body[0].strip(), spec.source
    # No statement smuggled onto one line, which is the other shape it took.
    assert ";" not in spec.source or "\n" in spec.source, spec.source
    assert spec.title.strip(), spec

    if expected_type is not None:
        assert spec.diagram_type == expected_type, (request_text, spec.diagram_type)


async def test_the_same_request_survives_repetition(provider):
    # The live failure was intermittent, so passing once proves little. This is
    # the request that actually failed on a phone.
    for attempt in range(4):
        spec = await provider.generate("Roman aqueduct architecture thinking process")
        assert len(spec.source.splitlines()) >= 2, (attempt, spec.source)


# The conversation that failed on a real phone on 2026-08-30, end to end: the
# router reads it, the service uses the subject the router resolved, and the
# diagram model draws from that. Before the fix the diagram agent was handed
# the words "try again" and drew them.
_AQUEDUCT = [
    {
        "query": "how did the romans move water so far",
        "response": "Aqueducts. A gentle continuous gradient carried the water, with stacked arches to cross valleys.",
        "created_at": "2026-08-30T02:33:00+00:00",
    },
    {
        "query": "how did they build it that high",
        "response": "Stacked arches - rows of arches one on top of another, two or three tiers deep.",
        "created_at": "2026-08-30T02:34:00+00:00",
    },
    {
        "query": "can you draw it as a diagram instead?",
        "response": "I couldn't create that diagram. Please revise the request and try again.",
        "created_at": "2026-08-30T02:38:00+00:00",
    },
]
_NOW_LINE = (
    "Sunday 2026-08-30 04:00 - they are in Arlington, Virginia (America/New_York)"
)


@pytest.mark.parametrize("said", ["try again", "try again please", "can you try that again"])
async def test_try_again_draws_what_was_being_discussed(provider, said):
    from backend.core.dependencies import get_mcp_invocation_service, get_routing_llm_client
    from backend.services.main_action_selector import MainActionSelector

    selector = MainActionSelector(
        get_routing_llm_client(),
        get_mcp_invocation_service(),
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )
    action = await selector.select("diag_user", said, _AQUEDUCT, None, local_now=_NOW_LINE)
    subject = str(getattr(action, "subject", "") or "").strip()
    # What the service passes: the resolved subject, with the typed words as
    # the fallback only when the router returned none.
    spec = await provider.generate(subject or said)
    print(f"\n{said!r} -> subject={subject!r} title={spec.title!r}")

    haystack = f"{spec.title} {spec.source}".casefold()
    assert any(
        word in haystack
        for word in ("aqueduct", "arch", "water", "channel", "gradient", "roman")
    ), (said, subject, spec.title, spec.source[:200])
    # And never the words the person typed, which is what it used to draw.
    assert "try again" not in haystack, (said, spec.title)
