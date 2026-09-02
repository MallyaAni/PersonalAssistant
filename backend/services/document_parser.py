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

import json
import re

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


class ParseUnavailable(ParseError):
    """The parser itself is off or unreachable - the document is fine and can
    be kept for later, which is what the durable queue does."""


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
# Seconds to establish a connection to the parser before it counts as away.
PARSER_CONNECT_SECONDS = 10

# What the caller is told when the parser cannot be reached.
PARSER_AWAY = (
    "The document parser is not reachable right now; I will not be able "
    "to read that file until it is back."
)


def needs_parser(media_type: str) -> bool:
    """Whether a file of this type goes through Docling at all.

    Plain text is read in place; everything else needs the parser, so only
    those uploads should wait on it or be queued when it is away.
    """
    return not media_type.startswith("text/")


# Docling's marker for a picture in its Markdown; with description on, the
# caption follows it as a paragraph.
PICTURE_PLACEHOLDER = "<!-- image -->"
PICTURE_PROMPT = (
    "Describe what this picture shows in one or two factual sentences, "
    "including any text, names, numbers, or places in it. No opinions."
)
_PICTURE = re.compile(r"<!-- image -->\s*\n\s*\n(?P<caption>[^\n]+)")


def _picture_options() -> dict[str, str]:
    """Docling's form fields for describing pictures through the vision
    model, or nothing when the describer is off."""
    url = settings.DOCLING_PICTURE_API_URL.strip()
    if not url:
        return {}
    api = {
        "url": url,
        "params": {"model": settings.DOCLING_PICTURE_MODEL, "max_tokens": 160},
        "prompt": PICTURE_PROMPT,
        "timeout": settings.DOCLING_PICTURE_TIMEOUT_SECONDS,
        "concurrency": 1,
    }
    return {
        "do_picture_description": "true",
        "picture_description_api": json.dumps(api),
        "picture_description_area_threshold": str(settings.DOCLING_PICTURE_AREA_THRESHOLD),
    }


def mark_pictures(markdown: str) -> str:
    """A described picture becomes one marked passage - "[Picture: ...]" -
    so a citation of it reads as a description, not as the document's own
    words; an undescribed picture's placeholder is dropped."""
    marked = _PICTURE.sub(lambda m: f"[Picture: {m.group('caption').strip()}]", markdown)
    return marked.replace(PICTURE_PLACEHOLDER, "").strip()


async def parse_document(filename: str, content: bytes) -> ParsedDocument:
    media_type = classify(filename, content)
    if media_type.startswith("text/"):
        text = content.decode("utf-8", errors="replace").strip()
        if not text:
            raise ParseError(f'"{filename}" looks empty.')
        return ParsedDocument(markdown=text, pages=1, media_type=media_type)
    base = settings.DOCLING_BASE_URL.rstrip("/")
    if not base:
        raise ParseUnavailable(
            "Document parsing is not switched on here yet, so I can only take "
            "plain text for now."
        )
    try:
        # A long read (a big scan takes minutes) but a short connect: the
        # parser's host drops connection attempts while the container is
        # stopped, and one number for both would wait out the kernel's
        # ~2 minutes of retries before admitting it is away (measured
        # 2026-09-02).
        timeout = httpx.Timeout(settings.DOCLING_TIMEOUT_SECONDS, connect=PARSER_CONNECT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base}/v1/convert/file",
                files={"files": (filename, content, media_type)},
                data={
                    "to_formats": "md",
                    "do_ocr": "true",
                    "md_page_break_placeholder": PAGE_BREAK,
                    **_picture_options(),
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Docling unreachable or failed for %s", filename, exc_info=True)
        raise ParseUnavailable(PARSER_AWAY) from exc
    markdown = mark_pictures(str(((payload.get("document") or {}).get("md_content")) or "").strip())
    if payload.get("status") not in (None, "success") or not markdown:
        raise ParseError(f'I could not get any readable text out of "{filename}".')
    pages = markdown.count(PAGE_BREAK) + 1
    return ParsedDocument(markdown=markdown, pages=pages, media_type=media_type)
