"""Document knowledge changes the answer.

Phase 1 of docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md: the reply consults the
native KnowledgeStore every turn and renders what it finds as cited
passages. Structural tests can prove the block is rendered; only the real
model can prove the reply then answers FROM the document, names it, and
declines to invent when the document is silent. The seeded facts follow the
drop's test-matrix discipline: a number that appears nowhere in training data
either surfaces or it does not.

The third test exercises the retrieval half for real - ingest through the
store, search with the production embedding - and is skipped where the
database or embedding runtime is unreachable, like every other test here.
"""
import uuid

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages

pytestmark = pytest.mark.asyncio

_DOCUMENT = {
    "title": "Roman aqueduct field notes",
    "source_uri": "upload://roman-aqueduct-field-notes.pdf",
}

# One passage, one seeded fact. 214 appears in no training corpus for this
# aqueduct; it is either read from the passage or invented.
_KNOWLEDGE = {
    "knowledge": [
        {
            "content": (
                "The Vallis Umbra crossing was the longest span on the line: "
                "214 arches carried the channel across the valley floor, each "
                "roughly 5.6 metres wide at the springing."
            ),
            "position": 3,
            "document": dict(_DOCUMENT),
        }
    ]
}

_HISTORY = [
    {"role": "user", "content": "i uploaded my aqueduct notes earlier"},
    {"role": "assistant", "content": "Got them - ask me anything about them."},
]


def _messages(context: dict, query: str) -> list[dict]:
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(_HISTORY)
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": query})
    return messages


async def test_a_fact_in_the_document_is_answered_from_it_and_cited(llm):
    from backend.tests.functional.semantic import states

    result = llm.chat(
        _messages(dict(_KNOWLEDGE), "how many arches crossed the vallis umbra?"),
        300,
        None,
        0.0,
    )
    text = str(result["content"])

    assert text.strip()
    # The exact fact is not about meaning: it is there or it is not.
    assert "214" in text, text
    # The citation is: the reply must say where the number came from.
    assert states(
        text,
        "The reply attributes the answer to the person's own notes or document "
        "(for example their aqueduct notes) rather than to general knowledge.",
    ), text


async def test_a_fact_absent_from_the_document_is_declined_not_invented(llm):
    from backend.tests.functional.semantic import states

    result = llm.chat(
        _messages(dict(_KNOWLEDGE), "what year was the vallis umbra crossing finished?"),
        300,
        None,
        0.0,
    )
    text = str(result["content"])

    assert text.strip()
    assert states(
        text,
        "The reply says the year is not in the person's document or that it "
        "does not have that information, rather than stating a year.",
    ), text


# The retrieval half, for real: ingest through the store with the production
# embedding, then search with a question. The chunk holding the fact must come
# back, or nothing above ever reaches the model in production.
async def test_an_ingested_document_is_found_by_a_question_about_it():
    try:
        from backend.core.dependencies import get_agent_memory_manager, get_embedding_provider
        from backend.database.session import AsyncSessionLocal
    except Exception as exc:  # pragma: no cover - environment, not behaviour
        pytest.skip(f"knowledge store not importable here: {type(exc).__name__}")

    user_id = f"functional-doc-{uuid.uuid4().hex[:8]}"
    content = (
        "Field notes, Roman aqueduct survey.\n\n"
        + _KNOWLEDGE["knowledge"][0]["content"]
        + "\n\nThe settling tank at the head of the line was cleaned each spring."
    )
    try:
        async with AsyncSessionLocal() as session:
            manager = get_agent_memory_manager(session, get_embedding_provider())
            document = await manager.knowledge.ingest(
                user_id, _DOCUMENT["title"], content, _DOCUMENT["source_uri"], "user_knowledge"
            )
            try:
                found = await manager.knowledge.search(
                    user_id, "how many arches crossed the vallis umbra?", 6
                )
                assert found, "the question retrieved nothing from the ingested document"
                assert any("214" in item.get("content", "") for item in found), found
                assert found[0]["document"]["title"] == _DOCUMENT["title"], found[0]
            finally:
                await manager.knowledge.delete(user_id, document["id"])
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database or embedding runtime unreachable: {type(exc).__name__}")


# The document cutoff, measured on the live miss: "Scout whats on evening of
# day 1?" sat 0.46 from the itinerary's Day 1 passage, which the memory
# policy (0.35) rejected outright - the reply then answered from an older
# plan. Under the document policy the passage comes back for the person's
# own words, unaided by any restatement.
async def test_a_documents_passage_is_found_for_the_persons_own_shorthand():
    from backend.core.dependencies import get_agent_memory_manager, get_embedding_provider
    from backend.database.session import AsyncSessionLocal

    itinerary = (
        "## Day 1: Sun., October 11\n\n"
        "Arrivals throughout the day - Grand Hotel of Salerno 6:00 p.m. - "
        "Orientation 7:30 p.m. - Dinner in Hotel (included)\n\n"
        "## Day 2: Mon., October 12\n\nExcursion - 8:30 a.m. departure Pompeii and/or Paestum\n\n"
        "## Day 5: Thurs., October 15\n\nMorning - Independent: Boat trip along the coast (on your own)"
    )
    user_id = f"functional-shorthand-{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            manager = get_agent_memory_manager(session, get_embedding_provider())
            stored = await manager.knowledge.ingest(
                user_id, _DOCUMENT["title"], itinerary, _DOCUMENT["source_uri"], "uploaded_document"
            )
            try:
                found = await manager.knowledge.search(user_id, "Scout whats on evening of day 1?", 6)
                assert found, "the shorthand retrieved nothing under the document policy"
                assert any("Day 1" in item.get("content", "") for item in found), [
                    item.get("content", "")[:60] for item in found
                ]
            finally:
                await manager.knowledge.delete(user_id, stored["id"])
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database or embedding runtime unreachable: {type(exc).__name__}")
