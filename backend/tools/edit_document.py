"""edit_document: the Word file the user shared, rewritten with revised text, its look kept."""
from typing import Any

from .actions import EditDocumentAction
from .base import BuiltinTool, required_text

NAME = "edit_document"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The document's title as it should read at the top of the updated file.",
        },
        "format": {
            "type": "string",
            "enum": ["docx", "pdf"],
            "description": "docx unless the user asked for the updated file as a PDF.",
        },
        "body_markdown": {
            "type": "string",
            "description": (
                "The document's full revised text in Markdown (headings, paragraphs, bullet "
                "lists, bold) - the whole document as it should now read, not only the "
                "changed part. Leave empty when it is what you wrote in your previous message."
            ),
        },
    },
    "required": ["title", "format"],
    "additionalProperties": False,
}

TOOL = BuiltinTool(
    name=NAME,
    label="Edits to a shared file",
    description=(
        "Rewrite a Word file the user shared earlier in this conversation with "
        "revised text, keeping the file's own look - its fonts, colours, header, "
        "logo, and page setup - and hand the updated file back. Use it when the "
        "user asks to update, revise, or change the document or file they sent, "
        "to put changes into the original, or for an updated copy of their file. "
        "A brand-new document from the conversation is create_document instead; "
        "answering or summarising in the chat is neither."
    ),
    schema=_SCHEMA,
    waiting=(
        "✏️ Updating your file…",
        "📄 Rewriting the document in its own style…",
    ),
)


# The call as an action, or nothing when the model left out the title.
def parse(arguments: dict[str, Any]) -> EditDocumentAction | None:
    title = required_text(arguments, "title")
    if title is None:
        return None
    fmt = str(arguments.get("format") or "docx").strip().lower()
    body = arguments.get("body_markdown")
    return EditDocumentAction(
        title=title,
        format=fmt if fmt in ("docx", "pdf") else "docx",
        body_markdown=body.strip() if isinstance(body, str) else "",
    )
