"""create_document: the assistant's words as a PDF or Word file."""
from typing import Any

from .actions import CreateDocumentAction
from .base import BuiltinTool, required_text
from .contracts import EffectContract

NAME = "create_document"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The document's title, as it should appear at the top and in its file name.",
        },
        "format": {
            "type": "string",
            "enum": ["pdf", "docx"],
            "description": "pdf unless the user asked for Word, a .docx, or an editable document.",
        },
        "body_markdown": {
            "type": "string",
            "description": (
                "The document's full text in Markdown (headings, paragraphs, bullet "
                "lists, bold). Leave empty when the document is what you wrote in "
                "your previous message - 'put that in a PDF' - and it is used as is."
            ),
        },
    },
    "required": ["title", "format"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Documents as files",
    description=(
        "Write text into a file the user can keep, open, and share: a PDF or a "
        "Word document. Use it when the user asks for a PDF, a Word file, a "
        ".docx, a printable or downloadable copy, or to 'put that in a "
        "document' - of an itinerary, plan, list, letter, or anything "
        "composed in this conversation. Answering, summarising, or drafting "
        "text in the chat itself is never this tool; only a file is."
    ),
    schema=_SCHEMA,
    waiting=(
        "📄 Laying out the pages…",
        "🖨️ Putting that in a document…",
        "📎 Writing the file…",
    ),
    family="documents",
    contract=EffectContract(effect="write", cost="expensive", creates=True),
)


# The call as an action, or nothing when the model left out what to call it.
def parse(arguments: dict[str, Any]) -> CreateDocumentAction | None:
    title = required_text(arguments, "title")
    if title is None:
        return None
    fmt = str(arguments.get("format") or "pdf").strip().lower()
    body = arguments.get("body_markdown")
    return CreateDocumentAction(
        title=title,
        format=fmt if fmt in ("pdf", "docx") else "pdf",
        body_markdown=body.strip() if isinstance(body, str) else "",
    )
