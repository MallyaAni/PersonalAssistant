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


def test_a_file_needs_the_parser_unless_it_is_plain_text():
    from backend.services.document_parser import needs_parser

    assert needs_parser("application/pdf")
    assert needs_parser("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert not needs_parser("text/plain")
    assert not needs_parser("text/markdown")


@pytest.mark.asyncio
async def test_the_parser_client_connects_fast_and_reads_long(monkeypatch):
    """The read timeout is the configured one (a big scan takes minutes); the
    connect timeout is short, so a host that drops connection attempts while
    the parser is stopped is admitted to be away in seconds, not after the
    kernel's retries."""
    import httpx

    from backend.config.settings import settings
    from backend.services import document_parser
    from backend.services.document_parser import PARSER_CONNECT_SECONDS, ParseUnavailable

    monkeypatch.setattr(settings, "DOCLING_BASE_URL", "http://parser.invalid:5001")
    seen: dict[str, object] = {}

    class Client:
        def __init__(self, *args, **kwargs):
            seen["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectTimeout("simulated")

    monkeypatch.setattr(document_parser.httpx, "AsyncClient", Client)
    with pytest.raises(ParseUnavailable):
        await document_parser.parse_document("scan.pdf", b"%PDF-1.4 fake")
    timeout = seen["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == PARSER_CONNECT_SECONDS <= 10
    assert timeout.read == settings.DOCLING_TIMEOUT_SECONDS


def test_a_described_picture_is_one_marked_passage_and_a_bare_placeholder_is_dropped():
    from backend.services.document_parser import mark_pictures

    md = "12:30 p.m. - Bus departs for Naples\n\n<!-- image -->\n\nThis image is a promotional graphic for the festival, a striped dome against a blue sky.\n\n## Day 2\n\n<!-- image -->\n\n## Day 3"
    marked = mark_pictures(md)
    assert "[Picture: This image is a promotional graphic for the festival, a striped dome against a blue sky.]" in marked
    assert "<!-- image -->" not in marked
    assert "## Day 2" in marked and "## Day 3" in marked


def test_picture_options_are_off_without_a_describer(monkeypatch):
    from backend.config.settings import settings
    from backend.services.document_parser import _picture_options

    monkeypatch.setattr(settings, "DOCLING_PICTURE_API_URL", "")
    assert _picture_options() == {}
    monkeypatch.setattr(settings, "DOCLING_PICTURE_API_URL", "http://172.16.8.5:8001/v1/chat/completions")
    options = _picture_options()
    assert options["do_picture_description"] == "true"
    assert "qwen3-vl-8b" in options["picture_description_api"] and options["picture_description_area_threshold"] == "0.05"
