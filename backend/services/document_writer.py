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


async def print_docx(docx: bytes) -> bytes:
    """A Word file printed to a PDF by Gotenberg's LibreOffice route - the
    writer's own file, or someone's original edited in place."""
    base = settings.GOTENBERG_BASE_URL.rstrip("/")
    if not base:
        raise WriterUnavailable("PDF rendering is not switched on here.")
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


async def render_pdf(title: str, markdown: str) -> bytes:
    """The Word file printed to a PDF by Gotenberg's LibreOffice route."""
    return await print_docx(render_docx(title, markdown))


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/footer1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
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
_DOCUMENT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
    "</Relationships>"
)
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

# The template: one readable face, sized headings with space above them,
# a hanging bullet, a small grey footer with the page number. A styles part
# makes the file open the same in Word, Pages, and LibreOffice (which prints
# the PDF), and it is what an edit of someone else's file must NOT overwrite.
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles {_W}>'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>'
    '<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-US"/>'
    '</w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:after="140" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:spacing w:before="0" w:after="240"/></w:pPr>'
    '<w:rPr><w:b/><w:color w:val="1D1D1F"/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>'
    '<w:rPr><w:b/><w:color w:val="1D1D1F"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr>'
    '<w:rPr><w:b/><w:color w:val="1D1D1F"/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="220" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr>'
    '<w:rPr><w:b/><w:color w:val="3A3A3C"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:spacing w:after="60"/><w:ind w:left="360" w:hanging="360"/></w:pPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:jc w:val="center"/><w:spacing w:after="0"/></w:pPr>'
    '<w:rPr><w:color w:val="86868B"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>'
    '</w:styles>'
)
_FOOTER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:ftr {_W}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>'
)
# A4-ish page with 2 cm margins and the footer, in twentieths of a point.
_SECTION = (
    '<w:sectPr><w:footerReference w:type="default" r:id="rId2"/>'
    '<w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1247" w:right="1134" w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/>'
    '</w:sectPr>'
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


def _paragraph(text: str, style: str | None = None) -> str:
    """One Word paragraph in a named style of the template (Title, Heading1-3,
    ListBullet) or the default; bold segments survive inside it."""
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_runs(text)}</w:p>"


def _without_repeated_title(title: str, blocks: list[_Block]) -> list[_Block]:
    """The body without a leading heading that only repeats the title: the
    reply's own first line is often the title again, and the live PDF opened
    with it twice (2026-09-02)."""
    if blocks and blocks[0].level and not blocks[0].bullet:
        if " ".join(blocks[0].text.split()).casefold().strip(" :.") == " ".join(title.split()).casefold().strip(" :."):
            return blocks[1:]
    return blocks


def render_docx(title: str, markdown: str) -> bytes:
    """The body as a Word document, built from the standard library, in the
    writer's template: a title block, styled headings, hanging bullets, a
    page number in the footer."""
    paragraphs = [_paragraph(title, "Title")]
    for block in _without_repeated_title(title, _blocks(markdown)):
        if block.bullet:
            paragraphs.append(_paragraph(block.text, "ListBullet"))
        elif block.level:
            paragraphs.append(_paragraph(block.text, f"Heading{min(block.level, 3)}"))
        else:
            paragraphs.append(_paragraph(block.text))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {_W}>"
        f"<w:body>{''.join(paragraphs)}{_SECTION}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/_rels/document.xml.rels", _DOCUMENT_RELS)
        archive.writestr("word/styles.xml", _STYLES)
        archive.writestr("word/footer1.xml", _FOOTER)
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
