"""Search results in, typed event records out - with every claim traced.

On 2026-08-29 a "what's on in Canggu" listing reached a phone with invented
map links and a venue's opening hours printed as an event's start time. The
links are fenced now (`backend/core/links.py`). This module removes the other
half of that failure: the model no longer writes the listing at all.

It is asked instead to *quote* - which result each event came from, and the
exact phrase in it that states the day, and the one that states the price.
Code then checks the phrase is really in that result, parses the date and the
clock time out of it, and builds the links from the venue. The model's only
free text is the one line saying what the thing is, and that line is passed
through the link fence so an address cannot hide in it.

The consequence worth stating plainly: an event whose source never said when
it happens does not appear. Neither does one whose "time" turned out to be
opening hours. The caller is told how many were dropped and why, because
"nothing is on" and "nothing was dated" must never look the same to a reader.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from backend.core.grounding import mentions, states
from backend.core.links import fence_text
from backend.core.prompts import load

# The one explicit-date parser in this repository, and the boundary cleaner
# every untrusted field in this codebase already passes through. Importing
# them is the point: a second date parser would be a second set of bugs, and
# the two would disagree about "Sept. 12" within a month.
from backend.core.dates import extract_explicit_date
from backend.discovery.events import clean_text

logger = logging.getLogger(__name__)

MAX_EVENTS = 16
MAX_RESULTS_READ = 10
_MAX_TOKENS = 2_000
# What the extractor reads of each result. It was 700 characters, which
# on 2026-09-02 cut ARLnow's events page - 2,300 characters holding a dozen
# dated Arlington events - to its first two, while a New York page's one
# event survived whole; the listing for "events in the area this week" was
# that one event. The search already bounds a result at SEARCH_RESULT_CHARS
# (2,500), so reading it all costs at most ten results of that.
_CONTENT_CHARS = 2_500
_WHAT_WORDS = 24

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# "4pm", "4 PM", "16:00", "4:30pm", "8.30 pm" - the forms a listing writes.
# The hour is required; everything else is optional, and a bare number with no
# am/pm and no colon is not a time ("from 4" could be a date, a price, a lane).
_CLOCK = re.compile(
    r"\b(?P<h>[01]?\d|2[0-3])\s*(?:[:.](?P<m>[0-5]\d))?\s*(?P<ampm>am|pm)\b"
    r"|\b(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)\b",
    re.IGNORECASE,
)

# What is left of "..., see <link>" once the link is gone: a short trailing
# clause after a comma, or a bare connector at the end of the line.
_TRAILING_CLAUSE = re.compile(
    r"(?:\s*[,;:-]\s*(?:\w+\s+){0,3}\w*|\s+(?:see|at|via|from|here|visit|check|details|more))\s*$",
    re.IGNORECASE,
)

_KINDS = ("one_off_date", "recurring_weekday", "opening_hours", "not_stated")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "maxItems": MAX_EVENTS,
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "integer"},
                    "name": {"type": "string"},
                    "venue": {"type": "string"},
                    "area": {"type": "string"},
                    "artist": {"type": "string"},
                    "when_text": {"type": "string"},
                    "when_kind": {"type": "string", "enum": list(_KINDS)},
                    "price_text": {"type": "string"},
                    "what": {"type": "string"},
                },
                "required": [
                    "source", "name", "venue", "area", "artist",
                    "when_text", "when_kind", "price_text", "what",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ListedEvent:
    """One event every field of which some result actually stated."""

    name: str
    venue: str
    area: str
    artist: str
    what: str
    # The phrase the day was read from, kept so the listing can show its work.
    when_text: str
    recurring: bool
    starts_at: datetime | None
    start_time: time | None
    price_text: str
    source_url: str
    source_title: str
    # Which result this came from, 1-based, in the order the ranker put them.
    #
    # That order is the only per-person signal on this path: the ranker reads
    # the question, the place and what is known about the person, and puts the
    # results it judges most useful to *them* first. Carried here because the
    # listing shows fewer events than the extraction finds, and choosing which
    # ones to drop by date alone threw that judgement away - a Tuesday craft
    # fair displacing a Saturday salsa night purely on the calendar.
    source_rank: int = 999
    # Whether this is close enough to where the person is to be worth
    # listing. Judged by the model that already writes each event's line,
    # because "is Colonial Heights near Arlington" is a question about the
    # world, not a string comparison - and a listing with no notion of
    # distance led with an event two hours away (2026-09-03).
    near: bool = True

    # Where the person would go to check it. Never model-authored.
    @property
    def day(self) -> date | None:
        return self.starts_at.date() if self.starts_at else None


@dataclass(frozen=True, slots=True)
class Extraction:
    """What survived, and what did not - the second half matters to the reader."""

    events: tuple[ListedEvent, ...] = ()
    # Counted by reason, so the reply can say "three more had no date given"
    # rather than quietly showing a shorter list.
    undated: int = 0
    opening_hours: int = 0
    unsourced: int = 0

    @property
    def dropped(self) -> int:
        return self.undated + self.opening_hours + self.unsourced


# Pull typed events out of this turn's results. Never raises: an events turn
# that cannot be typed falls back to the prose path, which the link fence
# still guards.
async def extract_events(
    llm: Any,
    results: list[dict[str, Any]],
    now: datetime | None = None,
    known: tuple[str, ...] = (),
    place: str = "",
) -> Extraction:
    usable = [item for item in (results or []) if isinstance(item, dict)][:MAX_RESULTS_READ]
    if not usable or llm is None:
        return Extraction()
    moment = now or datetime.now(UTC)
    listing = "\n\n".join(
        f"[{index}] {str(item.get('title') or '')[:200]}\n"
        f"{str(item.get('content') or '')[:_CONTENT_CHARS]}"
        for index, item in enumerate(usable, start=1)
    )
    try:
        messages = [
            {"role": "system", "content": load("search/events")},
            {
                "role": "user",
                "content": f"Today: {moment.strftime('%A %Y-%m-%d')}\n\nResults:\n\n{listing}",
            },
        ]
        answer = await asyncio.to_thread(llm.chat, messages, _MAX_TOKENS, _SCHEMA, 0.0)
    except Exception:
        logger.warning("Event extraction call failed; keeping the prose listing", exc_info=True)
        return Extraction()
    found = build_extraction(_parse(answer), usable, moment)
    # Which events exist is now settled, and only then is the reader mentioned.
    # Measured on the real model 2026-08-29: told about the reader during
    # extraction, it *filtered* - one person got only the salsa night, the
    # other only the book club - so two people asking the same question got
    # different facts and the dropped-count stopped being true. Separating the
    # two passes makes that impossible rather than discouraged.
    return await describe_for(llm, found, known, moment, place)


# The model's records, checked against the results they name. Split out from
# the call so every rule below is testable without a model.
def build_extraction(
    records: list[dict[str, Any]],
    results: list[dict[str, Any]],
    now: datetime,
) -> Extraction:
    kept: list[ListedEvent] = []
    undated = opening_hours = unsourced = 0
    seen: set[tuple[str, str]] = set()
    for record in records[:MAX_EVENTS]:
        source = _index(record.get("source"), len(results))
        if source is None:
            unsourced += 1
            continue
        result = results[source - 1]
        evidence = f"{result.get('title') or ''} {result.get('content') or ''}"
        name = _quoted(record.get("name"), evidence, 160)
        venue = _quoted(record.get("venue"), evidence, 120)
        if not name or not venue:
            # Nothing to show and nothing to build a map link from.
            unsourced += 1
            continue
        kind = str(record.get("when_kind") or "").strip().lower()
        when_text = clean_text(str(record.get("when_text") or ""), 160) or ""
        if kind == "opening_hours":
            opening_hours += 1
            continue
        # The phrase must be in the result word for word. This is the check
        # the 29 August listing did not have.
        if kind not in ("one_off_date", "recurring_weekday") or not states(when_text, evidence):
            undated += 1
            continue
        starts_at = _resolve_day(when_text, kind, now)
        if starts_at is None:
            undated += 1
            continue
        clock = _first_clock(when_text) or _clock_in_the_same_listing(when_text, evidence)
        if clock is not None:
            starts_at = datetime.combine(starts_at.date(), clock, tzinfo=UTC)
        key = (name.casefold(), starts_at.date().isoformat())
        if key in seen:
            continue
        seen.add(key)
        price = record.get("price_text") or ""
        kept.append(
            ListedEvent(
                name=name,
                venue=venue,
                area=_quoted(record.get("area"), evidence, 80) or "",
                artist=_quoted(record.get("artist"), evidence, 80) or "",
                what=_own_words(record.get("what")),
                when_text=when_text,
                recurring=kind == "recurring_weekday",
                starts_at=starts_at,
                start_time=clock,
                price_text=price if states(price, evidence) else "",
                source_url=str(result.get("url") or ""),
                source_title=str(result.get("title") or "")[:200],
                source_rank=source,
            )
        )
    # Date order for reading; the fit rank is preserved on each record so the
    # renderer can choose *which* events survive a cut before it groups them.
    kept.sort(key=lambda event: (event.starts_at or datetime.max.replace(tzinfo=UTC), event.name))
    return Extraction(tuple(kept), undated, opening_hours, unsourced)


# A 1-based result number the model may have written as a string or as "[2]".
def _index(value: Any, count: int) -> int | None:
    try:
        number = int(re.sub(r"[^\d-]", "", str(value)) or "x")
    except ValueError:
        return None
    return number if 1 <= number <= count else None


# A field the result must actually carry. Bounded and cleaned first, so a
# model that returns a paragraph cannot put one in a listing.
def _quoted(value: Any, evidence: str, limit: int) -> str:
    text = clean_text(str(value or ""), limit) or ""
    if not text:
        return ""
    return text if mentions(text, evidence) else ""


# The one field in the model's own words - so it is the one field an address
# could hide in. Fenced with nothing allowed, then bounded to a line.
#
# When the fence does remove something, the clause that introduced it goes
# too. "Deep house on the grass, see <link>" becomes "Deep house on the
# grass", not "Deep house on the grass, see" - a sentence trailing off is a
# visible defect where a missing link is not, and the clause was only ever
# there to carry the address.
def _own_words(value: Any) -> str:
    text = clean_text(str(value or ""), 200) or ""
    if not text:
        return ""
    fenced, dropped = fence_text(text, frozenset(), "")
    if dropped:
        fenced = _TRAILING_CLAUSE.sub("", fenced).rstrip(" ,;:-")
    words = fenced.split()
    return " ".join(words[:_WHAT_WORDS])


# The day a quoted phrase names, or None. An explicit date is parsed by the
# repository's one date parser; a weekday resolves to its next occurrence,
# which is a fact about the calendar rather than a guess about the event.
def _resolve_day(when_text: str, kind: str, now: datetime) -> datetime | None:
    if kind == "one_off_date":
        return extract_explicit_date(when_text, now)
    lowered = when_text.casefold()
    for name, number in _WEEKDAYS.items():
        if name in lowered or f"{name[:3]}s" in lowered:
            ahead = (number - now.weekday()) % 7
            return datetime.combine(
                (now + timedelta(days=ahead)).date(), time(0, 0), tzinfo=UTC
            )
    return None


# The first clock time stated in the phrase, or None when it states only a
# day. None is rendered as a day with no time rather than an invented one.
def _first_clock(text: str) -> time | None:
    match = _CLOCK.search(text or "")
    if match is None:
        return None
    if match.group("h24") is not None:
        return time(int(match.group("h24")), int(match.group("m24")))
    hour = int(match.group("h"))
    minute = int(match.group("m") or 0)
    meridiem = (match.group("ampm") or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return time(hour % 24, minute)


# The clock time stated alongside the date, when the model quoted only the
# date. "Sunset Session on Saturday 5 September 2026 at Potato Head,
# Seminyak. Doors 6pm, entry IDR 250k" is one listing, and returning "time not
# listed" for it loses something the page plainly said - measured on the real
# model 2026-08-29, which quoted the date and dropped the doors time.
#
# Two bounds, and together they are the safety property. The clock must be
# within a short window after the quoted date, and it must be introduced by a
# word that means a start: "doors", "from", "starts", "begins", "kicks off".
# A bare clock anywhere near is exactly how "open until 11pm" or "kitchen
# until 10pm" becomes an event's start time, which is the failure this whole
# module exists to end.
_WINDOW_CHARS = 120
_START_WORD = re.compile(
    r"\b(?:doors?|from|starts?|starting|begins?|kicks?\s+off)\b[^.\n]{0,14}?"
    r"(?P<clock>\b(?:[01]?\d|2[0-3])\s*(?:[:.][0-5]\d)?\s*(?:am|pm)\b"
    r"|\b(?:[01]?\d|2[0-3]):[0-5]\d\b)",
    re.IGNORECASE,
)


def _clock_in_the_same_listing(when_text: str, evidence: str) -> time | None:
    if not when_text:
        return None
    haystack = evidence or ""
    at = haystack.casefold().find(when_text.casefold())
    if at < 0:
        return None
    window = haystack[at + len(when_text) : at + len(when_text) + _WINDOW_CHARS]
    match = _START_WORD.search(window)
    return _first_clock(match.group("clock")) if match else None


# The records out of whatever shape the engine returned them in.
def _parse(answer: Any) -> list[dict[str, Any]]:
    payload = answer
    if isinstance(answer, dict) and "content" in answer:
        payload = answer["content"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    if not isinstance(payload, dict):
        return []
    records = payload.get("events")
    return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []


_LINES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "maxItems": MAX_EVENTS,
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "what": {"type": "string"},
                    "near": {"type": "boolean"},
                },
                "required": ["index", "what", "near"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


# Rewrite each event's one line for the person it is going to.
#
# The event set is an input here and is never returned differently: this
# function maps descriptions onto events by index and keeps the extractor's
# own line for anything it does not get back. So a reader can change how an
# evening is described and can never change which evenings there are, what
# time they start, or how many were dropped - the failure this exists to
# prevent, measured before it shipped.
async def describe_for(
    llm: Any,
    found: Extraction,
    known: tuple[str, ...] = (),
    now: datetime | None = None,
    place: str = "",
) -> Extraction:
    facts = [str(item).strip()[:160] for item in known if str(item).strip()][:8]
    # The place alone is reason enough to make this call: without it the
    # listing has no idea how far away anything is.
    if not found.events or (not facts and not place) or llm is None:
        return found
    listing = "\n".join(
        f"[{index}] {event.name} at {event.venue}"
        + (f", {event.area}" if event.area else "")
        + (f" - {event.artist}" if event.artist else "")
        + f" ({event.what})"
        for index, event in enumerate(found.events, start=1)
    )
    about = "\n".join(f"- {fact}" for fact in facts) or "- nothing in particular is known about them"
    if place:
        about = f"- they are in {place}\n{about}"
    try:
        messages = [
            {"role": "system", "content": load("search/event_lines")},
            {
                "role": "user",
                "content": f"The person:\n{about}\n\nThe events:\n\n{listing}",
            },
        ]
        answer = await asyncio.to_thread(llm.chat, messages, _MAX_TOKENS, _LINES_SCHEMA, 0.0)
    except Exception:
        logger.warning("Event description call failed; keeping the plain lines", exc_info=True)
        return found
    written: dict[int, str] = {}
    payload = answer
    if isinstance(payload, dict) and "content" in payload:
        payload = payload["content"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return found
    far: set[int] = set()
    for row in (payload or {}).get("lines", []) if isinstance(payload, dict) else []:
        if not isinstance(row, dict):
            continue
        index = _index(row.get("index"), len(found.events))
        if index is None:
            continue
        line = _own_words(row.get("what"))
        if line:
            written[index] = line
        # Only a place makes "near" meaningful; with none, everything stays.
        if place and row.get("near") is False:
            far.add(index)
    if not written and not far:
        return found
    return replace(
        found,
        events=tuple(
            replace(event, what=written.get(index, event.what), near=index not in far)
            for index, event in enumerate(found.events, start=1)
        ),
    )
