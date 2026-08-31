"""The operator's own group thread, replayed against the running model.

2026-08-30. A diagram of Roman aqueducts failed, and the retries went "you
try again bruh", then "try again!", then "Try Again". Each was resolved
against the most recent message, and during a run of failures the most
recent message is the failure - so the subject decayed out of the
conversation and the thread ended holding a diagram titled "Try Again
Flow", and then one titled "Try Again". The operator had been long-pressing
the diagram request and replying to it the whole time.

Two fixes are pinned here, and the first is the one that matters most
because it needs nothing of the person. The resolver's schema asked for the
restatement before it had decided what the message referred to, so it
restated "try again" as "try again" and had nothing left to name a subject
from. Asked in dependency order - what it refers to, then the message
written out, then the subject - it recovers the aqueduct on its own.

The second is that a long-press reply is now supplied and honoured, so a
person who points at an older message is answered about that message.
"""

from __future__ import annotations

import pytest

from backend.config.settings import settings
from backend.core.dependencies import get_mcp_invocation_service, get_routing_llm_client
from backend.search.budgeted import SearchIdentity, current_search_identity
from backend.services.main_action_selector import MainActionSelector

pytestmark = pytest.mark.asyncio

# The thread as it happened - with the metadata production stores.
#
# That metadata is the point. An artifact turn's stored response reads
# "Created an editable diagram: Try Again Flow.", and `transcript_lines`
# rewrites it to `[a diagram was created for "..."]` using the turn's route
# detail, so no model ever reads the title as if it were the subject. A test
# history without that metadata is a transcript the system never shows: it
# made this file pass while the real thread failed, and then made it fail
# while the real thread passed. Build the history the way the database has
# it, or measure something else entirely.
def _drew(query: str, title: str, detail: str) -> dict:
    return {
        "query": query,
        "response": f"Created an editable diagram: {title}.",
        "metadata": {
            "artifact_ids": [f"id-{title}"],
            "artifact_status": "ready",
            "trace": {"route": {"label": "Diagrams", "detail": detail}},
        },
    }


AQUEDUCT = "Roman aqueduct architecture thinking process"
HISTORY = [
    {"query": "JenOS what is an aqueduct?",
     "response": "An aqueduct is a channel that carries water. The Romans built the famous ones."},
    {"query": "how did they build it that high",
     "response": "They used stacked arches to span valleys with little material."},
    {"query": "generate a picture of the architecture thinking process",
     "response": "Here's the image you asked for."},
    {"query": "can you draw it as a diagram instead?",
     "response": "I couldn't create that diagram. Please revise the request and try again."},
    _drew("you try again bruh", "Simple Flowchart", AQUEDUCT),
    _drew("try again!", "Try Again Flow", AQUEDUCT),
]


def _selector() -> MainActionSelector:
    return MainActionSelector(
        get_routing_llm_client(),
        get_mcp_invocation_service(),
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


async def _routed(said: str, replying_to: str = ""):
    token = current_search_identity.set(
        SearchIdentity(user_id="retry_subject", is_operator=True)
    )
    try:
        return await _selector().select(
            "retry_subject", said, HISTORY, None,
            zone="America/New_York", replying_to=replying_to,
        )
    finally:
        current_search_identity.reset(token)


def _subject(action: object) -> str:
    return str(getattr(action, "subject", "") or "")


@pytest.mark.parametrize("said", ["try again", "try again!", "you try again bruh"])
async def test_a_bare_retry_redraws_the_subject_not_the_request(said: str) -> None:
    # The failure verbatim: a diagram named after the words of the request.
    # The bar is the subject saying what the diagram is *of* - "architecture
    # thinking process" is shorthand that means nothing on its own and drew a
    # generic flowchart, which is what the operator saw on 2026-08-31.
    action = await _routed(said)
    subject = _subject(action)
    assert type(action).__name__ == "CreateDiagramAction", (said, action)
    assert "try again" not in subject.casefold(), subject
    assert "aqueduct" in subject.casefold(), subject


@pytest.mark.parametrize(
    "replied_to",
    [
        "I couldn't create that diagram. Please revise the request and try again.",
        "can you draw it as a diagram instead?",
    ],
)
async def test_replying_to_an_older_message_answers_that_message(replied_to: str) -> None:
    action = await _routed("try again", replied_to)
    subject = _subject(action)
    assert type(action).__name__ == "CreateDiagramAction", action
    assert "try again" not in subject.casefold(), subject
    assert "aqueduct" in subject.casefold(), subject


async def test_replying_to_the_picture_asks_for_the_picture() -> None:
    # The reference decides the kind as well as the subject: that bubble was
    # an image, so "try again" means make the picture again, not draw a
    # diagram. Getting this "wrong" would mean ignoring what they pointed at.
    action = await _routed("try again", "Here's the image you asked for.")
    assert type(action).__name__ == "GenerateImageAction", action
