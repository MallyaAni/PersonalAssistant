"""The create_document tool and what feeds it: the call parses into an action,
"put that in a PDF" resolves to the previous real reply, and a written
document is named after its title on the way out of the iMessage worker."""
from backend.services.conversation_service import _previous_reply
from backend.tools import create_document
from backend.tools.actions import CreateDocumentAction
from backend.tools.registry import builtin_tools, parse_builtin
from backend.workers.imessage_chat import _document_filename


def test_the_tool_is_offered_and_parses_into_an_action():
    assert any(tool.name == "create_document" for tool in builtin_tools())
    action = parse_builtin("create_document", {"title": "Amalfi itinerary", "format": "docx", "body_markdown": "# Day 1"}, "x")
    assert action == CreateDocumentAction(title="Amalfi itinerary", format="docx", body_markdown="# Day 1")


def test_a_missing_title_is_no_action_and_an_odd_format_is_pdf():
    assert create_document.parse({"format": "pdf"}) is None
    assert create_document.parse({"title": "T", "format": "pptx"}).format == "pdf"
    assert create_document.parse({"title": "T"}).body_markdown == ""


def test_that_means_the_last_reply_long_enough_to_be_a_document():
    history = [
        {"query": "revise the tour", "response": "Here's the full revised day-by-day.\n\nDay 1 - Arrival in Salerno, orientation at 6pm, dinner at the hotel.\n\nDay 2 - Pompeii only."},
        {"query": "thanks", "response": "Any time."},
    ]
    assert _previous_reply(history).startswith("Here's the full revised")
    assert _previous_reply([{"query": "hi", "response": "Hello!"}]) == ""
    assert _previous_reply([]) == ""


def test_the_attachment_is_named_after_the_title_with_the_right_suffix():
    assert _document_filename("Amalfi itinerary: revised!", "application/pdf") == "Amalfi itinerary revised.pdf"
    assert _document_filename("", "application/vnd.openxmlformats-officedocument.wordprocessingml.document") == "document.docx"
    assert len(_document_filename("x" * 200, "application/pdf")) <= 84
