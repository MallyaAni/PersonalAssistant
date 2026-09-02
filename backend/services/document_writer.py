"""Turn the assistant's words into a file: a PDF or a Word document.

The mirror of document_parser. Reading goes through Docling on the desktop;
writing builds a .docx here with no dependency, and a PDF is that Word file
printed by Gotenberg's LibreOffice route on the same desktop - one source
for both formats, so the PDF says exactly what the Word file says. (The
Chromium route was tried first and cannot start on the desktop's Docker:
"chrome_crashpad_handler: --database is required", 2026-09-02.) The body is
the Markdown subset the assistant writes anyway: headings, paragraphs,
bullet lists, bold.

Gotenberg is bursty and lives where Docling does, so a PDF asked for while
the desktop is off is answered with the Word file instead of a failure - the
sharer still gets a document, and the reply says which one.
"""
from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass

import httpx

from backend.config.settings import settings

# Seconds to establish a connection to the renderer before it counts as away.
RENDERER_CONNECT_SECONDS = 10

PDF = "pdf"
DOCX = "docx"

# The formats the assistant can write, with the media type each file carries.
DOCUMENT_FORMATS: dict[str, str] = {
    PDF: "application/pdf",
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class WriteError(Exception):
    """The document could not be produced from what was given."""


class WriterUnavailable(WriteError):
    """The PDF renderer cannot be reached; the file is fine to make later."""


@dataclass(frozen=True, slots=True)
class WrittenDocument:
    content: bytes
    media_type: str
    format: str
    extension: str


def needs_renderer(fmt: str) -> bool:
    """Whether a format needs Gotenberg: PDF does, Word is built here."""
    return fmt == PDF


async def renderer_reachable() -> bool:
    """Whether Gotenberg answers at all - a quick probe before a long render."""
    base = settings.GOTENBERG_BASE_URL.rstrip("/")
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            return (await client.get(f"{base}/health")).status_code == 200
    except Exception:
        return False


# One block of the body: a heading level (0 for a paragraph), bullet flag, text.
@dataclass(frozen=True, slots=True)
class _Block:
    level: int
    bullet: bool
    text: str


# Markdown a reply may carry that has no place in a printed page as syntax:
# an image tag has no picture to show (the writer carries text only, for
# now), a link is kept as its words with the address after them.
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _plain(text: str) -> str:
    """Inline Markdown the page cannot render, reduced to words: images
    dropped (their alt text kept when they have one), links as text (url)."""
    text = _IMAGE.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    return " ".join(text.split())


_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _blocks(markdown: str) -> list[_Block]:
    """The body as blocks: a heading per '#' line, a bullet per list line,
    a paragraph per run of other lines."""
    blocks: list[_Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(_Block(0, False, " ".join(paragraph).strip()))
            paragraph.clear()

    for raw in markdown.splitlines():
        line = _plain(raw.rstrip())
        if not line.strip():
            flush()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            blocks.append(_Block(len(heading.group(1)), False, heading.group(2).strip()))
            continue
        bullet = _BULLET.match(line)
        if bullet:
            flush()
            blocks.append(_Block(0, True, bullet.group(1).strip()))
            continue
        paragraph.append(line.strip())
    flush()
    return blocks


async def render_pdf(title: str, markdown: str) -> bytes:
    """The Word file printed to a PDF by Gotenberg's LibreOffice route."""
    base = settings.GOTENBERG_BASE_URL.rstrip("/")
    if not base:
        raise WriterUnavailable("PDF rendering is not switched on here.")
    docx = render_docx(title, markdown)
    timeout = httpx.Timeout(settings.GOTENBERG_TIMEOUT_SECONDS, connect=RENDERER_CONNECT_SECONDS)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base}/forms/libreoffice/convert",
                files={"files": ("document.docx", docx, DOCUMENT_FORMATS[DOCX])},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WriterUnavailable("The PDF renderer is not reachable right now.") from exc
    content = response.content
    if not content.startswith(b"%PDF-"):
        raise WriteError("The renderer did not return a PDF.")
    return content


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    "</Relationships>"
)


def _runs(text: str) -> str:
    """Word runs for one line: bold segments become bold runs."""
    out: list[str] = []
    position = 0
    for match in _BOLD.finditer(text):
        if match.start() > position:
            out.append(_run(text[position : match.start()], bold=False))
        out.append(_run(match.group(1), bold=True))
        position = match.end()
    if position < len(text):
        out.append(_run(text[position:], bold=False))
    return "".join(out)


def _run(text: str, *, bold: bool) -> str:
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{html.escape(text, quote=False)}</w:t></w:r>'


def _paragraph(text: str, *, size_half_points: int | None = None, bold: bool = False, bullet: bool = False) -> str:
    """One Word paragraph. Headings are sized and bold rather than styled, so
    the file needs no styles part; bullets are a hanging-indent paragraph
    that starts with the bullet character."""
    props = []
    if bullet:
        props.append('<w:ind w:left="360" w:hanging="360"/>')
    ppr = f"<w:pPr>{''.join(props)}</w:pPr>" if props else ""
    body = _runs(("• " if bullet else "") + text)
    if size_half_points or bold:
        rpr = ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size_half_points}"/>' if size_half_points else "")
        body = body.replace("<w:r>", f"<w:r><w:rPr>{rpr}</w:rPr>", 1) if "<w:r>" in body else body
    return f"<w:p>{ppr}{body}</w:p>"


def render_docx(title: str, markdown: str) -> bytes:
    """The body as a Word document, built from the standard library."""
    paragraphs = [_paragraph(title, size_half_points=36, bold=True)]
    for block in _blocks(markdown):
        if block.bullet:
            paragraphs.append(_paragraph(block.text, bullet=True))
        elif block.level:
            paragraphs.append(_paragraph(block.text, size_half_points=max(22, 30 - 4 * block.level), bold=True))
        else:
            paragraphs.append(_paragraph(block.text))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(paragraphs)}<w:sectPr/></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


async def write_document(title: str, markdown: str, fmt: str) -> WrittenDocument:
    """The body as a file in the asked-for format, or a WriteError."""
    if fmt not in DOCUMENT_FORMATS:
        raise WriteError(f"I can write a PDF or a Word document, not {fmt!r}.")
    if not markdown.strip():
        raise WriteError("There is nothing to put in the document yet.")
    if fmt == PDF:
        content = await render_pdf(title, markdown)
    else:
        content = render_docx(title, markdown)
    return WrittenDocument(content, DOCUMENT_FORMATS[fmt], fmt, fmt)
