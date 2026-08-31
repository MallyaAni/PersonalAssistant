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
from backend.tests.functional.judge import describes

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


# The 2026-08-31 sequel, from production rows rather than a thought experiment.
# At 12:50 UTC the operator long-pressed the picture receipt and replied with
# the words "Architecture Thinking Process" - the title the thread had been
# using for four turns - and the subject came back as those words, so the
# diagram drawn was a generic flowchart again. Two things were licensing the
# echo and both are fixed: the resolver prompt treated a complete-looking
# phrase as a name, and the answering block quoted the pointed-at exchange
# without saying its words lean on the conversation above it. A said that
# carries the shorthand itself is the case "try again" never measured.
@pytest.mark.parametrize(
    ("replied_to", "kind"),
    [
        ("Here's the image you asked for.", "GenerateImageAction"),
        ("I couldn't create that diagram. Please revise the request and try again.",
         "CreateDiagramAction"),
    ],
)
async def test_a_reply_carrying_the_shorthand_still_completes_it(
    replied_to: str, kind: str
) -> None:
    action = await _routed("Architecture Thinking Process", replied_to)
    # An image action carries its reading in `prompt` - it has no subject
    # field, which is what the first version of this test read (empty) while
    # the prompt opened with the aqueduct.
    subject = _subject(action) or str(getattr(action, "prompt", "") or "")
    assert type(action).__name__ == kind, action
    assert "aqueduct" in subject.casefold(), subject


async def test_replying_to_a_receipt_reads_what_it_was_for() -> None:
    # 2026-08-31, the evening sequel: a reply directly to a receipt bubble.
    # The receipt's raw text is a title pretending to be subject matter, and
    # `_answering_line` used to quote it raw - putting the title in front of
    # the resolver as if it were the thing, undoing transcript._answer_line's
    # whole point. The quote now renders the metadata-aware line, so what the
    # resolver reads is what the attempt was for.
    action = await _routed("try again", "Created an editable diagram: Try Again Flow.")
    subject = _subject(action) or str(getattr(action, "prompt", "") or "")
    assert type(action).__name__ == "CreateDiagramAction", action
    assert "try again" not in subject.casefold(), subject
    assert "aqueduct" in subject.casefold(), subject


async def test_replying_to_the_picture_completes_the_subject_too() -> None:
    # Asserting the action type alone is what let 12:50 through: the kind was
    # right and the subject was the shorthand. Both halves are the behaviour.
    action = await _routed("try again", "Here's the image you asked for.")
    subject = _subject(action) or str(getattr(action, "prompt", "") or "")
    assert "aqueduct" in subject.casefold(), subject


# What actually gets drawn, judged rather than pattern-matched.
#
# The subject string is a proxy and it let the real failure through: it read
# "architecture thinking process", which contains neither "try again" nor
# anything else a substring assertion would catch, while the diagram it
# produced was a generic software-architecture flowchart with no aqueduct in
# it. The only honest question is whether the thing made is the thing wanted,
# so the diagram's own source goes back through a model and is asked.
async def test_the_diagram_a_retry_produces_is_about_the_aqueduct(llm: object) -> None:
    from backend.artifacts.diagram import LLMDiagramProvider
    from backend.config.settings import settings
    from backend.core.dependencies import get_llm_client
    from backend.services.followup import _answering_line, _recent

    replied_to = "I couldn't create that diagram. Please revise the request and try again."
    action = await _routed("try again", replied_to)
    subject = _subject(action)

    _, at = _answering_line(replied_to, HISTORY)
    provider = LLMDiagramProvider(
        get_llm_client(), settings.MAIN_LLM_MODEL or settings.LLM_MODEL
    )
    drawn = await provider.generate(subject, _recent(HISTORY, "", at))

    verdict = await describes(
        get_llm_client(),
        getattr(drawn, "source", "") or "",
        "a diagram about Roman aqueducts - how they were built, how they "
        "carried water, or the engineering thinking behind them. A generic "
        "software or business process flowchart does not match.",
    )
    assert verdict, f"subject was {subject!r}; {verdict}"
