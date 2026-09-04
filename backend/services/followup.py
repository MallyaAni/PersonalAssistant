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
import re
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from backend.core.prompts import load
from backend.services.transcript import transcript_lines

logger = logging.getLogger(__name__)

# A diagram is not a picture, however alike they look.
#
# There was no category for one until 2026-08-30, so the resolver called them
# pictures - the closest thing on offer - and the router believed it. Measured
# on a real thread: "draw the aqueduct one" routed to show_image and "make the
# diagram simpler" to edit_image, which edits photographs. Both would act on
# the wrong artifact or on none. The tools have always been distinct
# (create_diagram, and diagrams are stored as their own kind); only this list
# was not.
REFERS_TO = ("picture", "diagram", "task", "scout", "draft", "subject", "none")

# The order is load-bearing. The engine fills fields in the order they are
# declared, and `self_contained` used to come first - so the model had to
# restate the message before it had decided what the message was about.
# Measured 2026-08-30 on the operator's own group thread, where "try again"
# followed a run of failed diagram attempts: it restated "try again" as
# "try again", every run, and then had nothing left to name a subject from -
# empty 2/3, and "Try Again Flow" the rest of the time, which is the title
# of its own previous failure.
#
# The dependency runs one way: what it refers to, then the message written
# out in full, then the subject named from that. Restating first left the
# model echoing "try again"; naming the subject first left it blank 3/3 while
# the restatement carried the subject perfectly well. Each field is now asked
# for only once the thing it is derived from has been written.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "refers_to": {"type": "string", "enum": list(REFERS_TO)},
        "self_contained": {"type": "string", "maxLength": 600},
        "subject": {"type": "string", "maxLength": 120},
        # Whether the assistant's own last message offered to do something
        # that this message accepts. See `Resolution.accepts_offer`.
        "accepts_offer": {"type": "boolean"},
        # Whether this message is asking again for what the last one already
        # answered. See `Resolution.redoes_previous`.
        "redoes_previous": {"type": "boolean"},
    },
    "required": [
        "refers_to",
        "self_contained",
        "subject",
        "accepts_offer",
        "redoes_previous",
    ],
    "additionalProperties": False,
}
_MAX_TOKENS = 220
_HISTORY_TURNS = 4
# How much of a thread's opening is always shown: where it names its subject.
_OPENING_TURNS = 2
_HISTORY_CHARS = 2400


@dataclass(frozen=True, slots=True)
class Resolution:
    """The newest message restated to stand alone, and what it refers to."""

    self_contained: str
    refers_to: str
    subject: str
    # Whether the assistant's previous message offered to *do* something that
    # this message accepts.
    #
    # "Yes" is not an instruction on its own; it is an instruction only when
    # something was offered. Measured on the real model 2026-08-29: "yes"
    # after a plain weather answer routed a fresh weather call - agreeing with
    # a statement sent the assistant off doing work. The router now refuses to
    # take any tool for a bare acceptance that accepts nothing.
    #
    # The same question is asked of the readiness model for a tapback
    # (`backend/services/readiness.py`). Two places, deliberately: that one
    # runs in the iMessage worker before a turn exists and decides whether to
    # answer at all; this one runs inside every turn on every channel and
    # decides what may be done.
    accepts_offer: bool = False
    # Whether this message is asking again for something the previous turn
    # already answered - because the answer was wrong, off the subject, or
    # not what was wanted.
    #
    # This is the only signal in the system for the failure that reaches
    # people most. A tool that ran and returned the wrong content records a
    # success: the trace says `ran:7` and nothing is wrong anywhere except in
    # the answer. The person retrying is the evidence, and until now it was
    # discarded - which also means a corpus built from outcomes would label
    # that turn *successful* and train the next router to do it again.
    #
    # A judgement, so a model makes it: "try again", "no, I meant the
    # Arlington one" and "that's not what I asked" share no words, and the
    # four bounded classifiers this repository has deleted all died on
    # phrasing their author did not anticipate. It is deliberately narrow -
    # asking again for the *same* thing, not asking a next question - and
    # false when in doubt, because a wrong true blames a turn that was fine.
    redoes_previous: bool = False

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
            **({"redoes_previous": True} if self.redoes_previous else {}),
        }


# This turn's resolution, for the components after the router that need the
# same reading: the search composer and the research rounds. None when the
# turn had no history or the call failed.
current_followup: ContextVar[Resolution | None] = ContextVar("current_followup", default=None)


# The conversation the resolver reads: the last few turns, bounded.
def _recent(history: list[dict[str, Any]], zone: str = "", from_index: int | None = None) -> str:
    # Dated, because "that one" and "the same again" are resolved against
    # turns whose age changes the answer: a plan made last night is not the
    # plan for tonight (2026-08-29, a group told an ice-cream run that had
    # already happened was happening "tonight").
    #
    # Always the opening of the conversation, and always the recent end.
    #
    # A thread names its subject once, at the start, and then talks in
    # shorthand about it. Keeping only the tail loses the name and leaves
    # the shorthand: on 2026-08-31 the operator replied to a failed diagram
    # in a thread that opened with Roman aqueducts, and by then the visible
    # turns said only "the architecture thinking process". That is what got
    # drawn - a generic thinking-process flowchart - because it is all the
    # resolver could see. Both the old turn window and the old character
    # cap trimmed from the front, so the name went first in both.
    #
    # When the person replied to a specific message the middle opens at that
    # turn too, since that is the part of the conversation they are pointing
    # at.
    if not history:
        return ""
    last = len(history) - 1
    if from_index is not None:
        # A reply says which moment is meant, so the conversation is read as
        # it stood at that moment. What came after is the attempts being
        # asked about again, and their own wording is the thing that
        # corrupts the answer: on 2026-08-31 the turns after the replied-to
        # message were three failed diagrams and a reply naming one of them,
        # and the subject came back as the name of the failure instead of
        # the aqueduct the thread had been about. They are counted, not
        # quoted - the model should know retries happened without reading
        # what they were called.
        at = min(from_index, last)
        lines = transcript_lines(history[: at + 1], zone)
        after = last - at
        if after > 0:
            lines.append(
                f"[{after} later exchange{'s' if after != 1 else ''} followed, "
                "which is what they are asking about again]"
            )
        return _within_budget(lines)
    keep = set(range(min(_OPENING_TURNS, len(history))))
    keep |= set(range(max(0, last - _HISTORY_TURNS + 1), len(history)))
    chosen = sorted(keep)
    lines: list[str] = []
    previous: int | None = None
    for index in chosen:
        if previous is not None and index > previous + 1:
            lines.append("[...]")
        lines.extend(transcript_lines([history[index]], zone))
        previous = index
    return _within_budget(lines)


# Trim from the middle, never from the front. The front is where the
# subject was named, which is the one part that must survive.
def _within_budget(lines: list[str]) -> str:
    text = "\n".join(lines)
    if len(text) <= _HISTORY_CHARS:
        return text
    head = "\n".join(lines[:2])[: _HISTORY_CHARS // 3]
    tail = "\n".join(lines[2:])[-(_HISTORY_CHARS - len(head) - 8) :]
    return f"{head}\n[...]\n{tail}"


# Resolve one message against its conversation, or None when there is no
# conversation to resolve against or the model could not be reached. A
# failure here is never a failure of the turn: the router still sees the
# history and decides as it did before this step existed.
# The exchange a reply points at, rendered for the prompt.
#
# A person replying to an old bubble means the conversation that bubble
# belongs to, not the bubble's words alone: the message they pointed at on
# 2026-08-30 was "I couldn't create that diagram", which names no subject at
# all. So the turn is found in the history and both halves are shown - the
# request that produced it is where the subject actually lives.
#
# Matched by containment rather than equality because a long reply is
# delivered as several bubbles, and the person replied to one of them.
# Whether a turn's text is the bubble that was replied to.
#
# Containment in one direction only, plus a length guard, and both halves
# are load-bearing. A long reply is delivered as several bubbles and the
# person replied to one of them, so the bubble being inside the turn's text
# has to count. The reverse - the turn's text inside the bubble - only
# counts when it is substantially the whole of it, because otherwise any
# short message matches any long one that happens to contain those words:
# on 2026-08-31 "try again" matched "...please revise the request and try
# again", and since the search runs backwards it matched the newest such
# turn. The window then opened at the end of the thread rather than at the
# message being pointed at, which is the opposite of the point.
def _same_bubble(said: str, text: str) -> bool:
    if not text or not said:
        return False
    if said in text:
        return True
    return text in said and len(text) >= 0.6 * len(said)


def _answering_line(
    replying_to: str, history: list[dict[str, Any]]
) -> tuple[str, int | None]:
    said = " ".join(str(replying_to or "").split())
    if not said:
        return "", None
    shown, found = said[:1200], None
    for index in range(len(history) - 1, -1, -1):
        turn = history[index]
        answer = " ".join(str(turn.get("response") or "").split())
        asked = " ".join(str(turn.get("query") or "").split())
        matched = _same_bubble(said, answer) or _same_bubble(said, asked)
        if matched:
            # Matching is against the raw bubble - that is what the person
            # long-pressed. But the *quote* goes through the same
            # metadata-aware line the transcript uses, because a receipt's
            # raw text is a title pretending to be subject matter: on
            # 2026-08-31 a reply to "Created an editable diagram:
            # Architecture Thinking Process." put the title in front of the
            # resolver as if it were the thing, undoing what
            # transcript._answer_line exists to prevent.
            from backend.services.transcript import _answer_line

            rendered = " ".join(_answer_line(turn).split())
            shown = f"They asked: {asked[:600]}\nYou answered: {rendered[:900]}"
            found = index
            break
    return (
        "\n\nThey have replied directly to this earlier exchange, so it is "
        f"what their newest message is about:\n{shown}\n"
        "The words of that exchange lean on the conversation above it the "
        "same way any shorthand does: read them completed, as what the "
        "thread says they mean, not as a name in themselves.",
        found,
    )


async def resolve_followup(
    llm: Any,
    query: str,
    history: list[dict[str, Any]],
    zone: str = "",
    replying_to: str = "",
) -> Resolution | None:
    answered, matched_at = _answering_line(replying_to, history or [])
    recent = _recent(history or [], zone, matched_at)
    if not recent or not query.strip():
        return None
    # When the person used a native reply they named the message themselves,
    # and that beats anything inferred from the words. Given as its own line
    # rather than folded into the transcript, because the whole point is that
    # it is not the most recent message - and the transcript's own ordering
    # would otherwise say it was.
    messages = [
        {"role": "system", "content": load("referent/followup")},
        {
            "role": "user",
            "content": f"Recent conversation:\n{recent}{answered}\n\nNewest message: {query}",
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
    # Absent means false, which is the safe direction: the router withholds
    # every tool from a bare acceptance that accepts nothing, and an
    # unreadable answer should leave it answering in words rather than acting.
    return Resolution(
        restated,
        refers_to,
        subject,
        bool(payload.get("accepts_offer")),
        # Absent means false here too, and for the same reason in reverse: a
        # missing field must not accuse a turn that was fine.
        bool(payload.get("redoes_previous")),
    )


# One line for the router: the reading beside the person's own words.
def describe(resolution: Resolution, query: str) -> str:
    if not resolution.changes(query):
        return ""
    # `.get`, not `[]`. A category added to REFERS_TO and forgotten here raised
    # KeyError inside the router and took the whole turn down - caught in
    # measurement on 2026-08-30 when "diagram" was added. A reading nobody has
    # written a phrase for is worth less than the reading; it is never worth
    # the turn.
    about = {
        "picture": "a picture the assistant made or was sent",
        "diagram": "a diagram the assistant drew, which is not a picture and is redrawn rather than edited",
        "task": "a reminder or task the person set up",
        "scout": "Scout's own sweep or its schedule",
        "draft": "the text being written together",
        "subject": "the thing under discussion",
        "none": "nothing earlier",
    }.get(resolution.refers_to, "something earlier in the conversation")
    subject = f" ({resolution.subject})" if resolution.subject else ""
    return (
        f"Read in context as: {resolution.self_contained}\n"
        f"It refers to {about}{subject}."
    )


# Whether a message is nothing but assent.
#
# The bound on a guard that refuses to act: only a message with no content of
# its own can reach it, so "yes, and book the later one" is routed normally
# however the offer question is answered. Matched on the whole message after
# punctuation and filler are stripped, never as a substring - "yes" inside
# "yesterday" or "can you say yes for me" is not assent.
_ASSENT = frozenset(
    {
        "yes", "yes please", "yes pls", "yep", "yeah", "yea", "ya", "yup",
        "sure", "ok", "okay", "k", "kk", "fine", "alright", "all right",
        "do it", "go ahead", "go for it", "please do", "sounds good",
        "yes do it", "yeah do it", "yes go ahead", "yeah go ahead",
        "yes please do", "sure do it", "ok do it", "okay do it", "yes thanks",
        "perfect", "great", "cool", "nice", "lets do it", "let's do it",
    }
)
_FILLER = re.compile(r"[^\w\s']+")


def is_bare_acceptance(message: str) -> bool:
    stripped = _FILLER.sub(" ", str(message or "").casefold())
    collapsed = " ".join(stripped.split())
    return collapsed in _ASSENT

