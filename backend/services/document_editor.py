"""Edit a Word file someone shared, keeping its look.

The writer (document_writer.py) makes a new document from the assistant's
words. This is the other case the person asks for: "update the itinerary
with this and send me the file" - the file they gave, with its fonts,
colours, header and logo, page setup, and styles kept, and its body replaced
by the revised text.

A .docx is a zip of XML parts. Everything but `word/document.xml` is copied
byte for byte (styles, numbering, headers and footers with their pictures,
settings, fonts), and inside document.xml only the body's paragraphs and
tables are replaced; the section properties (page size, margins, the header
and footer references) stay. New paragraphs are written in the original's
own style ids - its title style, its heading styles, its list style with
its numbering - so Word renders them as the original's author set them up.
"""
from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass, field

from backend.services.document_writer import _blocks, _runs

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class EditError(Exception):
    """The file cannot be edited in place (not a Word file, or no body)."""


@dataclass(frozen=True, slots=True)
class _Styles:
    """The style ids the original uses for the shapes a body has."""

    title: str | None
    headings: dict[int, str] = field(default_factory=dict)  # level -> styleId
    list_paragraph: str | None = None
    list_numbering: str | None = None  # the <w:numPr>...</w:numPr> of the first bulleted paragraph, verbatim


_STYLE = re.compile(r'<w:style\b[^>]*w:styleId="(?P<id>[^"]+)"[^>]*>(?P<body>.*?)</w:style>', re.S)
_NAME = re.compile(r'<w:name\b[^>]*w:val="(?P<name>[^"]+)"')
_NUMPR = re.compile(r"<w:numPr>.*?</w:numPr>", re.S)
_PSTYLE = re.compile(r'<w:pStyle\b[^>]*w:val="(?P<id>[^"]+)"')
_PARAGRAPH = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.S)


def _styles_of(styles_xml: str, document_xml: str) -> _Styles:
    """Read the original's style ids by their names: "Title", "heading 1".."3",
    "List Paragraph"; and the numbering of its first list paragraph."""
    by_name: dict[str, str] = {}
    for m in _STYLE.finditer(styles_xml):
        name = _NAME.search(m.group("body"))
        if name:
            by_name[name.group("name").casefold()] = m.group("id")
    headings = {}
    for level in (1, 2, 3):
        for candidate in (f"heading {level}", f"heading{level}"):
            if candidate in by_name:
                headings[level] = by_name[candidate]
                break
    list_paragraph = by_name.get("list paragraph") or by_name.get("list bullet")
    numbering = None
    for paragraph in _PARAGRAPH.finditer(document_xml):
        num = _NUMPR.search(paragraph.group(0))
        if num:
            numbering = num.group(0)
            break
    return _Styles(by_name.get("title"), headings, list_paragraph, numbering)


def _paragraph(text: str, style: str | None, numbering: str | None = None) -> str:
    props = ""
    if style or numbering:
        style_xml = '<w:pStyle w:val="' + html.escape(style, quote=True) + '"/>' if style else ""
        props = "<w:pPr>" + style_xml + (numbering or "") + "</w:pPr>"
    return "<w:p>" + props + _runs(text) + "</w:p>"


def _body_xml(title: str, markdown: str, styles: _Styles) -> str:
    """The new body's paragraphs in the original's styles. Without a title
    style the title is a heading 1; without heading styles the heading text
    is bold; a bullet without a list style keeps its bullet character."""
    from backend.services.document_writer import _without_repeated_title

    out: list[str] = []
    if title.strip():
        out.append(_paragraph(title, styles.title or styles.headings.get(1)))
    for block in _without_repeated_title(title, _blocks(markdown)):
        if block.bullet:
            if styles.list_paragraph or styles.list_numbering:
                out.append(_paragraph(block.text, styles.list_paragraph, styles.list_numbering))
            else:
                out.append(_paragraph("• " + block.text, None))
        elif block.level:
            style = styles.headings.get(min(block.level, 3)) or styles.headings.get(max(styles.headings) if styles.headings else 1)
            out.append(_paragraph(block.text if style else f"**{block.text}**", style))
        else:
            out.append(_paragraph(block.text, None))
    return "".join(out)


def edit_docx(original: bytes, title: str, markdown: str) -> bytes:
    """The original Word file with its body replaced by the revised text, in
    its own styles; every other part untouched."""
    try:
        source = zipfile.ZipFile(io.BytesIO(original))
        names = set(source.namelist())
    except zipfile.BadZipFile as exc:
        raise EditError("That file is not a Word document.") from exc
    if "word/document.xml" not in names:
        raise EditError("That file is not a Word document.")
    document = source.read("word/document.xml").decode("utf-8")
    styles = source.read("word/styles.xml").decode("utf-8") if "word/styles.xml" in names else ""
    body_start = document.find("<w:body")
    body_open_end = document.find(">", body_start)
    body_end = document.rfind("</w:body>")
    if body_start < 0 or body_end < 0:
        raise EditError("That Word document has no body to edit.")
    inner = document[body_open_end + 1 : body_end]
    sect_at = inner.rfind("<w:sectPr")
    section = inner[sect_at:] if sect_at >= 0 else ""
    new_inner = _body_xml(title, markdown, _styles_of(styles, inner)) + section
    edited = document[: body_open_end + 1] + new_inner + document[body_end:]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename == "word/document.xml":
                target.writestr(item.filename, edited.encode("utf-8"))
            else:
                target.writestr(item, source.read(item.filename))
    return buffer.getvalue()


def is_docx(content: bytes) -> bool:
    """Whether the bytes are a Word file: a zip carrying word/document.xml."""
    if not content.startswith(b"PK\x03\x04"):
        return False
    try:
        return "word/document.xml" in zipfile.ZipFile(io.BytesIO(content)).namelist()
    except zipfile.BadZipFile:
        return False
