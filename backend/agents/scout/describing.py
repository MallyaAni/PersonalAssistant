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

_PROMPT = load("scout/describe")


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
    """Write a find's name and description, or leave it undescribed."""

    def __init__(self, writer: TextWriter | None) -> None:
        self.writer = writer

    async def describe(
        self,
        title: str,
        source: str | None,
        today: date | None = None,
    ) -> Readable:
        # The source's own title still prepares the prompt and still stands in
        # when there is no model answer at all. That is not a rewriting of what
        # the model said — it is what a find is called when nothing said
        # anything, and a find with no name cannot be rendered.
        cleaned = clean_title(title)
        if self.writer is None or not source:
            return Readable(title=cleaned, description=None)

        prompt = _PROMPT.format(
            title=cleaned,
            source=source[:MAX_SOURCE_CHARS],
            description_limit=MAX_DESCRIPTION_CHARS,
            today=(today or datetime.now(UTC).date()).isoformat(),
        )
        try:
            result = await asyncio.to_thread(
                self.writer.chat,
                [{"role": "user", "content": prompt}],
                # The schema is sent as a decoding grammar, so the runtime cannot
                # emit anything outside it. Greedy, because a description that
                # changes between runs of the same page is a bug, not variety.
                160,
                _SCHEMA,
                0.0,
            )
            payload = json.loads(result["content"])
            written = payload.get("description")
            named = payload.get("name")
            over = payload.get("already_happened")
            starts_on = _valid_date(payload.get("starts_on"))
            ends_on = _valid_date(payload.get("ends_on"))
        except Exception:
            written, named, over = None, None, None
            starts_on = ends_on = None

        if not isinstance(written, str) or not written.strip():
            # No deterministic summary stands in for a failed call any more. A
            # scraped first paragraph was never something a person could decide
            # on, and shipping one made a describing failure invisible; a find
            # with no description now renders as its name, date and link.
            return Readable(title=_safe_name(named) or cleaned, description=None)

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
        )
