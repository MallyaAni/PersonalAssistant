"""Chunks remember their page when the parser marked page breaks, and text
without breaks chunks exactly as it always did."""
from backend.services.agent_memory_manager import KnowledgeStore
from backend.services.document_parser import PAGE_BREAK


def test_text_without_breaks_is_one_page():
    paged = KnowledgeStore._paged_chunks("first paragraph\n\nsecond paragraph")
    assert paged == [("first paragraph\n\nsecond paragraph", 1)]


def test_chunks_never_span_a_page_break():
    content = f"page one text{PAGE_BREAK}page two text\n\nmore of two{PAGE_BREAK}page three"
    paged = KnowledgeStore._paged_chunks(content)
    assert [page for _, page in paged] == [1, 2, 3]
    assert paged[1][0] == "page two text\n\nmore of two"
    assert all(PAGE_BREAK not in chunk for chunk, _ in paged)


def test_an_empty_page_is_skipped_but_numbering_keeps_the_document_order():
    content = f"one{PAGE_BREAK}{PAGE_BREAK}three"
    assert [page for _, page in KnowledgeStore._paged_chunks(content)] == [1, 3]
