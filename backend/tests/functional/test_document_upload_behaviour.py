"""A real document, end to end: parsed by the real Docling, stored, retrieved,
and answered from - the acceptance case of Phase 2 in
docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md.

The document is the operator's own itinerary PDF (two pages, eleven day
headings), placed at ITINERARY_PATH by the runner. Docling lives on the
desktop GPU, so this runs where the backend runs and, like every test here,
skips where the parser is unreachable - and a skip fails the gate.
"""
import os
import uuid

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.config.settings import settings

pytestmark = pytest.mark.asyncio

ITINERARY_PATH = os.environ.get("ITINERARY_PATH", "/tmp/itinerary.pdf")


@pytest.fixture(scope="module")
def itinerary() -> bytes:
    if not settings.DOCLING_BASE_URL:
        pytest.skip("DOCLING_BASE_URL is not set; document parsing is off here")
    if not os.path.exists(ITINERARY_PATH):
        pytest.skip(f"itinerary PDF not present at {ITINERARY_PATH}")
    return open(ITINERARY_PATH, "rb").read()


async def test_the_itinerary_parses_into_page_anchored_markdown(itinerary):
    from backend.services.document_parser import PAGE_BREAK, parse_document

    parsed = await parse_document("Itinerary Amalfi Choral Tour.pdf", itinerary)
    assert parsed.media_type == "application/pdf"
    # Two pages in the PDF: one break between them, so two anchored pages.
    assert parsed.pages == 2, parsed.pages
    assert PAGE_BREAK in parsed.markdown
    # Structure survives: the day headings Docling recovered on the desktop.
    assert "Day 1" in parsed.markdown and "Salerno" in parsed.markdown, parsed.markdown[:400]


async def test_an_uploaded_itinerary_answers_a_question_about_its_evening(itinerary, llm):
    from backend.core.dependencies import get_agent_memory_manager, get_embedding_provider
    from backend.database.session import AsyncSessionLocal
    from backend.services.document_parser import parse_document
    from backend.tests.functional.semantic import states

    parsed = await parse_document("Itinerary Amalfi Choral Tour.pdf", itinerary)
    user_id = f"functional-upload-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        manager = get_agent_memory_manager(session, get_embedding_provider())
        stored = await manager.knowledge.ingest(
            user_id, "Itinerary Amalfi Choral Tour.pdf", parsed.markdown,
            "upload://Itinerary Amalfi Choral Tour.pdf", "uploaded_document",
        )
        try:
            query = "what happens on the evening of day 1 of the amalfi tour?"
            found = await manager.knowledge.search(user_id, query, 6)
            assert found, "the itinerary question retrieved nothing"
            context = {"knowledge": found}
            messages = [{"role": "system", "content": _build_system_prompt(context)}]
            messages.extend(turn_context_messages(context))
            messages.append({"role": "user", "content": query})
            text = str(llm.chat(messages, 300, None, 0.0)["content"])
        finally:
            await manager.knowledge.delete(user_id, stored["id"])

    assert text.strip()
    # Exact facts from page one: dinner in the hotel, Salerno.
    assert "Salerno" in text or "hotel" in text.lower(), text
    assert states(
        text,
        "The reply says there is a dinner (in the hotel) on the evening of Day 1, "
        "and attributes this to the person's itinerary document.",
    ), text
