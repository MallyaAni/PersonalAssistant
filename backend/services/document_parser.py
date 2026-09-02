"""Turn an uploaded document into Markdown through Docling.

Stage 2 of docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md. Docling is the one piece
kept from the Specialized-Services drop: it reads PDFs (including scanned
pages, via OCR), Word and PowerPoint files, and returns clean Markdown with
page breaks marked, which the knowledge store then chunks and embeds exactly
as it does any text. This module knows nothing about storage; it converts.

Docling runs where a GPU is (the desktop), so it may be unreachable. Every
failure here is a ParseError with a sentence the person can be told, never a
traceback, and the caller decides whether to queue or to apologise.
"""
import logging
from dataclasses import dataclass

import httpx

from backend.config.settings import settings

logger = logging.getLogger(__name__)

# Docling puts this between pages when asked, so page numbers survive into the
# stored text and a citation can say which page an answer came from.
PAGE_BREAK = "<!-- page -->"

# What a document upload may be, proven by its first bytes rather than by the
# name or the declared type: a PDF starts with %PDF-, and Office files are zip
# containers. Plain text is accepted as it is and never sent to Docling.
_MAGIC = {
    "application/pdf": (b"%PDF-",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (b"PK\x03\x04",),
}
_SUFFIX_TO_TYPE = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


class ParseError(Exception):
    """A document could not be parsed; str(exc) is safe to show the person."""


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    pages: int
    media_type: str


# Decide what kind of document this is from its name and its first bytes, or
# say why it is refused. The suffix picks the type; the magic proves it.
def classify(filename: str, content: bytes) -> str:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media_type = _SUFFIX_TO_TYPE.get(suffix)
    if media_type is None:
        raise ParseError(
            "I can read PDF, Word (.docx), PowerPoint (.pptx) and plain text files."
        )
    magics = _MAGIC.get(media_type)
    if magics and not any(content.startswith(m) for m in magics):
        raise ParseError(f"That file does not look like a {suffix[1:].upper()} inside.")
    return media_type


# Convert one document to Markdown. Text passes straight through; everything
# else goes to Docling and comes back with page breaks marked.
async def parse_document(filename: str, content: bytes) -> ParsedDocument:
    media_type = classify(filename, content)
    if media_type.startswith("text/"):
        text = content.decode("utf-8", errors="replace").strip()
        if not text:
            raise ParseError(f'"{filename}" looks empty.')
        return ParsedDocument(markdown=text, pages=1, media_type=media_type)
    base = settings.DOCLING_BASE_URL.rstrip("/")
    if not base:
        raise ParseError(
            "Document parsing is not switched on here yet, so I can only take "
            "plain text for now."
        )
    try:
        async with httpx.AsyncClient(timeout=settings.DOCLING_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base}/v1/convert/file",
                files={"files": (filename, content, media_type)},
                data={
                    "to_formats": "md",
                    "do_ocr": "true",
                    "md_page_break_placeholder": PAGE_BREAK,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Docling unreachable or failed for %s", filename, exc_info=True)
        raise ParseError(
            "The document parser is not reachable right now; I will not be able "
            "to read that file until it is back."
        ) from exc
    markdown = str(((payload.get("document") or {}).get("md_content")) or "").strip()
    if payload.get("status") not in (None, "success") or not markdown:
        raise ParseError(f'I could not get any readable text out of "{filename}".')
    pages = markdown.count(PAGE_BREAK) + 1
    return ParsedDocument(markdown=markdown, pages=pages, media_type=media_type)
