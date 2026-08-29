"""What the newest message is about, decided once before anything acts on it.

Every incident of 2026-08-26/27 was a second turn about something the first
turn mentioned, and each component that had to resolve "this" - the router,
the search composer, the task picker, the memory agent - did so separately
and could get it wrong its own way. This resolves it once, with the routing
model and a schema, and hands one reading to all of them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from backend.core.prompts import load
from backend.services.transcript import transcript_lines

logger = logging.getLogger(__name__)

REFERS_TO = ("picture", "task", "scout", "draft", "subject", "none")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "self_contained": {"type": "string", "maxLength": 600},
        "refers_to": {"type": "string", "enum": list(REFERS_TO)},
        "subject": {"type": "string", "maxLength": 120},
    },
    "required": ["self_contained", "refers_to", "subject"],
    "additionalProperties": False,
}
_MAX_TOKENS = 220
_HISTORY_TURNS = 4
_HISTORY_CHARS = 2400


@dataclass(frozen=True, slots=True)
class Resolution:
    """The newest message restated to stand alone, and what it refers to."""

    self_contained: str
    refers_to: str
    subject: str

    # Whether the reading adds anything beyond the message itself.
    def changes(self, query: str) -> bool:
        return self.self_contained.strip() != query.strip() or self.refers_to != "none"

    # The reading as plain data - the turn trace and the reply's context both
    # carry exactly this, so explain_turn and the reply model read one thing.
    def as_dict(self, limit: int = 160) -> dict[str, str]:
        return {
            "refers_to": self.refers_to,
            "subject": self.subject,
            "as": self.self_contained[:limit],
        }


# This turn's resolution, for the components after the router that need the
# same reading: the search composer and the research rounds. None when the
# turn had no history or the call failed.
current_followup: ContextVar[Resolution | None] = ContextVar("current_followup", default=None)


# The conversation the resolver reads: the last few turns, bounded.
def _recent(history: list[dict[str, Any]], zone: str = "") -> str:
    # Dated, because "that one" and "the same again" are resolved against
    # turns whose age changes the answer: a plan made last night is not the
    # plan for tonight (2026-08-29, a group told an ice-cream run that had
    # already happened was happening "tonight").
    return "\n".join(transcript_lines(history[-_HISTORY_TURNS:], zone))[-_HISTORY_CHARS:]


# Resolve one message against its conversation, or None when there is no
# conversation to resolve against or the model could not be reached. A
# failure here is never a failure of the turn: the router still sees the
# history and decides as it did before this step existed.
async def resolve_followup(
    llm: Any, query: str, history: list[dict[str, Any]], zone: str = ""
) -> Resolution | None:
    recent = _recent(history or [], zone)
    if not recent or not query.strip():
        return None
    messages = [
        {"role": "system", "content": load("referent/followup")},
        {
            "role": "user",
            "content": f"Recent conversation:\n{recent}\n\nNewest message: {query}",
        },
    ]
    try:
        answer = await asyncio.to_thread(llm.chat, messages, _MAX_TOKENS, _SCHEMA, 0.0)
    except Exception:
        logger.warning("Follow-up resolution failed; routing on the raw message", exc_info=True)
        return None
    return parse_resolution(answer, query)


# The model's reading as a Resolution, or None when it is unreadable. An
# empty restatement falls back to the message itself.
def parse_resolution(answer: Any, query: str) -> Resolution | None:
    payload = answer.get("content") if isinstance(answer, dict) and "content" in answer else answer
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None
    refers_to = str(payload.get("refers_to") or "none")
    if refers_to not in REFERS_TO:
        refers_to = "none"
    restated = " ".join(str(payload.get("self_contained") or "").split()) or query.strip()
    subject = " ".join(str(payload.get("subject") or "").split())[:120]
    return Resolution(restated, refers_to, subject)


# One line for the router: the reading beside the person's own words.
def describe(resolution: Resolution, query: str) -> str:
    if not resolution.changes(query):
        return ""
    about = {
        "picture": "a picture the assistant made or was sent",
        "task": "a reminder or task the person set up",
        "scout": "Scout's own sweep or its schedule",
        "draft": "the text being written together",
        "subject": "the thing under discussion",
        "none": "nothing earlier",
    }[resolution.refers_to]
    subject = f" ({resolution.subject})" if resolution.subject else ""
    return (
        f"Read in context as: {resolution.self_contained}\n"
        f"It refers to {about}{subject}."
    )
