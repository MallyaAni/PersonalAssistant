"""Scout's describing step: turn a scraped page into something decidable.

A recipient cannot judge "Nature and History Events – Official Website of
Arlington County Virginia Government" — that is a page title, not an event. The
deterministic half of this lives in `discovery/summarize.py` and never invents;
the prompt lives here, because it is Scout's judgement about what a find is and
whether the page says it is over, and no other agent would phrase it that way.

The safety story is deliberate and now down to one rule. Page text is untrusted
and the result is delivered to third parties, so the model answers into a
constrained schema with bounded fields and **no URL survives from model
output** — links in a message come from the typed record.

Nothing else post-processes what the model wrote. The schema is sent as a
decoding grammar, so its `maxLength` is enforced while the tokens are being
chosen; a second bound in code could only ever cut a sentence the runtime had
already agreed to keep short, and cutting it is what produced a description
stopping mid-clause. The deterministic summary no longer stands in for a failed
call either: a scraped first paragraph was never something a person could decide
on, and shipping one made a describing failure look like a description.

A grammar constrains shape, not meaning. A hostile page can still influence the
wording of its own description, the same way it can influence its own title. It
cannot inject a link, exceed the bound, or reach anything else.

`already_happened` is asked here and deliberately not trusted alone: a stated
deadline is read by `url_dates.deadline_has_passed`, after a digest offered a
vote that had closed a week earlier.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from backend.core.interfaces import TextWriter
from backend.core.prompts import load
from backend.discovery.summarize import (
    MAX_DESCRIPTION_CHARS,
    MAX_NAME_CHARS,
    MAX_SOURCE_CHARS,
    clean_title,
)

_URL_IN_TEXT = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Readable:
    """A find, in words a person can decide on."""

    title: str
    description: str | None
    # True only when the page itself says the thing is over. Defaults to False
    # so a find is never dropped because the model was not asked or failed.
    already_happened: bool = False
    # The dates the page states, resolved to ISO by the model and validated
    # here. None when the page states none - never guessed. These are what let
    # deterministic code do the past-event arithmetic the model was wrongly
    # trusted with: an audit found every selected web find undated, so a
    # county fair was sent five days after it ended.
    starts_on: date | None = None
    ends_on: date | None = None
    # True only when the page states or clearly implies the happening is
    # somewhere other than the reader's place. Town names repeat across
    # regions and search snippets rarely say which one they mean; the page
    # does, and the model reading it also knows where named venues are -
    # which is what a state-abbreviation table can never scale to. Defaults
    # to False so a failed call or an unlocated page never costs a find.
    located_elsewhere: bool = False
    # True only when the model reads the page as a listing of many happenings
    # - a search results page, a directory, a calendar - rather than one.
    # Describing one anyway produced a delivered find whose link opened a
    # city-wide search instead of the event it named. Defaults to False.
    lists_many: bool = False
    # True only when the page states who may attend and an approved fact
    # plainly rules this person out. An embedding cannot represent this:
    # no vector of an interest is far from an event that excludes the person
    # holding it. Defaults to False, so a page that names no audience, a
    # person with no facts on file, and a failed call all keep the find -
    # over-exclusion is the failure this question is most likely to cause.
    audience_rules_out: bool = False
    # The page's own words that caused it, kept so a drop can be explained
    # rather than only counted. Empty whenever nothing was dropped.
    stated_audience: str = ""


_SCHEMA: dict[str, Any] = {
    "title": "EventDescription",
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", "already_happened", "starts_on", "ends_on"],
    "properties": {
        "name": {
            "type": "string",
            "minLength": 3,
            "maxLength": MAX_NAME_CHARS,
        },
        "description": {
            "type": "string",
            "minLength": 10,
            "maxLength": MAX_DESCRIPTION_CHARS,
        },
        # Whether the page says this is over. Undated finds cannot be filtered
        # by any clock we hold — nobody published a start — so the only thing
        # that knows is the prose, which the model is already reading.
        "already_happened": {"type": "boolean"},
        # The stated date(s) as ISO, or null. The grammar admits nothing but a
        # date or null, and the parse below re-validates, so an invented or
        # malformed date cannot enter the pipeline.
        "starts_on": {
            "type": ["string", "null"],
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
        "ends_on": {
            "type": ["string", "null"],
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
    },
}

# The location question is its own call with its own prompt. Folded into the
# describe schema it measurably degraded the descriptions - the writing
# instructions and the location judgment compete in one small model - and a
# one-field grammar makes the verdict as constrained as an answer can be.
_LOCATE_SCHEMA: dict[str, Any] = {
    "title": "EventLocation",
    "type": "object",
    "additionalProperties": False,
    "required": ["located_elsewhere"],
    "properties": {"located_elsewhere": {"type": "boolean"}},
}

# Same shape, different question: is this page a listing rather than one
# happening? Its own call for the same reason locate is - a focused boolean
# stays reliable where a fact folded into the writing prompt drifted it.
_LISTING_SCHEMA: dict[str, Any] = {
    "title": "PageKind",
    "type": "object",
    "additionalProperties": False,
    "required": ["lists_many"],
    "properties": {"lists_many": {"type": "boolean"}},
}

# How much of the person's approved context the audience judge sees. The
# reader already bounds each statement and the count of them; this is the
# belt-and-braces bound on the rendered block, so one long memory cannot grow
# a per-find prompt.
MAX_FACTS_CHARS = 1_200

# How much of the page's stated audience is kept. Long enough for a sentence
# saying who may attend, short enough that it cannot carry a page into a log.
MAX_AUDIENCE_CHARS = 200

# The reading comes before the verdict, and the order is load-bearing rather
# than cosmetic: a decision field answered first is a guess the rest of the
# object then justifies. Measured here 2026-09-12 - asked for the verdict
# alone, a wine festival stating no restriction was ruled out 3/3 for someone
# whose fact was that they do not drink.
_AUDIENCE_SCHEMA: dict[str, Any] = {
    "title": "EventAudience",
    "type": "object",
    "additionalProperties": False,
    "required": ["stated_audience", "rules_out"],
    "properties": {
        "stated_audience": {"type": "string", "maxLength": MAX_AUDIENCE_CHARS},
        "rules_out": {"type": "boolean"},
    },
}

_PROMPT = load("scout/describe")
_LOCATE_PROMPT = load("scout/locate")
_LISTING_PROMPT = load("scout/listing")
_AUDIENCE_PROMPT = load("scout/audience")

# Sent only to a writer whose engine enforces no grammar, where the shape has
# to be asked for in words. Deliberately not in describe.md: folded into the
# shared prompt it perturbed the grammar path's prose enough to fail two
# description gates that have nothing to do with format.
_JSON_TAIL = (
    "\n\nAnswer with only a JSON object - no code fence, no text around it - "
    'shaped exactly like this: {"name": "...", "description": "...", '
    '"already_happened": false, "starts_on": "YYYY-MM-DD" or null, '
    '"ends_on": "YYYY-MM-DD" or null}.'
)


# A model-stated date, or nothing. The grammar constrains the shape; this
# constrains the meaning - fromisoformat rejects the well-formed impossible
# ("2026-02-31") that a pattern cannot.
def _valid_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# A model-written name, or nothing when it cannot be used.
#
# The one rule left on model output: a link must never originate from it. Nothing
# else here trims, bounds or rewrites what the model wrote — the schema is sent
# as a decoding grammar, so `maxLength` is enforced while the tokens are chosen
# rather than afterwards, and a second bound in code could only ever cut a
# sentence the runtime had already agreed to keep short.
#
# This is presentation only — the name a model writes reaches the reader, never
# identity. Novelty, familiarity and ranking have all been decided on the
# source's own title by the time this runs, so a rephrasing here cannot change
# what was chosen or make a seen item look new.
def _safe_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(_URL_IN_TEXT.sub(" ", value).split()) or None


class EventDescriber:
    """Write a find's name and description, or leave it undescribed.

    Two writers, one contract. `writer` is the best prose model available and
    is asked first, because this text is what a person actually reads and a
    small model's descriptions read small - "features a Family Day with Jr.
    Docents" reached a real phone. Its answer is JSON by instruction, held to
    the schema by the validation below rather than by a grammar, since the
    deployed harness enforces none. `structured_writer` is the grammar
    engine, kept as the fallback: when the prose model's answer does not
    survive validation, the enforced call still produces a usable answer
    rather than a raw scraped title.
    """

    def __init__(
        self,
        writer: TextWriter | None,
        structured_writer: TextWriter | None = None,
    ) -> None:
        self.writer = writer
        self.structured = structured_writer

    # One focused boolean judgement about the page, answered by the model
    # that reads it. Fail-open on every edge: nothing to read, no judge, or
    # a failed call all keep the find - only a parsed true acts.
    async def _page_verdict(
        self, prompt: str, schema: dict[str, Any], field: str
    ) -> bool:
        judge = self.structured or self.writer
        if judge is None:
            return False
        try:
            result = await asyncio.to_thread(
                judge.chat,
                [{"role": "user", "content": prompt}],
                16,
                schema,
                0.0,
            )
            return json.loads(result["content"]).get(field) is True
        except Exception:
            return False

    # Does the page place this happening away from the reader's area? Asked
    # of a model because town names repeat across regions and a venue's
    # whereabouts is world knowledge no lookup table scales to. The URL is
    # read as data with the text: the snippet is the search engine's summary
    # and a page's address is where it says it is, which is what caught a
    # "guided walk at Arlington" that was at Arlington Court in Devon.
    async def _located_elsewhere(
        self, title: str, source: str, place: str | None, url: str | None = None
    ) -> bool:
        if not place or not source:
            return False
        prompt = _LOCATE_PROMPT.format(
            title=title,
            source=source[:MAX_SOURCE_CHARS],
            place=place,
            url=" ".join((url or "").split())[:300],
        )
        return await self._page_verdict(prompt, _LOCATE_SCHEMA, "located_elsewhere")

    # Is the page a listing of many happenings rather than one? Asked of the
    # model for the same reason: the structural title-and-URL filter only
    # knows the shapes it has already seen, and the page's own text says
    # what it is to anything that reads it.
    async def _lists_many(self, title: str, source: str) -> bool:
        if not source:
            return False
        prompt = _LISTING_PROMPT.format(title=title, source=source[:MAX_SOURCE_CHARS])
        return await self._page_verdict(prompt, _LISTING_SCHEMA, "lists_many")

    # The page's own words saying who may attend, when an approved fact rules
    # this person out of them - and "" whenever it does not, which is the
    # answer in every other case including a failed call. Returning the quoted
    # words rather than a boolean is what lets the caller refuse a verdict with
    # no evidence behind it, and is what a person is owed if they ask why a
    # find never reached them.
    #
    # Asked separately for the reason locate.md was split out of describe.md:
    # one small model holding a writing task and a judgement at once does both
    # worse. Asked only when there are facts to judge against, so an account
    # with no memory spends nothing here.
    async def _audience_rules_out(self, title: str, source: str, facts: str) -> str:
        if not facts or not source:
            return ""
        judge = self.structured or self.writer
        if judge is None:
            return ""
        prompt = _AUDIENCE_PROMPT.format(
            title=title,
            source=source[:MAX_SOURCE_CHARS],
            facts=facts[:MAX_FACTS_CHARS],
        )
        try:
            result = await asyncio.to_thread(
                judge.chat,
                [{"role": "user", "content": prompt}],
                # Room for a quoted sentence as well as the verdict.
                120,
                _AUDIENCE_SCHEMA,
                0.0,
            )
            answer = json.loads(result["content"])
        except Exception:
            # Fail open, like every other page verdict: a judge that is down
            # must cost nobody a find.
            return ""
        if answer.get("rules_out") is not True:
            return ""
        # The verdict alone is not enough to act on. A restriction the model
        # could not quote from the page is one it inferred, and inferring is
        # the failure this whole question is most likely to produce - a taste
        # read as an eligibility bar, an attribute read off a name. Requiring
        # the evidence puts that rule in code rather than asking the prompt to
        # hold it twice.
        stated = str(answer.get("stated_audience") or "").strip()
        return stated[:MAX_AUDIENCE_CHARS]

    # One writer's answer, parsed - or None when the call failed or returned
    # something other than JSON. Validation happens on the caller.
    async def _ask(self, writer: TextWriter, prompt: str) -> dict | None:
        try:
            result = await asyncio.to_thread(
                writer.chat,
                [{"role": "user", "content": prompt}],
                # Room for the fields plus a written sentence. Greedy, because
                # a description that changes between runs of the same page is
                # a bug, not variety.
                220,
                # Sent to both writers: a grammar engine decodes inside it,
                # and one that cannot still gets the instruction text below.
                _SCHEMA,
                0.0,
            )
            payload = json.loads(result["content"])
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    # Does a parsed answer carry a usable description? A grammar enforces
    # the bounds during decoding; the prose writer's answer is only held to
    # them here. Overlength is rejected rather than truncated - cutting
    # produced descriptions stopping mid-clause, and the fallback writer
    # answering inside the grammar is strictly better than a trimmed
    # sentence. The description alone decides: a missing or unusable name
    # falls back to the cleaned source title, exactly as it always has, and
    # must not cost a good sentence.
    @staticmethod
    def _valid(payload: dict | None) -> bool:
        if payload is None:
            return False
        written = payload.get("description")
        if not isinstance(written, str) or not written.strip():
            return False
        return len(written) <= MAX_DESCRIPTION_CHARS

    async def describe(
        self,
        title: str,
        source: str | None,
        today: date | None = None,
        place: str | None = None,
        url: str | None = None,
        facts: str = "",
    ) -> Readable:
        # The source's own title still prepares the prompt and still stands in
        # when there is no model answer at all. That is not a rewriting of what
        # the model said — it is what a find is called when nothing said
        # anything, and a find with no name cannot be rendered.
        cleaned = clean_title(title)
        if (self.writer is None and self.structured is None) or not source:
            return Readable(title=cleaned, description=None)

        # Asked first because a listing invalidates everything after it: a
        # description written off a directory names an event its link cannot
        # honor, so nothing else about the page is worth a model call.
        if await self._lists_many(cleaned, source):
            return Readable(title=cleaned, description=None, lists_many=True)

        elsewhere = await self._located_elsewhere(cleaned, source, place, url)

        # Asked before the description is written, and answered from the page
        # rather than the snippet, because a stated audience is usually said
        # once and in the page's own words. Returning here also saves the
        # description call on a find the caller is about to drop.
        stated = await self._audience_rules_out(cleaned, source, facts)
        if stated:
            return Readable(
                title=cleaned,
                description=None,
                located_elsewhere=elsewhere,
                audience_rules_out=True,
                stated_audience=stated,
            )

        prompt = _PROMPT.format(
            title=cleaned,
            source=source[:MAX_SOURCE_CHARS],
            description_limit=MAX_DESCRIPTION_CHARS,
            today=(today or datetime.now(UTC).date()).isoformat(),
        )
        payload = None
        if self.writer is not None:
            # With a fallback configured, the primary is the prose model whose
            # engine enforces nothing, so the shape is asked for in words.
            # Alone, the writer is a grammar engine and gets the clean prompt.
            asked = prompt + _JSON_TAIL if self.structured is not None else prompt
            payload = await self._ask(self.writer, asked)
        if not self._valid(payload) and self.structured is not None:
            payload = await self._ask(self.structured, prompt)

        if payload is not None and self._valid(payload):
            written = payload.get("description")
            named = payload.get("name")
            over = payload.get("already_happened")
            starts_on = _valid_date(payload.get("starts_on"))
            ends_on = _valid_date(payload.get("ends_on"))
        else:
            written = named = None
            over = payload.get("already_happened") if payload else None
            starts_on = _valid_date(payload.get("starts_on")) if payload else None
            ends_on = _valid_date(payload.get("ends_on")) if payload else None

        if not isinstance(written, str) or not written.strip():
            # No deterministic summary stands in for a failed call any more. A
            # scraped first paragraph was never something a person could decide
            # on, and shipping one made a describing failure invisible; a find
            # with no description now renders as its name, date and link. The
            # verdicts still carry: a parsed answer that said "this is over"
            # or "this is elsewhere" holds even when the sentence was unusable.
            return Readable(
                title=_safe_name(named) or cleaned,
                description=None,
                already_happened=over is True,
                starts_on=starts_on,
                ends_on=ends_on,
                located_elsewhere=elsewhere,
            )

        # The one rule left: a link must never originate from model output, and
        # links in a message come from the typed record. Anything URL-shaped is
        # removed rather than trusted.
        safe = " ".join(_URL_IN_TEXT.sub(" ", written).split())
        return Readable(
            title=_safe_name(named) or cleaned,
            description=safe or None,
            already_happened=over is True,
            starts_on=starts_on,
            ends_on=ends_on,
            located_elsewhere=elsewhere,
        )
