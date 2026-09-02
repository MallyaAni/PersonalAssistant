"""A document the assistant writes says what was asked, proven by reading it
back through the parser: Gotenberg prints the PDF on the desktop and Docling
reads it, so the assertion is on the words in the file, not on the bytes
starting with %PDF. The Word file goes the same round trip.

Needs GOTENBERG_BASE_URL and DOCLING_BASE_URL (the desktop); skips where they
are unset - and a skip fails the gate, which is why this file is not in it
until the desktop is always on. Run by hand after a change to the writer.
"""
import pytest

from backend.config.settings import settings

pytestmark = pytest.mark.asyncio

ITINERARY = """# Revised itinerary

## Day 1 (Sun, Oct 11) - Arrival
- Arrive Salerno, 6pm orientation
- 7:30pm dinner at the hotel

## Day 2 (Mon) - Pompeii only
Afternoon free for Amalfi town or a swim.

## Day 4 (Wed) - Capri morning
Early ferry, then the concert in Naples.
"""


def _needs_desktop() -> None:
    if not settings.GOTENBERG_BASE_URL:
        pytest.skip("GOTENBERG_BASE_URL is not set; PDF writing is off here")
    if not settings.DOCLING_BASE_URL:
        pytest.skip("DOCLING_BASE_URL is not set; the read-back needs the parser")


async def test_the_pdf_says_what_the_reply_said():
    _needs_desktop()
    from backend.services.document_parser import parse_document
    from backend.services.document_writer import write_document

    written = await write_document("Amalfi itinerary", ITINERARY, "pdf")
    assert written.media_type == "application/pdf" and written.content.startswith(b"%PDF-")
    parsed = await parse_document("Amalfi itinerary.pdf", written.content)
    text = parsed.markdown.lower()
    for phrase in ("amalfi itinerary", "day 2", "pompeii", "capri morning", "7:30pm dinner"):
        assert phrase in text, f"{phrase!r} missing from the read-back:\n{parsed.markdown[:600]}"


async def test_the_word_file_says_what_the_reply_said():
    _needs_desktop()
    from backend.services.document_parser import parse_document
    from backend.services.document_writer import write_document

    written = await write_document("Amalfi itinerary", ITINERARY, "docx")
    parsed = await parse_document("Amalfi itinerary.docx", written.content)
    text = parsed.markdown.lower()
    for phrase in ("amalfi itinerary", "day 2", "pompeii", "capri morning"):
        assert phrase in text, f"{phrase!r} missing from the read-back:\n{parsed.markdown[:600]}"


# The router's side of the same capability: the plan just written, asked for
# as a file, becomes a create_document call with the format the person named.
# This runs against the real routing model and needs no desktop.
_PLAN_HISTORY = [
    {"query": "can you revise the tour so we get more time in Amalfi and Capri?", "response": ""},
    {
        "query": "yes",
        "response": (
            "Here's the full revised day-by-day.\n\nDay 1 (Sun, Oct 11) - Arrival. Arrive Salerno, "
            "6pm orientation, 7:30pm dinner at the hotel.\n\nDay 2 (Mon) - Pompeii only; afternoon free "
            "for Amalfi town.\n\nDay 3 (Tues) - Positano morning, rehearsal at 3pm."
        ),
    },
]


def _selector():
    from backend.core.dependencies import get_mcp_invocation_service, get_routing_llm_client
    from backend.services.main_action_selector import MainActionSelector

    return MainActionSelector(
        get_routing_llm_client(),
        get_mcp_invocation_service(),
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


@pytest.mark.parametrize(
    ("asked", "expected_format"),
    [("put that in a PDF", "pdf"), ("can you make that a word document?", "docx")],
)
async def test_the_plan_asked_for_as_a_file_routes_to_create_document(asked, expected_format):
    from backend.tools.actions import CreateDocumentAction

    action = await _selector().select("document_writing_eval", asked, _PLAN_HISTORY, None)
    assert isinstance(action, CreateDocumentAction), f"routed to {type(action).__name__} for {asked!r}"
    assert action.format == expected_format
    assert action.title.strip()
