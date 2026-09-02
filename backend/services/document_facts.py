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
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
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
        # Each with whether it holds only around the document's dates (a
        # departure time, a meeting point) or outlives them (the hotel, who
        # went). Dated statements are saved with an expiry; durable ones are
        # not. Retention, docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md.
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "dated": {"type": "boolean"}},
                "required": ["text", "dated"],
                "additionalProperties": False,
            },
            "maxItems": 3,
        },
        # The last date the document is about, ISO (YYYY-MM-DD), read after
        # the statements: an itinerary's final day, a ticket's date. Empty
        # for undated material - a lease, a recipe, a manual.
        "about_until": {"type": "string"},
    },
    "required": ["headline", "statements", "about_until"],
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
    "three short sentences of supporting detail from the document, each with "
    "`dated`: true when it holds only around the document's own dates (a "
    "departure time, a meeting point, a day's schedule), false when it outlives "
    "them (where they stayed, who went, what it cost). Give `about_until`: the "
    "last date the document is about as YYYY-MM-DD (an itinerary's final day, a "
    "ticket's or booking's date), or an empty string for undated material such "
    "as a lease, a recipe, or a manual. Only what the words and the document "
    "say; nothing invented. If no durable fact is established, headline is an "
    "empty string. Answer only through the schema."
)


@dataclass(frozen=True, slots=True)
class Digest:
    """What the digest step read: the one durable sentence, the supporting
    statements split by whether they outlive the document's dates, and the
    last date the document is about (None when it has none)."""

    headline: str
    statements: list[str]
    dated: list[str]
    about_until: date | None


def _iso_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def digest_document(llm: Any, title: str, markdown: str, caption: str = "", today: date | None = None) -> Digest:
    body = document_utterance(title, "", markdown).split("\n", 2)[-1]
    # An itinerary says "October 15" and rarely the year; told today's date,
    # the digest resolves it to the next such date, as the router does for
    # "tomorrow". Without it the date came back empty (0/3, 2026-09-02).
    today = today or datetime.now(UTC).date()
    messages = [
        {
            "role": "system",
            "content": _DIGEST_SYSTEM
            + f" Today is {today.isoformat()}; a date the document gives without a year is the next such date from today.",
        },
        {
            "role": "user",
            "content": f'caption: "{caption.strip() or "here is a document"}"\n\nDocument "{title}":\n{body}',
        },
    ]
    result = llm.chat(messages, 700, _DIGEST_SCHEMA, 0.0)
    try:
        payload = json.loads(str(result.get("content") or "{}"))
    except json.JSONDecodeError:
        return Digest("", [], [], None)
    headline = " ".join(str(payload.get("headline") or "").split())
    durable: list[str] = []
    dated: list[str] = []
    for item in (payload.get("statements") or [])[:3]:
        if isinstance(item, dict):
            text, is_dated = " ".join(str(item.get("text") or "").split()), bool(item.get("dated"))
        else:
            text, is_dated = " ".join(str(item).split()), False
        if text:
            (dated if is_dated else durable).append(text)
    return Digest(headline, durable, dated, _iso_date(payload.get("about_until")))


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
    document_id: str | None = None,
) -> int:
    try:
        from backend.config.settings import settings
        from backend.core.dependencies import get_routing_llm_client
        trace_id = tracer.start_trace(user_id)
        digest = digest_document(get_routing_llm_client(), title, markdown, caption)
        # The date the document is about, on its row: retention archives it
        # a grace period after that date (document_retention.py).
        if document_id and digest.about_until and getattr(service, "agent_memory", None) is not None:
            try:
                await service.agent_memory.knowledge.set_about_until(user_id, document_id, digest.about_until)
            except Exception:
                logger.warning("Could not record about_until for document %s", document_id, exc_info=True)
        headline = digest.headline
        if not headline:
            return 0
        utterance = facts_utterance(caption, headline)
        candidates = await service._classify_memory_proposals(utterance, trace_id, user_id, room=room)
        # Dated statements (a departure time, a meeting point) are the
        # sharer's words too, saved with an expiry on the document's last
        # date plus the grace period, so they leave memory with the event.
        if digest.dated and digest.about_until:
            expires_at = datetime.combine(
                digest.about_until + timedelta(days=settings.KNOWLEDGE_ARCHIVE_GRACE_DAYS),
                time.min,
                tzinfo=UTC,
            )
            for statement in digest.dated:
                dated = await service._classify_memory_proposals(
                    facts_utterance(caption, statement), trace_id, user_id, room=room
                )
                candidates = tuple(candidates) + tuple({**item, "expires_at": expires_at} for item in dated)
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
