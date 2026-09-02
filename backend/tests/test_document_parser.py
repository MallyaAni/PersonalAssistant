"""The document parser's own rules, without Docling: what is accepted, what is
refused, and that plain text never leaves the process."""
import pytest

from backend.services.document_parser import ParseError, classify, parse_document

def test_a_pdf_is_recognised_by_its_bytes_not_its_name():
    assert classify("notes.pdf", b"%PDF-1.7 ...") == "application/pdf"


def test_a_renamed_script_is_refused_as_not_a_pdf():
    with pytest.raises(ParseError, match="does not look like a PDF"):
        classify("payload.pdf", b"#!/bin/sh\nrm -rf /\n")


def test_an_office_file_is_a_zip_container():
    assert classify("deck.pptx", b"PK\x03\x04rest").endswith("presentation")
    with pytest.raises(ParseError):
        classify("deck.pptx", b"not a zip")


def test_an_unknown_suffix_says_what_is_accepted():
    with pytest.raises(ParseError, match="PDF, Word"):
        classify("data.csv", b"a,b\n1,2\n")


@pytest.mark.asyncio
async def test_plain_text_passes_through_without_docling():
    parsed = await parse_document("notes.txt", b"  hello world  \n")
    assert parsed.markdown == "hello world"
    assert parsed.pages == 1
    assert parsed.media_type == "text/plain"


@pytest.mark.asyncio
async def test_empty_text_is_refused():
    with pytest.raises(ParseError, match="looks empty"):
        await parse_document("blank.txt", b"   \n")
