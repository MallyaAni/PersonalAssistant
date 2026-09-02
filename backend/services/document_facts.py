"""Durable facts from a freshly shared document, into memory with attribution.

A document a person hands the assistant usually carries facts worth
remembering - an itinerary's dates and hotel, a lease's rent and term - and
the words it arrives with say whose they are ("we are going to do this trip").
Stage 3-4 of docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md: the same memory
classifier that reads a spoken turn reads the sharer's words plus what the
document says, and the same attribution rule decides the owners - the
sharer's own store and the room's, never another member's on the sharer's
word. Passages stay in the knowledge store for retrieval; this is only about
what should also be *remembered*.

Runs after the upload has been stored, in the background, and never fails
the upload: a classifier error costs the facts, not the document. The queue
(a document parsed later, when the parser is back) does not run this pass;
its facts arrive when the person next talks about the document.
"""
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# How much of the document the classifier reads. Enough for a two-page
# itinerary or the head of a contract; a fact buried on page 40 is still
# retrievable, just not proposed as memory here.
EXCERPT_CHARS = 1_800


# The classifier's utterance: the sharer's own words first (they carry the
# attribution - "we", "I", a name), then what the document says, marked as
# such so the model does not read the document's voice as the person's.
def document_utterance(title: str, caption: str, markdown: str) -> str:
    text = re.sub(r"<!--\s*page\s*-->", " ", markdown or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    excerpt = text[:EXCERPT_CHARS].rstrip()
    if len(text) > EXCERPT_CHARS:
        excerpt += " ..."
    lead = caption.strip() or "here's a document"
    return f'{lead}\n\n(shared a document "{title.strip()}", which says:)\n{excerpt}'


# What the document establishes, as one to three plain statements. The memory
# classifier is tuned to facts a person states; a document's own voice under
# "which says:" reads as content to discuss and proposed nothing (0/3 on the
# itinerary, 2026-09-02). So the document is first read into statements, and
# the classifier hears them as the sharer's own words. Structured output on
# the routing engine, temperature zero - the repository's pattern for a
# judgement that must not wander.
_DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        # The one sentence worth remembering. The memory classifier keeps a
        # plan stated short and plain ("Jenos and I are going on the Amalfi
        # Choral Tour, October 11 to 15" -> a fact) and refuses a paragraph of
        # detail (0/4 shapes, 2026-09-02), so this is the whole message it
        # hears, and the statements are only for the record.
        "headline": {"type": "string"},
        "statements": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["headline", "statements"],
    "additionalProperties": False,
}
_DIGEST_SYSTEM = (
    "A person just shared a document, with the words quoted as `caption`. Give "
    "`headline`: ONE plain sentence of at most 25 words, in the sharer's own "
    "first-person voice, stating the durable fact their words and the document "
    "together establish - who (from their words: we, I, a name) is doing what, "
    "where, and when or for how much. Example shape: \"We are going on the "
    "Amalfi Choral Tour, October 11 to 15, staying at the Grand Hotel of "
    "Salerno.\" Ignore any question in the caption. Give `statements`: up to "
    "three short sentences of supporting detail from the document. Only what "
    "the words and the document say; nothing invented. If no durable fact is "
    "established, headline is an empty string. Answer only through the schema."
)


def digest_document(llm: Any, title: str, markdown: str, caption: str = "") -> tuple[str, list[str]]:
    body = document_utterance(title, "", markdown).split("\n", 2)[-1]
    messages = [
        {"role": "system", "content": _DIGEST_SYSTEM},
        {
            "role": "user",
            "content": f'caption: "{caption.strip() or "here is a document"}"\n\nDocument "{title}":\n{body}',
        },
    ]
    result = llm.chat(messages, 600, _DIGEST_SCHEMA, 0.0)
    try:
        payload = json.loads(str(result.get("content") or "{}"))
    except json.JSONDecodeError:
        return "", []
    headline = " ".join(str(payload.get("headline") or "").split())
    statements = [" ".join(str(item).split()) for item in (payload.get("statements") or []) if str(item).strip()][:3]
    return headline, statements


# The sharer's statement, as the classifier hears it: the digest's one
# first-person sentence when there is one (it already folds in who from the
# caption), else the declarative part of the caption alone (a trailing
# question is a request, not a fact). One short sentence on purpose: the
# classifier keeps "Jenos and I are going on the Amalfi Choral Tour, October
# 11 to 15" and refuses a paragraph of the same content.
def facts_utterance(caption: str, headline: str) -> str:
    if headline.strip():
        return headline.strip()
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", caption.strip()) if part.strip()]
    declarative = " ".join(part for part in sentences if not part.endswith("?"))
    lead = declarative or "I'm sharing this document."
    return lead if lead.endswith((".", "!")) else lead + "."


# Classify and persist, through the conversation service's own memory path so
# rooms, attribution, receipts and undo all behave exactly as for a spoken
# turn. `room` is the same dict the room turn carries (speaker_user_id,
# speaker_name, members) or None one-to-one.
async def propose_document_facts(
    service: Any,
    tracer: Any,
    user_id: str,
    conversation_id: str | None,
    title: str,
    markdown: str,
    caption: str,
    room: dict[str, Any] | None,
) -> int:
    try:
        from backend.core.dependencies import get_routing_llm_client

        trace_id = tracer.start_trace(user_id)
        headline, _statements = digest_document(get_routing_llm_client(), title, markdown, caption)
        if not headline:
            return 0
        utterance = facts_utterance(caption, headline)
        candidates = await service._classify_memory_proposals(utterance, trace_id, user_id, room=room)
        if not candidates:
            return 0
        saved = await service._persist_memory_proposals(
            user_id, conversation_id or "", trace_id, candidates, room=room
        )
        count = len(saved) if isinstance(saved, (list, tuple)) else int(bool(saved))
        logger.info("document_facts_saved", extra={"user": user_id, "title": title, "count": count})
        return count
    except Exception:
        logger.warning("Document facts pass failed; the document itself is stored", exc_info=True)
        return 0
