"""Document conversion must preserve readable source evidence, not stringify errors."""

import io
import os
import zipfile

import httpx
import pytest

from backend.config.settings import settings
from backend.services import document_parser


# Reject malformed upstream payloads before they can become searchable knowledge.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [None, [], {"document": []}, {"document": {"md_content": 123}},
     {"document": {"md_content": {"error": "conversion failed"}}}],
)
async def test_invalid_conversion_is_not_readable_evidence(monkeypatch, payload):
    monkeypatch.setattr(settings, "DOCLING_BASE_URL", "http://parser.invalid")
    original = httpx.AsyncClient

    # Exercise the real HTTP response parser without contacting a provider.
    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(document_parser.httpx, "AsyncClient", client)
    with pytest.raises(document_parser.ParseError):
        await document_parser.parse_document("source.pdf", b"%PDF-1.7 fixture")


# Preserve complete table rows and original page identity through knowledge chunking.
def test_financial_table_preserves_page_and_numbers():
    from backend.services.agent_memory_manager import KnowledgeStore

    text = "Summary" + document_parser.PAGE_BREAK + (
        "| Period | Revenue | Margin |\n|---|---:|---:|\n"
        "| Q1 | 125.4 | 18.2% |\n| Q2 | 132.8 | 19.1% |"
    )
    chunks = KnowledgeStore._paged_chunks(text, chunk_size=60)
    table = [chunk for chunk, page in chunks if page == 2]
    assert len(table) == 1
    assert "125.4" in table[0]
    assert "19.1%" in table[0]
    assert document_parser.PAGE_BREAK not in table[0]


# Build a public financial table without a database, uploaded file or private data.
def financial_docx():
    from backend.tests.functional.fixtures.make_docx import make_docx

    source = make_docx(["Quarterly financial evidence"])
    rows = [("Period", "Revenue", "Margin"), ("Q1", "125.4", "18.2%"),
            ("Q2", "132.8", "19.1%")]
    table = "<w:tbl><w:tblPr/><w:tblGrid>" + "<w:gridCol/>" * 3 + "</w:tblGrid>"
    for row in rows:
        table += "<w:tr>" + "".join(
            f"<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>"
            for cell in row
        ) + "</w:tr>"
    table += "</w:tbl>"
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as old, zipfile.ZipFile(
        result, "w", zipfile.ZIP_DEFLATED
    ) as new:
        for name in old.namelist():
            content = old.read(name)
            if name == "word/document.xml":
                content = content.replace(
                    b"<w:sectPr/>", (table + "<w:sectPr/>").encode()
                )
            new.writestr(name, content)
    return result.getvalue()


# Exercise actual Docling conversion and preserve table evidence through chunking.
@pytest.mark.asyncio
async def test_real_financial_document_conversion(monkeypatch):
    from backend.services.agent_memory_manager import KnowledgeStore

    endpoint = os.environ.get("DOCLING_EVIDENCE_URL")
    if not endpoint:
        pytest.skip("DOCLING_EVIDENCE_URL is required for real conversion")
    monkeypatch.setattr(settings, "DOCLING_BASE_URL", endpoint)
    monkeypatch.setattr(document_parser, "_picture_options", lambda: {})
    parsed = await document_parser.parse_document(
        "financial-evidence.docx", financial_docx()
    )
    assert "Quarterly financial evidence" in parsed.markdown
    assert "|" in parsed.markdown
    for cell in ("Q1", "125.4", "18.2%", "Q2", "132.8", "19.1%"):
        assert cell in parsed.markdown
    table_rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in parsed.markdown.splitlines() if line.strip().startswith("|")
    ]
    assert ["Q1", "125.4", "18.2%"] in table_rows
    assert ["Q2", "132.8", "19.1%"] in table_rows
    chunks = KnowledgeStore._paged_chunks(parsed.markdown, chunk_size=60)
    assert any("125.4" in text and "19.1%" in text for text, page in chunks)
    assert all(page >= 1 for text, page in chunks)
