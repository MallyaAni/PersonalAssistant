"""The document writer: the assistant's Markdown becomes a Word file, and a PDF is
that file printed, the format decides whether a renderer is needed, and a PDF is
refused clearly when nothing can render it."""
import io
import zipfile

import pytest

from backend.services.document_writer import (
    DOCX,
    PDF,
    WriteError,
    WriterUnavailable,
    _blocks,
    needs_renderer,
    render_docx,
    write_document,
)

def _word_body(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


BODY = """# Revised itinerary

Day 1 (Sun, Oct 11) - Arrival
- Arrive Salerno, **6pm** orientation
- 7:30pm dinner at the hotel

## Day 2 (Mon)
Pompeii only; afternoon free for Amalfi town.
"""


def test_the_body_is_read_as_headings_bullets_and_paragraphs():
    blocks = _blocks(BODY)
    assert [(b.level, b.bullet) for b in blocks] == [(1, False), (0, False), (0, True), (0, True), (2, False), (0, False)]
    assert blocks[2].text == "Arrive Salerno, **6pm** orientation"


def test_the_word_file_is_a_real_docx_with_the_words_in_it():
    content = render_docx("Amalfi itinerary", BODY)
    assert content.startswith(b"PK\x03\x04")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names
        document = archive.read("word/document.xml").decode("utf-8")
    assert "Amalfi itinerary" in document
    assert "• Arrive Salerno, " in document and "<w:b/>" in document
    assert "7:30pm dinner at the hotel" in document


def test_only_a_pdf_needs_the_renderer():
    assert needs_renderer(PDF) and not needs_renderer(DOCX)


@pytest.mark.asyncio
async def test_an_unknown_format_and_an_empty_body_are_refused():
    with pytest.raises(WriteError):
        await write_document("t", BODY, "pptx")
    with pytest.raises(WriteError):
        await write_document("t", "   ", DOCX)


@pytest.mark.asyncio
async def test_a_pdf_without_a_renderer_is_unavailable_not_broken(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "GOTENBERG_BASE_URL", "")
    with pytest.raises(WriterUnavailable):
        await write_document("t", BODY, PDF)


@pytest.mark.asyncio
async def test_a_word_file_needs_nothing_switched_on(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "GOTENBERG_BASE_URL", "")
    written = await write_document("Plan", BODY, DOCX)
    assert written.format == DOCX and written.extension == "docx"
    assert written.media_type.endswith("wordprocessingml.document")


def test_links_become_words_and_image_tags_are_dropped():
    body = "See [the tour site](https://example.com/tour) for details.\n\n![map of Salerno](https://example.com/map.png)\n\n![](https://example.com/blank.png)\n- Tickets at [the box office](https://example.com/box)"
    blocks = _blocks(body)
    assert blocks[0].text == "See the tour site (https://example.com/tour) for details."
    assert blocks[1].text == "map of Salerno"
    assert [b.text for b in blocks[2:]] == ["Tickets at the box office (https://example.com/box)"]
    document = _word_body(render_docx("t", body))
    assert "![" not in document and "](" not in document
    assert "the tour site (https://example.com/tour)" in document


def test_a_leading_heading_that_repeats_the_title_is_not_printed_twice():
    body = "# Relaxed Saturday in Old Town Alexandria\n\nA gentle day by the water.\n\n## Morning\n- 10:30 breakfast"
    document = _word_body(render_docx("Relaxed Saturday in Old Town Alexandria", body))
    assert document.count("Relaxed Saturday in Old Town Alexandria") == 1
    assert "A gentle day by the water." in document and "Morning" in document
    # A different first heading is kept.
    other = _word_body(render_docx("Weekend plan", body))
    assert other.count("Relaxed Saturday in Old Town Alexandria") == 1 and "Weekend plan" in other
